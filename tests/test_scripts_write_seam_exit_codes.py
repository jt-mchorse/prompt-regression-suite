"""Exit-code contract for the two `scripts/` entry points (#140).

`cli._write_output` exists because "every `--out` site called
`atomic_write_text` bare, so an unwritable `--out` escaped as a raw OSError
traceback at exit 1". That sweep (#99/#111) enumerated the library CLI's
`--out` sites and never enumerated `scripts/`, where both files had the same
seam.

The test that matters most is `test_capture_demo_propagates_the_render_scripts_
exit_code`. Before this change, `capture_demo._run_render_demo_into` raised an
uncaught `RuntimeError` on a non-zero `rc` — harmless only because
`render_regression_demo.main` never returned non-zero for a write failure; it
let the `OSError` escape instead. Giving the render script its exit-2 guard is
what *arms* that raise. So fixing the render script alone would have swapped an
`OSError` traceback for a `RuntimeError` traceback and discarded the code, and
a test suite that only checked the render script directly would have called
that a success.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from tests.test_capture_demo_smoke import _load_capture_module

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_render_module():
    """Load `scripts/render_regression_demo.py`, mirroring the capture
    script's own `_import_render_demo_main` bootstrap."""
    scripts_dir = _REPO_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if "render_regression_demo" in sys.modules:
        del sys.modules["render_regression_demo"]
    import render_regression_demo  # noqa: WPS433 — dynamic import is the point.

    return render_regression_demo


def _drive_render(argv: list[str]) -> tuple[int, str]:
    mod = _load_render_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(argv)
    return rc, buf.getvalue()


def _drive_capture(argv: list[str]) -> tuple[int, str]:
    mod = _load_capture_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(argv)
    return rc, buf.getvalue()


# ----------------------------------------------------------------------
# render_regression_demo.py — the two write seams
# ----------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX directory permissions; chmod is a no-op on Windows"
)
def test_render_unwritable_out_html_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "readonly"
    target.mkdir()
    target.chmod(0o500)
    try:
        rc, _ = _drive_render(["--out-html", str(target / "x.html"), "--no-screenshot"])
    finally:
        target.chmod(0o700)

    assert rc == 2, f"an unwritable --out-html must exit 2; got {rc}"
    err = capsys.readouterr().err
    assert "error: failed to write" in err, (
        f"expected the same message shape as cli._write_output; got:\n{err}"
    )


def test_render_out_html_that_is_a_directory_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`os.replace` onto a directory raises `IsADirectoryError` — a different
    exception from the permission case, reached through a different part of
    `atomic_write_text`."""
    target = tmp_path / "a_dir"
    target.mkdir()

    rc, _ = _drive_render(["--out-html", str(target), "--no-screenshot"])

    assert rc == 2, f"a directory --out-html must exit 2; got {rc}"
    assert str(target) in capsys.readouterr().err


def test_render_unwritable_out_png_parent_exits_2_after_the_html_landed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The screenshot seam is independent and fires *after* the HTML write
    succeeds. The HTML is real and already announced, so the test pins that
    both things are true: the report exists, and the run still reports 2.
    """
    out_html = tmp_path / "report.html"
    png_parent = tmp_path / "a_file"
    png_parent.write_text("", encoding="utf-8")

    rc, out = _drive_render(
        ["--out-html", str(out_html), "--out-png", str(png_parent / "shot.png")]
    )

    assert rc == 2, f"an unwritable --out-png parent must exit 2; got {rc}"
    assert out_html.exists(), "the HTML written before the screenshot seam must survive"
    assert "html wrote" in out, f"the successful HTML write must still be announced; got:\n{out}"
    assert "error: failed to create screenshot dir" in capsys.readouterr().err


def test_render_valid_invocation_still_exits_0(tmp_path: Path) -> None:
    rc, out = _drive_render(["--out-html", str(tmp_path / "ok.html"), "--no-screenshot"])
    assert rc == 0, f"a valid run must exit 0; stdout:\n{out}"
    assert (tmp_path / "ok.html").exists()


# ----------------------------------------------------------------------
# capture_demo.py — the ordering trap, plus its own seams
# ----------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX directory permissions; chmod is a no-op on Windows"
)
def test_capture_demo_propagates_the_render_scripts_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The test this whole issue turns on.

    `_run_render_demo_into` used to raise `RuntimeError` on a non-zero `rc`,
    uncaught. That was inert only while the render script never returned
    non-zero for a write failure. Fixing the render script arms it — so
    without this assertion, a change that fixed only the render script would
    look correct while this path still exited 1 with a traceback and threw the
    code away.
    """
    target = tmp_path / "readonly"
    target.mkdir()
    target.chmod(0o500)
    try:
        rc, _ = _drive_capture(["--pause-seconds=0", "--no-open", "--output-dir", str(target)])
    finally:
        target.chmod(0o700)

    assert rc == 2, (
        "the render script's exit code must be propagated verbatim — a write "
        f"failure is a 2, not the findings code 1; got {rc}"
    )
    err = capsys.readouterr().err
    assert "Traceback" not in err, f"must not surface as a traceback; got:\n{err}"
    # The render script already reported the cause; that line must survive.
    assert "error: failed to write" in err, (
        f"the render script's own diagnostic must not be buried; got:\n{err}"
    )
    assert "render_regression_demo.py exited 2" in err, (
        f"expected a clean [capture] abort line naming the code; got:\n{err}"
    )


def test_run_render_demo_into_returns_rc_rather_than_raising(tmp_path: Path) -> None:
    """Pin the helper's contract directly, so the raise can't be reintroduced
    and papered over with a broad `except Exception` in `main` — which would
    lose the code again."""
    mod = _load_capture_module()
    target = tmp_path / "a_dir"
    target.mkdir()

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc, _stdout = mod._run_render_demo_into(target)

    assert rc == 2, f"_run_render_demo_into must return the render script's rc; got {rc!r}"


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "-1", "-0.5"])
def test_capture_demo_rejects_bad_pause_seconds_before_stage_1(
    bad: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`inf` crashed from `_pause`, after STAGE 1 had regenerated the report;
    `nan` and negatives exited 0 having paused nowhere."""
    # `--pause-seconds -1` is eaten by argparse as an unknown flag; the `=`
    # form is the only one that reaches the validator.
    rc, out = _drive_capture([f"--pause-seconds={bad}", "--no-open", "--output-dir", str(tmp_path)])

    assert rc == 2, f"--pause-seconds {bad} should be a usage error (exit 2); got {rc}"
    assert "STAGE 1" not in out, (
        f"--pause-seconds {bad} must be rejected before STAGE 1 runs; stdout:\n{out}"
    )
    assert not list(tmp_path.iterdir()), "a rejected --pause-seconds must leave no artifacts"
    err = capsys.readouterr().err
    assert "--pause-seconds" in err, f"the error must name the offending flag; got:\n{err}"


def test_capture_demo_nan_pause_takes_no_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anchor on the corruption: `nan > 0` is False, so `_pause` silently did
    nothing — a clean exit-0 run whose recording has no cue points."""
    mod = _load_capture_module()
    calls: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: calls.append(s))

    mod._pause(float("nan"))
    assert calls == [], "nan silently skips the pause — hence the parse-time guard"

    mod._pause(0.25)
    assert calls == [0.25], "a valid pause must still reach time.sleep"


def test_capture_demo_validate_pause_seconds_rejects_bool() -> None:
    mod = _load_capture_module()
    assert mod._validate_pause_seconds(True) is not None
    assert mod._validate_pause_seconds(False) is not None
    assert mod._validate_pause_seconds(0) is None
    assert mod._validate_pause_seconds(2.0) is None


def test_capture_demo_output_dir_that_is_a_file_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "not_a_dir"
    target.write_text("", encoding="utf-8")

    rc, out = _drive_capture(["--pause-seconds=0", "--no-open", "--output-dir", str(target)])

    assert rc == 2, f"an --output-dir that is a file should exit 2; got {rc}"
    assert "STAGE 1" not in out, "the mkdir guard must fire before STAGE 1 runs"
    assert str(target) in capsys.readouterr().err
