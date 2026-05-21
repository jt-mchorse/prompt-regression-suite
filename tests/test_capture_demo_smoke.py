"""Smoke test for `scripts/capture_demo.sh` (issue #15).

The capture script is the deterministic driver for the 60-second README demo.
JT records the GIF/video while it runs; CI runs it with `CAPTURE_PACE_SECONDS=0`
and `CAPTURE_OPEN_HTML=0` so the bench part is exercised without launching
the OS default browser.

Contract this test pins:

1. The script exits 0 on a fresh clone with no API key.
2. Each of the three surfaces runs and emits its distinctive output.
3. The third surface's two `prompt-snap diff` calls both render — once
   green at `--threshold 0.9` and once red at `--threshold 0.99
   --warn-band 0.0` on the SAME candidate — the literal "tighter
   tolerance makes benign drift fail" demo the issue scope calls for.
4. The committed `docs/regression_demo.html` is byte-equal before and
   after the script runs (deterministic regen — same property
   `test_regression_demo_snapshot.py` already pins via the script
   directly).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "capture_demo.sh"
COMMITTED_HTML = REPO_ROOT / "docs" / "regression_demo.html"


@pytest.fixture(scope="module")
def capture_run() -> dict[str, object]:
    """Run the capture script once and reuse its stdout across assertions."""
    if not SCRIPT.exists():
        pytest.fail(f"missing {SCRIPT}")
    if shutil.which("bash") is None:
        pytest.skip("bash not available")

    env = dict(os.environ)
    env["CAPTURE_PACE_SECONDS"] = "0"
    env["CAPTURE_OPEN_HTML"] = "0"
    # Ensure `prompt-snap` and the editable `prompt_regression` package
    # resolve via the active venv's bin so capture_demo.sh's shells out
    # use the same interpreter pytest is using.
    venv_bin = Path(sys.executable).parent
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"

    committed_before = COMMITTED_HTML.read_bytes() if COMMITTED_HTML.exists() else None

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"capture_demo.sh exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )

    return {
        "stdout": result.stdout,
        "committed_before": committed_before,
    }


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} should be executable"


def test_surface_1_render_regression_demo(capture_run: dict[str, object]) -> None:
    stdout = capture_run["stdout"]
    assert isinstance(stdout, str)
    assert "1/3 · scripts/render_regression_demo.py" in stdout
    assert "docs/regression_demo.html" in stdout
    # The render script's "html wrote" line carries the verdict + cosine.
    assert "html wrote docs/regression_demo.html" in stdout
    assert "verdict:" in stdout
    assert "cosine:" in stdout


def test_surface_2_describes_browser_step(capture_run: dict[str, object]) -> None:
    stdout = capture_run["stdout"]
    assert isinstance(stdout, str)
    assert "2/3 · open docs/regression_demo.html" in stdout
    # With CAPTURE_OPEN_HTML=0 the script prints the skip notice + path.
    assert "browser launch skipped" in stdout
    assert "regression_demo.html" in stdout


def test_surface_3_tighter_tolerance_flips_pass_to_fail(
    capture_run: dict[str, object],
) -> None:
    """The two `prompt-snap diff` calls demonstrate the threshold flip."""
    stdout = capture_run["stdout"]
    assert isinstance(stdout, str)
    assert "3/3 · prompt-snap diff" in stdout
    # `prompt-snap update` re-baselined the tempdir snapshot first.
    assert "updated " in stdout
    assert "hash-embedder-128d-ngram2" in stdout
    # Diff #1 is the pass.
    assert "diff #1" in stdout
    assert "threshold 0.9" in stdout
    # Diff #2 is the fail with a tighter threshold + zero warn band.
    assert "diff #2" in stdout
    assert "threshold 0.99" in stdout
    # Scope the pass/fail ordering check to the third-surface section only;
    # surface 1 (render_regression_demo.py) also prints "verdict: fail" up
    # at the top, which would beat any surface-3 verdict on raw find().
    surface3_start = stdout.index("3/3 · prompt-snap diff")
    surface3 = stdout[surface3_start:]
    pass_idx = surface3.find("verdict: pass")
    fail_idx = surface3.find("verdict: fail")
    assert pass_idx != -1, f"expected verdict: pass on diff #1 in surface 3; got:\n{surface3}"
    assert fail_idx != -1, (
        f"expected verdict: fail on diff #2 (tighter threshold) in surface 3; got:\n{surface3}"
    )
    assert pass_idx < fail_idx, (
        "expected diff #1 (pass at threshold 0.9) to render before diff #2 "
        "(fail at threshold 0.99) within surface 3"
    )


def test_render_step_is_deterministic_does_not_dirty_committed_html(
    capture_run: dict[str, object],
) -> None:
    """The capture re-runs `render_regression_demo.py` which writes to
    docs/regression_demo.html. That write must be byte-equal — same
    property `test_regression_demo_snapshot.py` already pins, asserted
    here at the capture-script level."""
    committed_before = capture_run["committed_before"]
    if committed_before is None:
        pytest.skip("no committed docs/regression_demo.html to snapshot against")
    committed_after = COMMITTED_HTML.read_bytes()
    assert committed_after == committed_before, (
        "scripts/capture_demo.sh rewrote docs/regression_demo.html in a way "
        "that diverged from the committed copy. The script is supposed to be "
        "a deterministic regen — if this asserts, render_regression_demo.py "
        "is no longer producing byte-equal output and the snapshot test "
        "(`test_regression_demo_snapshot.py`) will be failing too."
    )
