"""YAML load/save for Snapshot objects.

Round-trip identity is the contract: ``load_snapshot(save_snapshot(s)) == s``
for any snapshot whose fields validate. Reader is strict about schema
version mismatches — that's the diff-layer's escape hatch when an old
snapshot would otherwise be silently misinterpreted.

Writes route through ``atomic_write_text`` (#39) so an interrupted
``save_snapshot`` cannot leave a snapshot YAML zero-length or partial.
"""

from __future__ import annotations

import contextlib
import fnmatch
import os
import sys
import tempfile
from os import PathLike
from pathlib import Path
from typing import Any

import yaml

from .schema import SCHEMA_VERSION, Snapshot, SnapshotValidationError

PathArg = str | PathLike[str]

#: The one definition of what counts as a snapshot file on disk (#135).
#:
#: The opinionated ``*.snapshot.yaml`` convention is preferred for fresh
#: projects (it clearly distinguishes snapshot files from other YAML in the
#: repo), but the plain ``.yml`` / ``.yaml`` extensions are also accepted so
#: the committed ``examples/snapshots/*.yml`` files — and whatever convention
#: an operator already uses — work without renames.
#:
#: This lived in three modules (``cli``, ``validate``, ``stats``) behind
#: comments asking the next author to keep them in sync. They had already
#: drifted: ``stats`` carried only the last two patterns, so it reported a
#: narrower "patterns considered" list than its siblings. The set of files
#: walked happened to stay identical, because the two patterns it kept are
#: supersets of the two it dropped — an accident, not a design.
#:
#: ``io`` is the home because it imports only ``schema``, and ``cli``,
#: ``validate``, and ``stats`` all already import it. That sidesteps the
#: circular import (``cli`` pulls in ``validate``) which is why these were
#: separate in the first place.
SNAPSHOT_GLOBS: tuple[str, ...] = (
    "*.snapshot.yaml",
    "*.snapshot.yml",
    "*.yml",
    "*.yaml",
)


def iter_snapshot_paths(snapshots_dir: PathArg) -> list[Path]:
    """Every snapshot file under ``snapshots_dir``, recursively, deduped.

    Patterns overlap (``*.yml`` also matches ``*.snapshot.yml``), so a file
    matching more than one is yielded once. The result is sorted, so callers
    get a stable order regardless of filesystem enumeration order.

    Extension matching is **case-insensitive** (#144). It used to be
    ``root.rglob(pattern)``, and ``pathlib``'s glob is case-sensitive on every
    platform, so a snapshot whose extension was not lowercase was invisible to
    the whole suite. Measured on seven well-formed files in one directory::

        one.snapshot.yaml     WALKED
        two.snapshot.yaml     WALKED
        three.snapshot.YAML   SILENTLY SKIPPED
        four.SNAPSHOT.yaml    WALKED
        five.Yml              SILENTLY SKIPPED
        six.yaml              WALKED
        seven.YML             SILENTLY SKIPPED

        found: 4 of 7   ->   validate_snapshots reported CLEAN

    All three consumers share this walker -- ``validate``, ``stats``, and
    ``cli._run_command``, the regression check itself -- so those three files
    were not merely unvalidated, they were never *run*. The `run` summary then
    reports ``total=len(snapshot_paths)``, which counts only what was walked, so
    there is nothing for an operator to notice the gap against. The
    "no snapshot files" error only fires on *zero* matches, which is the one
    case a real repository never hits.

    Note ``four.SNAPSHOT.yaml`` was walked while ``three.snapshot.YAML`` was
    not: only the final extension's case mattered, so the old behaviour was not
    even consistent across mixed-case names. And on a case-insensitive
    filesystem (APFS, NTFS) those two spellings denote the *same file*, yet the
    match was case-sensitive regardless -- so whether a snapshot ran depended on
    how it happened to be typed, not on anything the filesystem treats as
    meaningful.

    This restores what ``SNAPSHOT_GLOBS`` above already says it is for:
    "whatever convention an operator already uses -- work without renames".

    ``SNAPSHOT_GLOBS`` stays the single definition. #135 consolidated it here
    after three modules had drifted, so the matching is done *against* it rather
    than by re-listing the extensions with case variants.
    """
    root = Path(snapshots_dir)
    seen: set[Path] = set()
    out: list[Path] = []
    # One walk, matching each name case-insensitively against the patterns --
    # rather than one `rglob` per pattern -- because `rglob` is where the
    # case-sensitivity lives. The patterns are already lowercase, so lowering
    # the candidate name is all that is needed.
    for p in root.rglob("*"):
        # Deliberately NOT filtered to `is_file()`. A *directory* whose name
        # matches a snapshot glob is yielded, exactly as the old per-pattern
        # `rglob` yielded it, so `validate` still reports it as an `unreadable`
        # finding rather than aborting the walk (#133). Filtering it here would
        # make it vanish silently -- the same class of defect this change
        # exists to fix, reintroduced one line away.
        name = p.name.lower()
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in SNAPSHOT_GLOBS) and p not in seen:
            seen.add(p)
            out.append(p)
    out.sort()
    return out


# Cap the target basename's contribution to the temp filename. The temp name is
# `.<base>.<random>.tmp`; the affixes add ~13-20 bytes, so prepending a full
# basename that is itself near NAME_MAX (255 on ext4/APFS) overflows the limit
# and the write fails with `OSError: [Errno 63] File name too long` — even though
# a plain `Path.write_text` of that same target succeeds (sibling of
# rag-production-kit#128 and mcp-server-cookbook#96). The base in the temp name
# is cosmetic (`ls`-ability); uniqueness comes from `NamedTemporaryFile`'s random
# component, so truncating it is safe. Budget is in BYTES (NAME_MAX is a byte
# limit) and we trim on a char boundary so multibyte names are never split
# mid-codepoint.
_MAX_TEMP_BASE_BYTES = 200


def _name_bytes(base: str) -> int:
    """Length of *base* in the bytes the filesystem actually sees.

    ``os.fsencode``, not ``base.encode("utf-8")`` (#159). Both halves of the
    comment above are true and the old implementation still counted the wrong
    bytes: NAME_MAX limits the bytes handed to the kernel, which is
    ``os.fsencode`` — ``sys.getfilesystemencoding()`` together with
    ``sys.getfilesystemencodeerrors()``, i.e. ``surrogateescape`` on POSIX.

    That handler is why the distinction bites rather than being pedantry. A
    path byte that is not valid UTF-8 arrives in Python as a lone surrogate in
    ``U+DC80..U+DCFF``, and strict ``str.encode("utf-8")`` refuses to encode
    it — so ``_cap_base_for_temp`` used to raise ``UnicodeEncodeError`` on a
    destination the OS can name, *before* reaching the length question.
    ``sys.argv`` decodes with the same handler, so a shell
    ``--out $'report\\xff'`` is enough.

    ``UnicodeEncodeError`` is a ``ValueError``, so none of the three write-seam
    guards catches it: ``cli._write_output`` (the shared ``run`` / ``diff`` /
    ``validate`` ``--out`` seam), ``cli``'s ``update`` snapshot save, and
    ``scripts/render_regression_demo.py`` all catch ``OSError`` alone. The
    interpreter's uncaught-exception path then exits 1 — and 1 is not a generic
    error in this CLI. The read-seam guards name it every time they are
    explained: a bad input "must land as a clean ``error:`` + exit 2, not
    escape ``main`` as a raw traceback at exit 1 — the *regressions found*
    code". On a clean snapshots directory that hands a gating CI job the answer
    "regressions were found" over a byte in the filename.

    ``os.fsencode`` never raises: ``surrogateescape`` on POSIX,
    ``surrogatepass`` on Windows, so every ``str`` a ``Path`` can hold
    round-trips. For a name that is valid UTF-8 it returns exactly the old
    number, so the budget is unchanged for every name that worked before.
    """
    return len(os.fsencode(base))


def _cap_base_for_temp(base: str) -> str:
    if _name_bytes(base) <= _MAX_TEMP_BASE_BYTES:
        return base
    out = base
    while out and _name_bytes(out) > _MAX_TEMP_BASE_BYTES:
        out = out[:-1]
    return out


def atomic_write_text(path: PathArg, text: str) -> None:
    # `Path.write_text` is not atomic: SIGINT/SIGTERM/disk-full/OOM
    # between the implicit `open(..., "w")` truncate and `close()`
    # flush leaves the destination zero-length or partial. For this
    # repo the load-bearing case is `save_snapshot` — corrupting a
    # snapshot YAML breaks the round-trip-identity contract that the
    # diff layer relies on. The same harm class applies to CLI
    # `--out` artifacts and the HTML demo report.
    #
    # Pattern mirrors `llm-eval-harness/eval_harness/cli.py::_atomic_write_text`
    # (#48 there) and `llm-cost-optimizer/scripts/_io.py::atomic_write_text`
    # (#42 there) so the portfolio-wide shape is uniform.
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{_cap_base_for_temp(target.name)}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if tmp_path is not None:
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()


def save_snapshot(snapshot: Snapshot, path: PathArg) -> Path:
    """Write a snapshot to ``path`` as YAML. Returns the resolved path.

    The output is deterministic (sorted keys turned off so author order
    survives, default_flow_style=False so blocks are readable in PR diffs).
    Atomic via ``atomic_write_text``.
    """
    p = Path(path)
    payload = snapshot.to_dict()
    rendered = yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    atomic_write_text(p, rendered)
    return p


def load_snapshot(path: PathArg) -> Snapshot:
    """Read a snapshot YAML file from ``path``.

    Validates schema_version against the package's current SCHEMA_VERSION;
    raises ``SnapshotValidationError`` on mismatch so callers can decide
    whether to migrate or skip.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data: Any = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SnapshotValidationError(f"{p}: snapshot YAML must be a mapping at the top level")
    version = data.get("schema_version", SCHEMA_VERSION)
    # YAML parses an unquoted `schema_version: 1` as the int 1, not the string
    # "1". `save_snapshot` writes the quoted '1', but a hand-authored /
    # PR-reviewed snapshot (the D-003 use case) naturally omits the quotes —
    # and an int-vs-str rejection here reads as a baffling "is 1 … supports
    # '1'". Compare on the string form so `1` and `'1'` are the same version,
    # while a genuinely-different version ("2", 2, "1.5") still rejects.
    if str(version) != SCHEMA_VERSION:
        raise SnapshotValidationError(
            f"{p}: snapshot schema_version is {version!r}, "
            f"this reader only supports {SCHEMA_VERSION!r}",
            # The single source of the `schema_version` finding code (#155).
            # Every other raise in this package takes the `"schema"` default.
            code="schema_version",
        )
    # Normalize to the canonical string before `from_dict`, whose strict
    # `_require_str(schema_version)` would otherwise re-reject the int form.
    return Snapshot.from_dict({**data, "schema_version": SCHEMA_VERSION})


def _eprint(message: str) -> None:
    r"""Write *message* to `sys.stderr`, and never raise doing it (#160).

    Every diagnostic in this CLI interpolates operator input -- a `--out`
    destination, a snapshots directory, a snapshot path. `sys.argv` decodes
    with `surrogateescape`, so any of those can hold a lone surrogate in
    `U+DC80..U+DCFF`, which has no UTF-8 encoding. Writing the message is then
    a candidate for the very `UnicodeEncodeError` the message is reporting, and
    the guard dies inside its own `print` instead of returning 2.

    It does not fire on a real process: CPython gives `sys.stderr`
    `errors="backslashreplace"`, so the message renders as `report\udcff.json`
    and the exit code is 2 as documented. It fires the moment `sys.stderr` is a
    stream with a strict handler -- which `pytest`'s `capsys` is, and which is
    how this was found while writing the tests for #159.

    **The helper, rather than `ascii()` at each interpolation site.** #160 was
    filed against "all three write-seam guards"; re-measuring found five sites
    across four subcommands, and the two the count missed were *read* seams
    (`validate <bad dir>`, `diff --snapshot <bad>`). Hand-listing the sites is
    what produced that miscount, and a sixth message added later would rejoin
    the gap silently. Every write to `sys.stderr` is a population a lock can
    check mechanically; "every message that happens to interpolate a path" is
    not. `tests/test_stderr_totality.py` holds both halves.

    The retry escapes through stderr's *own* encoding rather than through
    `ascii()`, so an ordinary non-ASCII diagnostic -- a snapshot id with an
    accent, a CJK path -- is still printed as itself, and only the run that
    genuinely cannot be encoded degrades. `ascii()` on every message would make
    the error path total and every non-ASCII message unreadable, which is the
    plausible over-broad fix rather than this one.

    **Not claimed:** that the CLI is total. `argparse` interpolates the same
    operator path into its own `error: unrecognized arguments: ...` and writes
    it to `sys.stderr` before any code here runs. That is stdlib and out of
    reach of a message-level fix; the scope here is every message this package
    writes.
    """
    try:
        print(message, file=sys.stderr)
    except UnicodeEncodeError:
        encoding = getattr(sys.stderr, "encoding", None) or "utf-8"
        print(
            message.encode(encoding, "backslashreplace").decode(encoding, "replace"),
            file=sys.stderr,
        )
