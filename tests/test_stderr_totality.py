"""Every stderr message this package writes survives an unencodable path (#160).

Each diagnostic in this CLI interpolates operator input — a `--out`
destination, a snapshots directory, a snapshot path. `sys.argv` decodes with
`surrogateescape`, so any of those can hold a lone surrogate in
`U+DC80..U+DCFF`, which has no UTF-8 encoding. Writing the message is then a
candidate for the very `UnicodeEncodeError` the message is reporting, and the
guard dies inside its own `print` instead of returning 2.

It does not fire on a real process — CPython gives `sys.stderr`
`errors="backslashreplace"` — which is why the harness here *replaces*
`sys.stderr` with a strict-handler stream. That is not a contrivance: it is
what `pytest`'s own `capsys` does, and hitting it there is how #159 found this.

**Why the population is "every stderr write" and not "the write seams".**
#160 was filed against "all three write-seam guards". Re-measuring found five
failing sites across four subcommands, and the two the count missed were
*read* seams (`validate <bad dir>`, `diff --snapshot <bad>`). Hand-listing the
sites is what produced that miscount. So the fix is one helper, and the lock
below is on the mechanically-checkable population: nothing outside
`io._eprint` writes to `sys.stderr`.

**What is deliberately not claimed.** Not that the CLI is total. `argparse`
interpolates the same operator path into its own `error: unrecognized
arguments: ...` and writes it before any code here runs. That is stdlib, out
of reach of a message-level fix, and `test_argparse_is_a_known_gap` pins it as
a known gap rather than letting it read as coverage.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
from pathlib import Path
from typing import Any

import pytest

from prompt_regression import cli as cli_module
from prompt_regression.cli import build_parser, main
from prompt_regression.io import _eprint, load_snapshot, save_snapshot

#: What `surrogateescape` produces for the raw byte 0xFF — the shape an
#: operator actually creates with `--out $'report\xff.json'`.
SURROGATE = chr(0xDCFF)


def _strict_stderr() -> io.TextIOWrapper:
    """A `sys.stderr` whose error handler refuses what the default escapes."""
    return io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict", write_through=True)


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples" / "snapshots"


@pytest.fixture
def snapshots_dir(tmp_path: Path) -> Path:
    """A real, valid snapshot dir, built from the repo's committed example.

    Copied rather than hand-written so this file cannot drift out of the
    schema and start asserting exit 2 for the wrong reason.
    """
    d = tmp_path / "snaps"
    d.mkdir()
    save_snapshot(load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml"), d / "a.yml")
    return d


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------


def test_eprint_writes_an_ordinary_message_verbatim() -> None:
    err = _strict_stderr()
    with contextlib.redirect_stderr(err):
        _eprint("error: plain ascii")
    err.flush()
    assert err.buffer.getvalue().decode() == "error: plain ascii\n"  # type: ignore[attr-defined]


def test_eprint_leaves_ordinary_non_ascii_unescaped() -> None:
    """The anti-vacuous partner, and the one that kills the over-broad fix.

    Routing every message through `ascii()` would make the error path total and
    every non-ASCII diagnostic unreadable — a snapshot id with an accent, a CJK
    path. Only the run that genuinely cannot be encoded may degrade.
    """
    err = _strict_stderr()
    with contextlib.redirect_stderr(err):
        _eprint("error: could not load snapshot café/日本語.json")
    err.flush()
    written = err.buffer.getvalue().decode()  # type: ignore[attr-defined]
    assert "café/日本語.json" in written
    assert "\\u" not in written
    assert "\\x" not in written


def test_eprint_does_not_raise_on_an_unencodable_message() -> None:
    err = _strict_stderr()
    with contextlib.redirect_stderr(err):
        _eprint(f"error: failed to write report{SURROGATE}.json")
    err.flush()
    written = err.buffer.getvalue().decode()  # type: ignore[attr-defined]
    assert "failed to write report" in written
    assert ".json" in written
    # The offending run is escaped, not dropped: an operator has to be able to
    # tell that a byte was there at all.
    assert "\\udcff" in written


def test_eprint_escapes_only_the_offending_run() -> None:
    """The surrounding message — including its non-ASCII — must survive."""
    err = _strict_stderr()
    with contextlib.redirect_stderr(err):
        _eprint(f"error: café{SURROGATE}日本語")
    err.flush()
    written = err.buffer.getvalue().decode()  # type: ignore[attr-defined]
    assert "café" in written
    assert "日本語" in written
    assert "\\udcff" in written


# ---------------------------------------------------------------------------
# The CLI, driven end to end under a strict stderr
# ---------------------------------------------------------------------------


def _subcommands() -> list[str]:
    """Discovered from the argparse subparser registry, not listed.

    A hand-written list is the shape that produced #160's 3-vs-5 miscount one
    level down; repeating it here would be the same mistake about the same
    defect.
    """
    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public registry
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return sorted(action.choices)
    return []


def test_the_subcommand_discovery_is_not_vacuous() -> None:
    """A discovery that finds nothing makes every case below pass silently."""
    found = _subcommands()
    assert len(found) >= 5, found
    assert {"run", "update", "diff", "stats", "validate"} <= set(found), found


def _run_under_strict_stderr(argv: list[str]) -> tuple[Any, str]:
    err = _strict_stderr()
    out = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        rc = main(argv)
    err.flush()
    return rc, err.buffer.getvalue().decode()  # type: ignore[attr-defined]


def _cases(tmp_path: Path, snaps: Path) -> list[tuple[str, list[str], bool]]:
    r"""``(label, argv, host_independent)`` for the five measured failures.

    Read seams outnumber write seams here, which is the whole correction to
    #160's enumeration.

    ``host_independent`` is load-bearing. The **read** rows fail because the
    path does not exist, which is true on every filesystem. The **write** row
    is not: `report\udcff.json` is a perfectly legal name on ext4, which
    accepts any non-NUL byte, so the write *succeeds* and the CLI exits 0 with
    no message at all. On APFS the same call returns `EILSEQ` and exits 2.
    Asserting exit 2 for that row passed locally on macOS and failed CI on
    Linux — a filesystem assertion wearing a guard's clothes.

    So the row stays (it is the seam #160 was filed about) and its assertion is
    the *class*: whatever the filesystem decides, the CLI must not die inside
    its own `print`.
    """
    bad_file = str(tmp_path / f"report{SURROGATE}.json")
    bad_dir = str(tmp_path / f"dir{SURROGATE}")
    snap = str(snaps / "a.yml")
    return [
        (
            "validate --out (write seam)",
            ["validate", str(snaps), "--json", "--out", bad_file],
            False,
        ),
        ("validate <bad dir> (read seam)", ["validate", bad_dir], True),
        ("stats <bad dir> (read seam)", ["stats", bad_dir], True),
        (
            "diff --snapshot <bad> (read seam)",
            ["diff", "--snapshot", bad_file, "--candidate", snap],
            True,
        ),
        (
            "run --snapshots <bad dir> (read seam)",
            ["run", "--snapshots", bad_dir, "--candidates", bad_dir],
            True,
        ),
    ]


def test_no_case_dies_inside_its_own_message_under_a_strict_stderr(
    tmp_path: Path, snapshots_dir: Path
) -> None:
    """The property, stated so it holds on every filesystem.

    Before the fix these raised `UnicodeEncodeError` out of `print`. The
    assertion is "an exit code came back, and any message written is intact" —
    not "the write failed", which is the filesystem's call, not this repo's.
    """
    for label, argv, _host_independent in _cases(tmp_path, snapshots_dir):
        rc, written = _run_under_strict_stderr(argv)  # must not raise
        assert rc in (0, 2), f"{label}: unexpected exit {rc!r}"
        if rc == 2:
            assert "error:" in written, f"{label}: exited 2 with no error line — {written!r}"
            assert "\\udcff" in written, (
                f"{label}: the offending byte vanished from the message — {written!r}"
            )


def test_the_host_independent_cases_all_report_the_escaped_path(
    tmp_path: Path, snapshots_dir: Path
) -> None:
    """Anti-vacuous floor for the test above.

    On a filesystem that accepts the name, the write row exits 0 and asserts
    nothing. The read rows fail because the path is absent, which no filesystem
    disagrees about — so at least these must exercise the message path, or the
    whole file could pass without a single diagnostic being written.
    """
    checked = 0
    for label, argv, host_independent in _cases(tmp_path, snapshots_dir):
        if not host_independent:
            continue
        rc, written = _run_under_strict_stderr(argv)
        assert rc == 2, f"{label}: expected exit 2, got {rc!r}"
        assert "error:" in written, f"{label}: no error line — {written!r}"
        assert "\\udcff" in written, f"{label}: offending byte missing — {written!r}"
        checked += 1
    assert checked >= 3, f"only {checked} host-independent rows; the floor is not being met"


def test_the_case_table_covers_both_seam_kinds(tmp_path: Path, snapshots_dir: Path) -> None:
    """#160 counted write seams and missed read seams. If this table ever
    narrows back to one kind, the correction has been undone."""
    labels = [label for label, _, _ in _cases(tmp_path, snapshots_dir)]
    assert sum("write seam" in x for x in labels) >= 1, labels
    assert sum("read seam" in x for x in labels) >= 3, labels


def test_the_same_cases_behave_identically_on_an_ordinary_stderr(
    tmp_path: Path, snapshots_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Anti-vacuous partner: the fix must not have turned every path into a 2
    by breaking the commands, and a lenient stderr must not change the verdict.
    """
    for label, argv, host_independent in _cases(tmp_path, snapshots_dir):
        rc = main(argv)
        assert rc in (0, 2), label
        if host_independent:
            assert rc == 2, label
    capsys.readouterr()


def test_a_well_formed_run_is_untouched(
    snapshots_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The guard must not have hardened into failing ordinary input."""
    assert main(["validate", str(snapshots_dir)]) == 0
    assert "error:" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The lock: one funnel, discovered from source
# ---------------------------------------------------------------------------

_SOURCE_ROOTS = ("prompt_regression", "scripts")
_STDERR_WRITE = re.compile(r"file\s*=\s*sys\.stderr")


def _source_files() -> list[Path]:
    root = Path(__file__).resolve().parent.parent
    found: list[Path] = []
    for d in _SOURCE_ROOTS:
        found.extend(sorted((root / d).rglob("*.py")))
    return found


def test_the_source_scan_is_not_vacuous() -> None:
    """A walk that finds no files would make the lock below pass trivially."""
    files = _source_files()
    assert len(files) >= 8, [str(f) for f in files]
    names = {f.name for f in files}
    assert "cli.py" in names
    assert "io.py" in names
    assert "capture_demo.py" in names


def test_only_the_helper_writes_to_sys_stderr() -> None:
    """The population #160 should have been stated over.

    Stated as "which files may", not "which messages must be safe": a rule
    about messages is a hand-list again, and a sixth message added next month
    would rejoin the gap silently. This one cannot be satisfied by adding a
    message — only by routing it through the funnel.
    """
    offenders = [
        str(f.relative_to(Path(__file__).resolve().parent.parent))
        for f in _source_files()
        if _STDERR_WRITE.search(f.read_text(encoding="utf-8"))
    ]
    assert offenders == ["prompt_regression/io.py"], (
        "only `io._eprint` may write to sys.stderr directly; these files bypass "
        f"the funnel: {offenders}"
    )


def test_the_helper_is_actually_used() -> None:
    """Stated positively, because a negative rule is satisfied by a file that
    does nothing — which is how a partial adoption passes a lock."""
    users = [f for f in _source_files() if "_eprint(" in f.read_text(encoding="utf-8")]
    assert len(users) >= 3, [str(f) for f in users]
    assert cli_module._eprint is _eprint  # noqa: SLF001 - one definition, not a copy


# ---------------------------------------------------------------------------
# The boundary this fix does not cross
# ---------------------------------------------------------------------------


def test_argparse_is_a_known_gap(tmp_path: Path) -> None:
    """`argparse` interpolates the same operator path and writes it itself.

    Pinned as a *known gap* rather than left unstated: a fix that stops short
    of a boundary should say where the boundary is, or the next reader will
    read this file as proof the CLI is total. Closing it would mean
    reconfiguring `sys.stderr` process-wide, which is a caller's decision to
    make, not a library's.
    """
    err = _strict_stderr()
    with pytest.raises(UnicodeEncodeError), contextlib.redirect_stderr(err):
        main(["stats", str(tmp_path), "--out", str(tmp_path / f"x{SURROGATE}.json")])
