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
import errno
import fnmatch
import math
import os
import secrets
import stat
import sys
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, date, datetime
from os import PathLike
from pathlib import Path
from typing import Any, TextIO

import yaml

from .diff import canonical_slot_failures, describe_slot_failures
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
# is cosmetic (`ls`-ability); uniqueness comes from the random component
# `_open_temp` appends (and its `O_EXCL` retry), so truncating it is safe. Budget is in BYTES (NAME_MAX is a byte
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


# How many random names `_open_temp` tries before giving up. Mirrors
# `tempfile.TMP_MAX`; a collision on 32 random bits is already vanishingly rare.
_TEMP_ATTEMPTS = 10000


def _open_temp(target: Path) -> tuple[TextIO, Path]:
    """Create ``.<base>.<random>.tmp`` beside *target*; return ``(file, path)``.

    The file is created with mode ``0o666`` so the KERNEL applies the process
    umask, exactly as ``Path.write_text`` / ``open(..., "w")`` do (#189). This
    replaced ``tempfile.NamedTemporaryFile``, which always creates 0600
    whatever the umask is, so every snapshot and ``--out`` artifact came out
    owner-only. The umask is deliberately never read through
    ``os.umask(0); os.umask(old)``: that sets a process-wide umask of 0 for
    every other thread until it is restored.

    The temp file stays in the target's directory so ``os.replace`` is a
    same-filesystem rename. The descriptor goes through ``open(..., opener=)``
    so the file object owns it from birth; if ``open`` fails after the file was
    created, this function unlinks it, so no ``.tmp`` is left behind.
    """
    prefix = f".{_cap_base_for_temp(target.name)}."
    for _ in range(_TEMP_ATTEMPTS):
        candidate = target.parent / f"{prefix}{secrets.token_hex(4)}.tmp"
        created = False

        def _create_0o666(name: str, flags: int) -> int:
            nonlocal created
            fd = os.open(name, flags | os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            created = True
            return fd

        try:
            # The caller owns the handle (it writes, fsyncs and closes it).
            fh = open(candidate, "x", encoding="utf-8", opener=_create_0o666)  # noqa: SIM115
        except FileExistsError:
            if created:
                raise
            continue
        except BaseException:
            if created:
                with contextlib.suppress(FileNotFoundError):
                    candidate.unlink()
            raise
        return fh, candidate
    raise FileExistsError(errno.EEXIST, "no usable temporary file name found", str(target.parent))


def _preserve_target_mode(tmp_path: Path, target: Path) -> None:
    """Give *tmp_path* the permission bits *target* has now, if it exists.

    ``os.replace`` carries the TEMP file's mode onto the target, so without
    this an overwrite silently re-moded the destination: under the old
    ``NamedTemporaryFile`` temp, a committed 0644 snapshot came back 0600 after
    ``prompt-snap update`` (#189). ``Path.write_text`` truncates in place and
    keeps the inode's mode; this is the rename-based equivalent. A missing
    target is not an error: a new file keeps the umask-derived mode
    ``_open_temp`` gave it.
    """
    try:
        mode = stat.S_IMODE(os.stat(target).st_mode)
    except FileNotFoundError:
        return
    os.chmod(tmp_path, mode)


def _resolve_symlinked_target(target: Path) -> Path:
    """The file a write to *target* lands in: through a symlink (#219).

    ``os.replace`` renames onto the LINK, not the file it points at, so a
    symlinked destination used to become a regular file while the linked file
    kept its old contents -- where ``Path.write_text``, the call this helper
    replaced, writes through the link. For a snapshot directory whose YAML is
    a link into a shared location, ``prompt-snap update`` silently forked the
    snapshot. ``_preserve_target_mode`` already followed the link
    (``os.stat``), so the helper copied the linked file's mode onto a file
    that then replaced the link instead. Sibling of
    python-async-llm-pipelines#157.

    Resolving here, before ``_open_temp``, puts the temp file beside the
    RESOLVED file, so the rename stays on one filesystem when the link points
    to another one, and the NAME_MAX cap above is applied to the name actually
    being replaced. A dangling link resolves to the path it names, which the
    write then creates, as ``Path.write_text`` would. A link loop is left as
    is by ``realpath`` and raises ``OSError`` (ELOOP) from
    ``_preserve_target_mode``, again as ``Path.write_text`` does -- so the
    CLI's ``except OSError`` write seams still turn it into ``error:`` + exit
    2. A plain path is returned unchanged, so no existing caller sees a
    different path.
    """
    if not target.is_symlink():
        return target
    return Path(os.path.realpath(target))


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
    #
    # File mode matches `Path.write_text` (#189): a new file gets
    # `0o666 & ~umask` and an overwrite keeps the existing file's mode. See
    # `_open_temp` and `_preserve_target_mode`.
    #
    # A symlinked destination is written THROUGH, as `Path.write_text` does:
    # the link stays a link and the file it names gets the new contents (#219).
    # See `_resolve_symlinked_target`.
    target = _resolve_symlinked_target(Path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        tmp, tmp_path = _open_temp(target)
        with tmp:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        _preserve_target_mode(tmp_path, target)
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
    # The rule `load_snapshot` states, applied here too (#165). Before any bytes
    # are written, so a refusal cannot truncate or half-overwrite a snapshot
    # that was already on disk -- and through the same helper, because the
    # comparison's `str()` leniency is the half a second copy would omit.
    _require_supported_schema_version(snapshot.schema_version, str(p))
    # The invariant `update` has refused to break since #207, held by the library
    # writer too (#276): a canonical that fails its own `structured_slots` is a
    # baseline that fails a diff against itself (cosine 1.0, verdict fail), and
    # `validate` now reports one on disk as `canonical_slots`. Refused before any
    # bytes are written, for the same reason as the version check above. Not in
    # `Snapshot.__post_init__` / `load_snapshot`: a reader that refused it would
    # leave `update` -- the remedy -- unable to open the file it has to repair.
    failing = canonical_slot_failures(
        snapshot.response_shape.structured_slots, snapshot.canonical.text
    )
    if failing:
        raise SnapshotValidationError(
            f"{p}: refusing to write a snapshot whose canonical.text fails its own "
            f"structured_slots ({describe_slot_failures(failing)}), so it would fail a "
            "diff against itself"
        )
    payload = snapshot.to_dict()
    # The write half of #278's cap, also before any bytes are written. Without
    # it a deep `prompt.extra` built in code either overflowed the stack below
    # or, under the cap's lower limit, was written as a file `load_snapshot`
    # now refuses.
    depth = _nesting_depth(payload, _value_children)
    if depth > _MAX_NESTING_DEPTH:
        raise SnapshotValidationError(f"{p}: snapshot {_nesting_problem(depth)}")
    rendered = yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    # The reader must invert the writer (#199). PyYAML writes U+0085 (NEL) raw
    # inside a quoted scalar and folds it to a space on load, so a canonical text
    # containing one came back different from the text its embedding was
    # computed from. When the readable unicode rendering does not load back to
    # what the escaped rendering does, write the escaped one -- so every other
    # snapshot stays byte-identical.
    escaped = yaml.safe_dump(
        payload, sort_keys=False, default_flow_style=False, allow_unicode=False
    )
    #
    # Compared with `_same_loaded_yaml`, not `!=` (#286). `!=` walks the fully
    # expanded structure, and `safe_dump` writes a shared node once with an
    # anchor: ten levels of ten aliases each in `prompt.extra`, a 3 KB file that
    # loads, validates and diffs in 0.1 s, made this one line take minutes.
    if not _same_loaded_yaml(yaml.safe_load(rendered), yaml.safe_load(escaped)):
        rendered = escaped
    atomic_write_text(p, rendered)
    return p


def _same_loaded_yaml(a: Any, b: Any, _seen: set[tuple[int, int]] | None = None) -> bool:
    """``a == b`` for two ``yaml.safe_load`` results, comparing a shared node once (#286).

    ``==`` on a container compares every path to a shared member again, so an
    alias graph costs its *expanded* size: exponential in its depth. Remembering
    each ``(id(a), id(b))`` pair already under comparison makes it linear in the
    loaded objects. A pair is recorded before its members are compared, which is
    safe because any mismatch below returns ``False`` all the way up. Leaves keep
    ``==``'s own rule, identity first, so the answer matches ``a == b`` and every
    snapshot without aliases picks the same rendering it did before. Recursive:
    both inputs are renderings of a payload ``save_snapshot`` has already held
    to ``_MAX_NESTING_DEPTH``.
    """
    if a is b:
        return True
    if type(a) is not type(b) or type(a) not in (dict, list, tuple):
        return bool(a == b)
    seen = set() if _seen is None else _seen
    pair = (id(a), id(b))
    if pair in seen:
        return True
    if len(a) != len(b):
        return False
    seen.add(pair)
    if type(a) is dict:
        return all(k in b and _same_loaded_yaml(v, b[k], seen) for k, v in a.items())
    return all(_same_loaded_yaml(x, y, seen) for x, y in zip(a, b, strict=True))


def _require_supported_schema_version(version: Any, where: str) -> None:
    """Raise unless *version* is the schema version this package reads (#165).

    One definition, called by ``load_snapshot`` on the way in and by
    ``save_snapshot`` on the way out. Before this, only the reader had the rule:
    ``Snapshot.__post_init__`` runs ``_require_str(self.schema_version)`` and
    stops, so the field was checked for being *a string* and never for being
    *the supported version*. The canonical writer therefore emitted files its
    own loader refuses. Measured::

        schema_version='1'   (control)   round-trips identically
        schema_version='2'               written, then refused on read
        schema_version='1.5'             written, then refused on read
        schema_version='01'              written, then refused on read
        schema_version=''                already refused at construction

    ``'01'`` is the row worth naming. The comparison is on ``str(version)`` --
    deliberately, because YAML parses an unquoted ``schema_version: 1`` as the
    int ``1`` while ``save_snapshot`` writes the quoted ``'1'``, and rejecting a
    hand-authored snapshot (the D-003 workflow) with "is 1 ... supports '1'"
    reads as nonsense. ``'01'`` is a string that survives that leniency and
    still fails, and nothing on the write side ever looked at it.

    The leniency is part of the shared rule rather than a caller's business,
    because a second copy of *it* is what would drift: the comparison is the
    obvious half and the ``str()`` is the half someone re-deriving would omit.

    ``code="schema_version"`` is preserved on both paths -- ``CODES`` exists so
    "migration tooling can route on the code without parsing the prose" (#155),
    and a write-side refusal is the same classification as a read-side one.
    """
    if str(version) != SCHEMA_VERSION:
        raise SnapshotValidationError(
            f"{where}: snapshot schema_version is {version!r}, "
            f"this reader only supports {SCHEMA_VERSION!r}",
            code="schema_version",
        )


class YAMLValueError(yaml.YAMLError):
    """A YAML scalar that matched a typed pattern but could not be built (#223)."""


_MERGE_TAG = "tag:yaml.org,2002:merge"


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """``SafeLoader`` that refuses a key repeated in one mapping (#243).

    PyYAML resolves a repeated key last-wins without a word, so a snapshot
    with a second ``tolerance:`` line passed ``validate`` clean and ``run``
    diffed against whichever came last. YAML requires unique keys. A ``<<``
    merge key is skipped: overriding a merged value is legal and is not a
    repeat of an explicit key.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        if isinstance(node, yaml.MappingNode):
            seen: set = set()
            for key_node, _ in node.value:
                if key_node.tag == _MERGE_TAG:
                    continue
                key = self.construct_object(key_node, deep=True)
                try:
                    repeated = key in seen
                except TypeError:
                    continue  # unhashable: the base class reports it
                if repeated:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"found duplicate key {key!r}",
                        key_node.start_mark,
                    )
                seen.add(key)
        return super().construct_mapping(node, deep=deep)

    # The read half of #278's nesting cap. Counted while composing, so a file
    # nested far past the cap is refused at the cap rather than at whatever
    # depth the stack happens to give out (the RecursionError #232 converts).
    # Only a collection is a level: a scalar leaf is not one to
    # `_nesting_depth`, and counting it here refused a file the writer had
    # just written at exactly the cap.
    _depth = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if not self.check_event(yaml.SequenceStartEvent, yaml.MappingStartEvent):
            return super().compose_node(parent, index)
        self._depth += 1
        try:
            if self._depth > _MAX_NESTING_DEPTH:
                raise yaml.composer.ComposerError(
                    None,
                    None,
                    f"nested deeper than {_MAX_NESTING_DEPTH} levels, "
                    "the deepest a snapshot can be written back (#278)",
                    self.peek_event().start_mark,
                )
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1

    def get_single_node(self) -> Any:
        # The composed count cannot see an alias: `*a` re-uses a node already
        # built elsewhere, so an alias chain nests past the cap in a file whose
        # every literal level is under it, and `&a [*a]` is a list that contains
        # itself. The writer walks the expanded structure, so the cap is checked
        # on it too (#278).
        node = super().get_single_node()
        if node is not None:
            depth = _nesting_depth(node, _node_children)
            if depth > _MAX_NESTING_DEPTH:
                raise yaml.composer.ComposerError(
                    None, None, _nesting_problem(depth), node.start_mark
                )
        return node


#: The deepest container nesting a snapshot may have, on read and on write
#: (#278). The top-level mapping is level 1, so ``prompt.extra``'s own mapping
#: is level 3.
#:
#: Derived from the writer, which is the side that runs out first. PyYAML's
#: representer recurses ``represent_data`` -> ``represent_list`` /
#: ``represent_dict`` -> ``represent_sequence`` / ``represent_mapping`` -- three
#: frames per level -- while the composer the reader runs costs two. Measured on
#: 3.11, 3.12 and 3.14 at the default recursion limit of 1000, the writer gives
#: out at ~329 levels and the reader at ~491, and with no explicit cap the
#: reader's limit was the stack's: a snapshot 340-480 deep loaded, validated and
#: diffed, and ``update --force`` died in ``save_snapshot`` with a traceback.
#: At 100 levels the writer needs 300 frames, under a third of the default
#: limit, which leaves the rest for whatever stack the caller is already on.
#: ``tests/test_nesting_depth_parity.py`` re-measures the per-level cost and
#: pins that budget.
_MAX_NESTING_DEPTH = 100


def _node_children(node: Any) -> list[Any] | None:
    if isinstance(node, yaml.MappingNode):
        return [part for pair in node.value for part in pair]
    if isinstance(node, yaml.SequenceNode):
        return list(node.value)
    return None


def _value_children(value: Any) -> list[Any] | None:
    if isinstance(value, Mapping):
        return [*value.keys(), *value.values()]
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return None


def _nesting_depth(root: Any, children: Callable[[Any], list[Any] | None]) -> float:
    """How many containers deep *root* nests; ``inf`` if it contains itself (#278).

    *children* returns a container's members, or ``None`` for a leaf (depth 0).
    One walker for both halves of the cap -- PyYAML nodes on read, the
    ``to_dict`` payload on write -- so the two cannot count differently.
    Iterative, because a recursive walk would fail on exactly the input it
    exists to refuse, and memoized, so an alias graph is walked once per node.
    """
    root_kids = children(root)
    if root_kids is None:
        return 0
    memo: dict[int, float] = {}
    on_path = {id(root)}
    # Each frame: the container, an iterator over its members, its deepest child.
    stack: list[tuple[Any, Iterator[Any], list[float]]] = [(root, iter(root_kids), [0])]
    while stack:
        obj, members, deepest = stack[-1]
        child = next(members, _NO_MORE)
        if child is _NO_MORE:
            stack.pop()
            on_path.discard(id(obj))
            memo[id(obj)] = deepest[0] + 1
            if stack:
                stack[-1][2][0] = max(stack[-1][2][0], deepest[0] + 1)
            continue
        if id(child) in on_path:
            return math.inf
        if id(child) in memo:
            deepest[0] = max(deepest[0], memo[id(child)])
            continue
        kids = children(child)
        if kids is not None:
            on_path.add(id(child))
            stack.append((child, iter(kids), [0]))
    return memo[id(root)]


_NO_MORE = object()


def _nesting_problem(depth: float) -> str:
    if depth == math.inf:
        return (
            "contains itself (a recursive alias), which a snapshot cannot be written back as (#278)"
        )
    return (
        f"nested {int(depth)} levels deep; the limit is {_MAX_NESTING_DEPTH}, "
        "the deepest a snapshot can be written back (#278)"
    )


def safe_load_yaml(stream: TextIO) -> Any:
    """``yaml.safe_load`` under the read seams' one parse-failure contract.

    PyYAML's constructors raise a plain ``ValueError`` -- not a ``YAMLError``
    -- for a scalar that matches a typed pattern but cannot be built: an
    impossible date in an unquoted timestamp (``created_at:
    2026-02-30T10:00:00Z``, the hand-authoring path #209 opened) or an integer
    past CPython's 4300-digit conversion limit. Every snapshot read seam
    catches ``yaml.YAMLError``, so that ``ValueError`` escaped all of them as a
    raw traceback at exit 1, and took ``validate``'s whole report down with it
    (#223). Re-raised here as a ``YAMLError`` so the existing ``parse`` routes
    handle it. ``UnicodeDecodeError`` is also a ``ValueError`` but already has
    its own route (#125), so it passes through untouched.

    ``RecursionError`` is not a ``ValueError`` either (#232). PyYAML's composer
    recurses once per nesting level, so a 2 KB file of a thousand ``[`` escaped
    the same way and took ``validate``'s report with it. It is converted too.

    A key repeated in one mapping is a ``ConstructorError`` (#243), not
    last-wins; see ``_UniqueKeySafeLoader``.
    """
    try:
        return yaml.load(stream, Loader=_UniqueKeySafeLoader)
    except UnicodeDecodeError:
        raise
    except ValueError as e:
        raise YAMLValueError(str(e)) from e
    except RecursionError as e:
        raise YAMLValueError("nested too deeply to parse") from e


def load_snapshot(path: PathArg) -> Snapshot:
    """Read a snapshot YAML file from ``path``.

    Validates schema_version against the package's current SCHEMA_VERSION;
    raises ``SnapshotValidationError`` on mismatch so callers can decide
    whether to migrate or skip.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data: Any = safe_load_yaml(f)
    if not isinstance(data, dict):
        raise SnapshotValidationError(f"{p}: snapshot YAML must be a mapping at the top level")
    version = data.get("schema_version", SCHEMA_VERSION)
    # YAML parses an unquoted `schema_version: 1` as the int 1, not the string
    # "1". `save_snapshot` writes the quoted '1', but a hand-authored /
    # PR-reviewed snapshot (the D-003 use case) naturally omits the quotes —
    # and an int-vs-str rejection here reads as a baffling "is 1 … supports
    # '1'". Compare on the string form so `1` and `'1'` are the same version,
    # while a genuinely-different version ("2", 2, "1.5") still rejects.
    # The single source of the `schema_version` finding code (#155) and, since
    # #165, of the rule itself -- `save_snapshot` calls the same helper, so the
    # writer cannot emit a version this reader refuses.
    _require_supported_schema_version(version, str(p))
    # Normalize to the canonical string before `from_dict`, whose strict
    # `_require_str(schema_version)` would otherwise re-reject the int form.
    normalized = {**data, "schema_version": SCHEMA_VERSION}
    # The same hand-authoring gap one field over (#209): YAML reads an unquoted
    # `created_at: 2026-05-18T16:10:00Z` as a `datetime`, and `from_dict`'s
    # `_require_str` then refused the whole snapshot ("Snapshot.created_at must
    # be a string, got datetime") from `validate`, `diff` and `run` alike.
    if "created_at" in data:
        normalized["created_at"] = _created_at_text(data["created_at"])
    return Snapshot.from_dict(normalized)


def _created_at_text(value: Any) -> Any:
    """The ISO-8601 UTC string a YAML timestamp was written as (#209).

    A tz-aware datetime is converted to UTC; a naive one is UTC already (YAML
    1.1 reads a timestamp without a zone as UTC). Both render in the shape
    `save_snapshot` writes, `%Y-%m-%dT%H:%M:%SZ`, with microseconds only when
    present. A bare date stays a date (`2026-05-18`). Anything else is passed
    through for `from_dict` to judge, so a non-string still fails loudly there.

    A tz-aware value at either end of the year range has no UTC form (#291):
    `9999-12-31T23:00:00-05:00` is in year 10000 once converted, and
    `0001-01-01T00:30:00+01:00` in year 0. `astimezone` raises `OverflowError`
    for both, which no read seam catches, so `validate`, `stats`, `diff` and
    `run` all died with a traceback at exit 1. It is refused as the
    `SnapshotValidationError` the field's other refusals raise, which every read
    seam already routes to a per-file finding / exit 2.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            utc = value.replace(tzinfo=UTC)
        else:
            try:
                utc = value.astimezone(UTC)
            except (OverflowError, ValueError) as e:
                raise SnapshotValidationError(
                    f"Snapshot.created_at {value.isoformat()} has no UTC form "
                    f"in the representable year range (#291): {e}"
                ) from e
        fmt = "%Y-%m-%dT%H:%M:%S.%fZ" if utc.microsecond else "%Y-%m-%dT%H:%M:%SZ"
        return utc.strftime(fmt)
    if isinstance(value, date):
        return value.isoformat()
    return value


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
    _write(message, sys.stderr)


def _print(message: str, *, end: str = "\n") -> None:
    r"""Write *message* to `sys.stdout`, and never raise doing it (#163).

    The stdout half of :func:`_eprint`, and the half that matters more on a
    real process. #160 built the stderr funnel and stated the reason the bug
    was hard to see: CPython gives `sys.stderr` ``errors="backslashreplace"``,
    so it only fires under a strict-handler stream like `pytest`'s `capsys`.
    That is true, and it is exactly the property `sys.stdout` does **not**
    have -- stdout is ``strict`` in an ordinary environment:

        stdout=strict  stderr=backslashreplace

    So the fix hardened the stream the interpreter had already made lenient
    and left the strict one bare. Two lines apart in ``cli.update``, the
    failure path went through ``_eprint`` and the success path through a bare
    ``print`` of the same ``snapshot_path`` -- meaning a successful update on
    an unencodable path wrote the file and *then* died announcing success.

    ``end`` passes through because two callers are relays
    (``capture_demo`` echoing a child's stdout, ``cli`` writing a
    pre-terminated rendered report) and a relay must not gain a newline.

    **Not claimed:** that the escape is invisible to a machine consumer.
    ``--format json`` emits a `str` this package built with `json.dumps`, so a
    snapshot id that cannot be encoded is written escaped -- valid JSON, and
    not byte-identical to the id on disk. `test_json_format_escape_is_stated`
    pins that rather than leaving it inferable; refusing such an id at load
    would be a snapshot-format policy, not a write-seam fix.
    """
    _write(message, sys.stdout, end=end)


def _write(message: str, stream: TextIO, *, end: str = "\n") -> None:
    """The retry both funnels share, so they cannot answer differently.

    Escaping through the stream's *own* encoding rather than `ascii()`: routing
    every message through `ascii()` makes the write total and every non-ASCII
    diagnostic unreadable, which is the plausible over-broad fix #160 measured
    and rejected. A `café` message with CJK in it is the row that separates the
    two, and it is asserted against both funnels.
    """
    try:
        print(message, file=stream, end=end)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        print(
            message.encode(encoding, "backslashreplace").decode(encoding, "replace"),
            file=stream,
            end=end,
        )
