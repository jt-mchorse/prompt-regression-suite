#!/usr/bin/env python3
"""Deterministic capture orchestrator for the prompt-regression-suite 60-second demo.

Sequences the three demo flows from issue #15's spec under explicit
stage banners + configurable inter-stage pause, so a screen recorder
can re-capture and land on the same frames each time.

Stages:

- **STAGE 1 (auto, hermetic).** Calls `render_regression_demo.main()`
  in-process against a temp `--out-html`, so the recording shows the
  synthetic regression report being regenerated without clobbering the
  committed `docs/regression_demo.html`.
- **STAGE 2 (browser).** Opens the freshly-rendered HTML in the
  operator's default browser so the side-by-side diff + slot table
  appear in the recording.
- **STAGE 3 (auto, hermetic).** Subprocess `prompt-snap diff
  --snapshot examples/snapshots/creative_kite_v1.yml --candidate <text>
  --threshold 0.9` — tight threshold makes a benign drift fail and
  demonstrates the CLI surface from #5 with the per-snapshot tolerance
  pattern from #6. The kite snapshot is used (not the refund-window
  one) because it ships embedded with `hash-embedder-128d-ngram2`,
  matching the CLI's default `--embedder hash` and keeping STAGE 3
  hermetic — no `--force-embedder` override needed.

Usage:

    python scripts/capture_demo.py [--pause-seconds 2.0] [--no-open]
                                   [--output-dir docs/demo-artifacts]

Closes the AC3 row on #15. AC1 (committed GIF/MP4) and AC2 (README
embed) remain operator-only. Locked by `tests/test_capture_demo_smoke.py`,
same hermetic contract as `tests/test_render_regression_demo.py`.
"""

from __future__ import annotations

import argparse
import importlib
import io
import subprocess
import sys
import time
import webbrowser
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "demo-artifacts"

STABLE_REGRESSION_HTML = "regression_demo.html"

# Snapshot used for the STAGE 3 CLI diff. The kite poem snapshot is
# the one embedded with `hash-embedder-128d-ngram2` (the same embedder
# the CLI's `--embedder hash` default reaches for) — picking that one
# keeps STAGE 3 fully hermetic, no `--force-embedder` override needed.
# The candidate diverges enough that a 0.9 threshold flips the verdict
# from `pass` (under the default warn/threshold) to `fail`, which is
# the visible demo point.
STAGE3_SNAPSHOT_REL = "examples/snapshots/creative_kite_v1.yml"
STAGE3_CANDIDATE_TEXT = (
    "The flying toy moves through the sky over the sand. Children watch from below."
)
STAGE3_THRESHOLD = "0.9"


def _banner(stage: int, title: str) -> str:
    line = "=" * 72
    return f"\n{line}\n  STAGE {stage}  {title}\n{line}\n"


def _pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _import_render_demo_main():
    """Fresh-import `render_regression_demo` and return its `main` callable.

    Mirrors the path-bootstrapping pattern in
    `tests/test_render_regression_demo.py` (which adds `scripts/` to
    `sys.path` then imports `render_regression_demo` directly).
    """
    scripts_dir = REPO_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if "render_regression_demo" in sys.modules:
        del sys.modules["render_regression_demo"]
    mod = importlib.import_module("render_regression_demo")
    if not hasattr(mod, "main"):
        raise RuntimeError("scripts/render_regression_demo.py must expose a `main()` callable")
    return mod.main


def _run_render_demo_into(out_html: Path) -> str:
    render_main = _import_render_demo_main()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = render_main(["--out-html", str(out_html), "--no-screenshot"])
    if rc != 0:
        raise RuntimeError(f"render_regression_demo.main exited {rc}; output:\n{buf.getvalue()}")
    return buf.getvalue()


def _run_prompt_snap_diff_fail() -> tuple[int, str, str]:
    """Run `prompt-snap diff` via subprocess with a tight threshold so a
    benign drift fails — that's the demo point for stage 3.

    Returns ``(returncode, stdout, stderr)``. A non-zero return code is
    the success path here: the CLI exits non-zero on a failing diff,
    which is the visible demonstration the recording captures.

    Uses `python -m prompt_regression.cli` rather than the
    ``prompt-snap`` console script so this works on a fresh clone
    before the editable install has put the entry point on PATH —
    same posture as the CLI surface tests.
    """
    cmd = [
        sys.executable,
        "-m",
        "prompt_regression.cli",
        "diff",
        "--snapshot",
        str(REPO_ROOT / STAGE3_SNAPSHOT_REL),
        "--candidate",
        STAGE3_CANDIDATE_TEXT,
        "--threshold",
        STAGE3_THRESHOLD,
        "--format",
        "text",
    ]
    result = subprocess.run(  # noqa: S603 — invoked with sys.executable, no shell.
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic 60-second demo capture orchestrator for prompt-regression-suite."
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=2.0,
        help=(
            "Pause between stages so the screen recorder has cue points. "
            "Default 2.0; set to 0 for CI and tests."
        ),
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help=(
            "Skip launching the system browser on the rendered HTML. "
            "Required for CI/tests; default is to open the report so "
            "the recording captures the rendered side-by-side diff."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Where the freshly-rendered HTML lands. Default: "
            "docs/demo-artifacts (gitignored). Avoids clobbering the "
            "committed docs/regression_demo.html."
        ),
    )
    args = parser.parse_args(argv)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # STAGE 1 — regenerate the regression report under a temp out path.
    print(_banner(1, "Regenerate regression report (scripts/render_regression_demo.py)"))
    out_html = output_dir / STABLE_REGRESSION_HTML
    render_stdout = _run_render_demo_into(out_html)
    print(render_stdout, end="")
    print(f"[capture] HTML written to: {out_html}")
    _pause(args.pause_seconds)

    # STAGE 2 — browser open on the freshly-rendered HTML.
    print(_banner(2, "Inspect the report in a browser"))
    print(f"[capture] opening: {out_html}")
    if not args.no_open:
        webbrowser.open(out_html.as_uri())
    _pause(args.pause_seconds)

    # STAGE 3 — prompt-snap diff with a tight threshold making it fail.
    print(_banner(3, "prompt-snap diff with --threshold 0.9 (benign drift → fail)"))
    rc, out, err = _run_prompt_snap_diff_fail()
    if out:
        print(out, end="")
    if err:
        print(err, end="", file=sys.stderr)
    # The diff returning non-zero IS the demo point. Don't propagate
    # as a script failure unless something exploded outright (rc < 0
    # or a Python-level traceback in stderr).
    if rc < 0:
        print(
            f"[capture] prompt-snap diff exited unexpectedly ({rc}); aborting.",
            file=sys.stderr,
        )
        return 1
    print(f"[capture] prompt-snap exit code: {rc}  (non-zero = failing diff; that's the demo)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
