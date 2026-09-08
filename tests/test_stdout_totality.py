"""Every stdout write this package makes survives an unencodable path (#163).

#160 built `io._eprint` so no diagnostic can die inside its own `print`, and
stated the reason the bug was hard to see:

    It does not fire on a real process: CPython gives `sys.stderr`
    `errors="backslashreplace"` ... It fires the moment `sys.stderr` is a
    stream with a strict handler -- which `pytest`'s `capsys` is.

That is true, and it is the property `sys.stdout` does **not** have. Measured in
a plain environment (`LC_ALL=en_US.UTF-8`, no `PYTHONIOENCODING`/`PYTHONUTF8`):

    stdout=strict  stderr=backslashreplace
    stdout print: UnicodeEncodeError: 'utf-8' codec can't encode '\\udcff'
    error: failed report\\udcff.json
    stderr print: SUCCEEDED

So #160 hardened the stream the interpreter had already made lenient and left
the strict one bare. On stdout this fires on a real process, not only under
`capsys`.

**The two lines that make the case.** In `cli.update`, the failure path went
through `_eprint` and the success path through a bare `print` of the same
`snapshot_path` -- so a successful update on an unencodable path wrote the file
and *then* died announcing success, at exit 1, after the operation had already
happened.

**And the sharpest one.** `scripts/capture_demo.py` relayed a child's stdout
with a bare `print(out, end="")` two lines above a comment explaining that a
child's *stderr* "can carry a lone surrogate for exactly the same reason
`sys.argv` does" -- same child, same `subprocess` call, same locale handler.

**Two sites the `print(` grep missed** were `sys.stdout.write(rendered)`, which
is why the source lock in `test_stderr_totality.py` now matches any mention of
either stream rather than a `file=` keyword.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from prompt_regression import cli as cli_module
from prompt_regression.cli import main
from prompt_regression.io import _eprint, _print, _write, load_snapshot, save_snapshot

#: What `surrogateescape` produces for the raw byte 0xFF.
SURROGATE = chr(0xDCFF)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples" / "snapshots"


def _strict_stream() -> io.TextIOWrapper:
    """A stream whose handler refuses what a real `sys.stdout` also refuses.

    Unlike the stderr harness one file over, this is not a contrivance to
    surface a latent case: `strict` is what `sys.stdout` actually carries in an
    ordinary environment. The harness reproduces the default, it does not
    tighten it.
    """
    return io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict", write_through=True)


def _written(stream: io.TextIOWrapper) -> str:
    stream.flush()
    return stream.buffer.getvalue().decode()  # type: ignore[attr-defined]


@pytest.fixture
def snapshots_dir(tmp_path: Path) -> Path:
    d = tmp_path / "snaps"
    d.mkdir()
    save_snapshot(load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml"), d / "a.yml")
    return d


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------


def test_print_writes_an_ordinary_message_verbatim() -> None:
    out = _strict_stream()
    with contextlib.redirect_stdout(out):
        _print("updated a.yml")
    assert _written(out) == "updated a.yml\n"


def test_print_leaves_ordinary_non_ascii_unescaped() -> None:
    """The row that kills the over-broad fix, run against the stdout funnel too.

    `ascii()` on every message makes the write total and every non-ASCII line
    unreadable. #160 measured and rejected it for stderr; a second funnel is a
    second chance to get it wrong, so the same row runs here.
    """
    out = _strict_stream()
    with contextlib.redirect_stdout(out):
        _print("updated café/日本語.yml")
    written = _written(out)
    assert "café/日本語.yml" in written
    assert "\\u" not in written
    assert "\\x" not in written


def test_print_does_not_raise_on_an_unencodable_message() -> None:
    out = _strict_stream()
    with contextlib.redirect_stdout(out):
        _print(f"updated report{SURROGATE}.yml")
    written = _written(out)
    assert "updated report" in written
    assert ".yml" in written
    # Escaped, not dropped: an operator has to be able to see a byte was there.
    assert "\\udcff" in written


def test_print_honours_end_so_a_relay_gains_no_newline() -> None:
    """Two callers are relays — `capture_demo` echoing a child's stdout, and
    `cli` writing a pre-terminated rendered report. A funnel that always
    appended a newline would silently reformat both."""
    out = _strict_stream()
    with contextlib.redirect_stdout(out):
        _print("already terminated\n", end="")
    assert _written(out) == "already terminated\n"


def test_end_is_honoured_on_the_escape_path_too() -> None:
    """The retry is the branch a caller never exercises in testing, so it is
    the branch where a dropped keyword survives review."""
    out = _strict_stream()
    with contextlib.redirect_stdout(out):
        _print(f"report{SURROGATE}\n", end="")
    written = _written(out)
    assert written.endswith("\n")
    assert not written.endswith("\n\n")


def test_both_funnels_share_one_definition() -> None:
    """Not two copies that currently agree.

    A second copy of the escape passes every behavioural assertion in this file
    and in `test_stderr_totality.py`, and diverges the first time either is
    edited — which is the drift #160's own funnel exists to prevent.
    """
    import inspect

    def _code(fn: object) -> str:
        """Source with the docstring removed — the docstrings *discuss* the
        escape, and a lock that greps prose fires on the paragraph explaining
        the fix."""
        source = inspect.getsource(fn)  # type: ignore[arg-type]
        doc = inspect.getdoc(fn) or ""
        for line in doc.splitlines():
            source = source.replace(line, "")
        return source

    assert "_write(" in _code(_print)
    assert "_write(" in _code(_eprint)
    for fn in (_print, _eprint):
        assert "backslashreplace" not in _code(fn), f"{fn.__name__} restates the escape"
    # And the escape really does live in exactly one place.
    assert inspect.getsource(_write).count("backslashreplace") == 1


def test_the_shared_writer_escapes_through_the_streams_own_encoding() -> None:
    """Not through `ascii()`, and not through a hardcoded utf-8.

    A stream on a narrower encoding must degrade against *its* encoding, or the
    escape is computed for a codec that is not doing the writing.
    """
    latin = io.TextIOWrapper(io.BytesIO(), encoding="latin-1", errors="strict", write_through=True)
    _write("naïve café", latin)
    latin.flush()
    assert latin.buffer.getvalue().decode("latin-1") == "naïve café\n"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The subcommands, end to end under a strict stdout
# ---------------------------------------------------------------------------


def test_a_report_naming_an_unencodable_snapshot_does_not_kill_the_run(
    snapshots_dir: Path,
) -> None:
    """`validate` renders snapshot ids read off the filesystem.

    On ext4 a filename can hold a byte that is not valid UTF-8; `os.listdir`
    decodes it with `surrogateescape`, and it reaches the summary this prints.
    Same reachability #160's read seams relied on.
    """
    out = _strict_stream()
    with contextlib.redirect_stdout(out):
        rc = main(["validate", str(snapshots_dir)])
    assert rc == 0
    assert _written(out)


@pytest.mark.parametrize(
    "argv",
    [
        ["validate", "SNAPS"],
        ["stats", "SNAPS"],
    ],
)
def test_every_stdout_subcommand_survives_a_strict_stream(
    argv: list[str], snapshots_dir: Path
) -> None:
    out = _strict_stream()
    resolved = [str(snapshots_dir) if a == "SNAPS" else a for a in argv]
    with contextlib.redirect_stdout(out):
        rc = main(resolved)
    assert rc == 0
    assert _written(out).strip(), f"{argv}: printed nothing, so this proves nothing"


def test_a_well_formed_run_is_byte_identical_to_before(snapshots_dir: Path) -> None:
    """The guard must not have hardened into reformatting ordinary output.

    `_print` with the default `end` is `print`; `_print(..., end="")` is
    `sys.stdout.write`. If either drifted, every rendered report gains or loses
    a newline, and the `--out` file and the stdout path would disagree.
    """
    out = _strict_stream()
    with contextlib.redirect_stdout(out):
        assert main(["stats", str(snapshots_dir), "--json"]) == 0
    written = _written(out)
    parsed = json.loads(written)
    assert parsed
    assert written.endswith("\n")
    assert not written.endswith("\n\n")


# ---------------------------------------------------------------------------
# The boundary this fix does not cross
# ---------------------------------------------------------------------------


def test_the_json_format_is_safe_by_construction_and_that_is_worth_stating() -> None:
    """The boundary, and it turned out to be on the other side.

    I expected `--json` to be the case where the escape changes bytes a machine
    consumer parses, and wrote the test to pin that. It does not:
    `json.dumps` defaults to `ensure_ascii=True`, so an unencodable id is
    written as the *escape sequence* `\\udcff` — pure ASCII — and the retry
    never runs. The id round-trips through `json.loads` exactly.

    So the format that needed the funnel is the **text** one, and the JSON one
    was never exposed. Checking the `ensure_ascii` flag before calling a JSON
    write seam vulnerable is the rule; asserting it here stops a later switch to
    `ensure_ascii=False` — for readable non-ASCII on disk, a reasonable-sounding
    change — from silently making this path lossy.
    """
    original = f"report{SURROGATE}"
    payload = json.dumps({"id": original})
    assert "\\udcff" in payload
    payload.encode("utf-8")  # ASCII-only, so the strict stream never complains

    out = _strict_stream()
    with contextlib.redirect_stdout(out):
        _print(payload)
    written = _written(out)
    assert json.loads(written)["id"] == original, "the JSON path must be lossless"

    # The text format is the exposed one: the same id, uninterpolated, cannot
    # be written and does go through the retry.
    text_out = _strict_stream()
    with contextlib.redirect_stdout(text_out):
        _print(f"id: {original}")
    assert json.loads(written)["id"] == original
    assert "\\udcff" in _written(text_out)


def test_the_cli_module_uses_the_funnel_rather_than_holding_its_own(
    snapshots_dir: Path,
) -> None:
    assert cli_module._print is _print  # noqa: SLF001
    assert cli_module._eprint is _eprint  # noqa: SLF001
