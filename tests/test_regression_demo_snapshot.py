"""Snapshot test for `docs/regression_demo.html`.

The existing `test_render_regression_demo.py` covers the diff math and the
structural shape of the rendered HTML, but doesn't lock the committed
`docs/regression_demo.html` to what the script actually produces today.

This module is the missing piece: run the script against a tempfile and
assert the result equals the committed file byte-for-byte. The script is
deterministic (`HashEmbedder` is dep-free + reproducible, no timestamps in
the renderer), so the snapshot is stable.

When the snapshot fails, the one-line regen path is:

    python scripts/render_regression_demo.py --no-screenshot

…then `git diff docs/regression_demo.html` before committing.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from render_regression_demo import main as render_main  # noqa: E402

COMMITTED_HTML = _REPO_ROOT / "docs" / "regression_demo.html"

REGEN_HINT = (
    "Regenerate the committed demo:\n"
    "  python scripts/render_regression_demo.py --no-screenshot\n"
    "Then inspect with `git diff docs/regression_demo.html` before committing."
)


def test_committed_regression_demo_html_matches_script_output(tmp_path: Path) -> None:
    """`scripts/render_regression_demo.py` output must equal `docs/regression_demo.html`."""
    out_html = tmp_path / "regression_demo.html"
    rc = render_main(
        [
            "--out-html",
            str(out_html),
            "--out-png",
            str(tmp_path / "regression_demo.png"),
            "--no-screenshot",
        ]
    )
    assert rc == 0, f"render script exited {rc}"
    rendered = out_html.read_text(encoding="utf-8")
    committed = COMMITTED_HTML.read_text(encoding="utf-8")
    assert rendered == committed, (
        f"docs/regression_demo.html is out of sync with the render script.\n{REGEN_HINT}"
    )


def test_committed_regression_demo_html_carries_synthetic_disclosure() -> None:
    """The committed report must include the synthetic-disclosure framing.

    The script renders "across model versions" into the report's title as
    the cue that the demo is a documentation artifact, not a captured real
    regression. A future renderer refactor that drops the framing should
    be loud rather than silent — even if `test_committed_regression_demo_html_matches_script_output`
    is regenerated alongside the refactor, this test calls out that the
    framing language is part of the contract.
    """
    committed = COMMITTED_HTML.read_text(encoding="utf-8")
    assert "across model versions" in committed, (
        "Synthetic-disclosure framing missing from docs/regression_demo.html. "
        "The demo HTML's title should include 'across model versions' so a "
        "reader doesn't mistake it for a captured real-model regression. "
        "If the wording changed intentionally, update this assertion."
    )
