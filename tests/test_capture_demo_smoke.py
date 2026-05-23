"""Smoke test for ``scripts/capture_demo.py``.

Same hermetic contract as ``tests/test_render_regression_demo.py`` —
runs end-to-end with the hash embedder, no API key, no live network.
Asserts the three stages run in order, the freshly-rendered HTML
lands under ``--output-dir``, and the STAGE 3 CLI diff returns
non-zero (the visible "failing diff" the recording captures).
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path


def _load_capture_module():
    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if "capture_demo" in sys.modules:
        del sys.modules["capture_demo"]
    import capture_demo  # noqa: WPS433 — dynamic import is the point here.

    return capture_demo


def test_capture_demo_runs_all_three_stages(tmp_path: Path) -> None:
    capture_demo = _load_capture_module()

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = capture_demo.main(
            [
                "--pause-seconds",
                "0",
                "--no-open",
                "--output-dir",
                str(tmp_path),
            ]
        )
    out = buf.getvalue()

    assert rc == 0, f"capture_demo exited {rc}; stdout:\n{out}"

    # All three stage banners appear in order.
    s1 = out.index("STAGE 1")
    s2 = out.index("STAGE 2")
    s3 = out.index("STAGE 3")
    assert s1 < s2 < s3, f"stage banners out of order; got positions {s1}, {s2}, {s3}"

    # STAGE 1 — HTML written to tmp output dir.
    out_html = tmp_path / "regression_demo.html"
    assert out_html.exists(), f"expected {out_html} to be written by STAGE 1"
    content = out_html.read_text(encoding="utf-8")
    assert "</html>" in content, "rendered file is not valid HTML"
    assert str(out_html) in out, "HTML output path should appear in stdout"

    # STAGE 3 — prompt-snap exit-code line printed; non-zero is the demo.
    assert "prompt-snap exit code:" in out, (
        "expected the STAGE 3 exit-code summary line; got:\n" + out[-400:]
    )
    # The diff `--format text` output always includes a `verdict:` line
    # and a `cosine:` line — assert both so a future format change is
    # caught here, not silently as a recording-frame regression.
    assert "verdict: fail" in out, (
        "expected the diff to fail at --threshold 0.9; got:\n" + out[-600:]
    )
    assert "cosine:" in out, "expected `cosine:` in STAGE 3 CLI output"


def test_capture_demo_does_not_clobber_committed_html(tmp_path: Path) -> None:
    """The committed `docs/regression_demo.html` is the README-cited demo
    asset. The capture script must never overwrite it — `--output-dir`
    forces writes elsewhere."""
    capture_demo = _load_capture_module()

    repo_root = Path(capture_demo.REPO_ROOT)
    committed_html = repo_root / "docs" / "regression_demo.html"
    before = committed_html.read_bytes() if committed_html.exists() else None

    buf = io.StringIO()
    with redirect_stdout(buf):
        capture_demo.main(
            [
                "--pause-seconds",
                "0",
                "--no-open",
                "--output-dir",
                str(tmp_path),
            ]
        )

    after = committed_html.read_bytes() if committed_html.exists() else None
    assert before == after, (
        "scripts/capture_demo.py must not modify the committed "
        "docs/regression_demo.html; pass --output-dir to redirect."
    )


def test_capture_demo_exposes_main_callable() -> None:
    capture_demo = _load_capture_module()
    assert hasattr(capture_demo, "main")
    import inspect

    sig = inspect.signature(capture_demo.main)
    assert "argv" in sig.parameters, f"main() must accept argv; got: {sig}"
