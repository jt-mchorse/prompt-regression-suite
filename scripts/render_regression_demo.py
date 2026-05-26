"""Build a regression demo: baseline vs upgraded response, render HTML report.

The "regression" is synthetic — clearly labeled as a documentation
demo, not a captured real-model regression. The shape it exercises
is the one a real captured regression would also produce: identical
prompt, baseline response with structured slots intact, upgraded
response that loses a slot and shifts the semantics slightly.

The path to a real regression is:
  1. Replace `_BASELINE_TEXT` with the response from your previous model version.
  2. Replace `_UPGRADED_TEXT` with the response from your new model version.
  3. Re-run this script.
The HTML output is identical in structure either way.

Outputs:
- `docs/regression_demo.html` — the full report.
- `docs/regression_demo.png` — screenshot of the rendered HTML, if
  Playwright or `wkhtmltoimage` is available. Either tool is opt-in:
  the script falls back to writing just the HTML when neither is
  installed and prints a one-line "screenshot tool not available" note.

Run:
    python scripts/render_regression_demo.py
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from prompt_regression.diff import HashEmbedder, diff_response  # noqa: E402
from prompt_regression.html_report import ReportEntry, render_report  # noqa: E402
from prompt_regression.io import atomic_write_text  # noqa: E402
from prompt_regression.schema import (  # noqa: E402
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
)

_PROMPT_USER = "What's the refund window for the Pro plan?"
_PROMPT_SYSTEM = (
    "You are a polite support agent for ExampleCo. Answer concisely. If the "
    "question is about refunds, state the eligibility window in days and "
    "name the plan. If the policy is unknown, say so explicitly."
)
_BASELINE_TEXT = (
    "The Pro plan has a 14-day refund window from the original purchase date. "
    "Refunds during that window are full unless usage exceeds 25% of the "
    "included monthly quota, in which case the unused remainder is refunded."
)
# Upgraded model: same overall topic, but drops the eligibility caveat
# slot and uses "two weeks" instead of "14 days" — the diff layer should
# catch both regressions (slot extraction misses the integer; the
# semantic similarity stays high enough that a cosine-only check would
# falsely pass).
_UPGRADED_TEXT = (
    "Pro plan customers can request a refund within two weeks of their "
    "purchase. Reach out to support@exampleco.com to start the process."
)


def _build_snapshot(embedder: HashEmbedder) -> Snapshot:
    return Snapshot(
        id="refund-window-pro-v1-demo",
        prompt=Prompt(
            model="claude-haiku-4-5-20251001",
            user=_PROMPT_USER,
            system=_PROMPT_SYSTEM,
            temperature=0.0,
            max_tokens=256,
            extra={},
        ),
        response_shape=ResponseShape(
            semantic_categories=[
                "refund-window",
                "plan-tier",
                "eligibility-conditions",
            ],
            structured_slots={
                "refund_days": {
                    "type": "integer",
                    "description": "Number of days from purchase during which a refund can be requested.",
                },
                "plan_name": {
                    "type": "string",
                    "description": "Human-readable plan name the answer applies to.",
                },
                "eligibility_caveat": {
                    "type": "string",
                    "description": "Free-text caveat, if any (e.g., 'minus usage fees').",
                },
            },
        ),
        canonical=CanonicalResponse(
            text=_BASELINE_TEXT,
            embedding=embedder.embed(_BASELINE_TEXT),
            embedding_model=embedder.model_name,
        ),
        notes=(
            "Synthetic snapshot built in-process by scripts/render_regression_demo.py. "
            "Labeled here so the README's demo screenshot is unambiguous about its provenance."
        ),
    )


def _maybe_screenshot(html_path: Path, png_path: Path) -> str:
    """Try Playwright, then wkhtmltoimage. Returns a one-line status."""
    # Playwright path.
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError:
        playwright_ok = False
    else:
        playwright_ok = True
    if playwright_ok:
        try:
            with sync_playwright() as p:  # type: ignore[no-untyped-call]
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1100, "height": 1400})
                page.goto(f"file://{html_path.absolute()}")
                page.screenshot(path=str(png_path), full_page=True)
                browser.close()
            return f"screenshot: playwright → {png_path}"
        except Exception as e:  # pragma: no cover - depends on local install
            return f"screenshot: playwright failed ({e}); HTML at {html_path}"

    # wkhtmltoimage path.
    if shutil.which("wkhtmltoimage"):
        try:
            subprocess.run(
                ["wkhtmltoimage", "--quiet", str(html_path), str(png_path)],
                check=True,
                capture_output=True,
            )
            return f"screenshot: wkhtmltoimage → {png_path}"
        except subprocess.CalledProcessError as e:  # pragma: no cover
            return f"screenshot: wkhtmltoimage failed ({e}); HTML at {html_path}"

    return f"screenshot tool not available (Playwright or wkhtmltoimage); HTML at {html_path}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out-html",
        default="docs/regression_demo.html",
        help="Where to write the rendered HTML.",
    )
    p.add_argument(
        "--out-png",
        default="docs/regression_demo.png",
        help="Where to write the screenshot (if a tool is available).",
    )
    p.add_argument(
        "--no-screenshot",
        action="store_true",
        help="Skip the screenshot step.",
    )
    args = p.parse_args(argv)

    embedder = HashEmbedder()
    snapshot = _build_snapshot(embedder)
    diff = diff_response(snapshot, _UPGRADED_TEXT, embedder=embedder)

    entry = ReportEntry(
        snapshot_id=snapshot.id,
        diff=diff,
        candidate_text=_UPGRADED_TEXT,
        baseline_text=snapshot.canonical.text,
    )
    html = render_report(
        [entry], title="Regression demo — refund-window prompt across model versions"
    )
    out_html = Path(args.out_html)
    atomic_write_text(out_html, html)
    print(f"html wrote {out_html} (verdict: {diff.verdict}, cosine: {diff.cosine_score:.3f})")

    if not args.no_screenshot:
        out_png = Path(args.out_png)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        print(_maybe_screenshot(out_html, out_png))

    return 0


if __name__ == "__main__":
    sys.exit(main())
