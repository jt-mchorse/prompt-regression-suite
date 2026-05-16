"""Test the demo regression renderer (#4).

The script itself is small; the meaningful test is that running it
produces a `fail` verdict on the synthetic regression, since that's
the whole demo. If a future refactor accidentally makes the upgraded
response score close enough to the baseline that the diff layer
passes it, this test catches that.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from render_regression_demo import (  # noqa: E402
    _BASELINE_TEXT,
    _UPGRADED_TEXT,
    _build_snapshot,
    main,
)

from prompt_regression.diff import HashEmbedder, diff_response  # noqa: E402


def test_demo_regression_actually_fails_the_diff():
    embedder = HashEmbedder()
    snapshot = _build_snapshot(embedder)
    diff = diff_response(snapshot, _UPGRADED_TEXT, embedder=embedder)
    # The whole point: the upgraded response doesn't pass the diff.
    assert diff.verdict == "fail"
    # The baseline response should *still* pass the diff against itself.
    diff_self = diff_response(snapshot, _BASELINE_TEXT, embedder=embedder)
    assert diff_self.verdict == "pass"


def test_demo_loses_the_eligibility_caveat_slot():
    embedder = HashEmbedder()
    snapshot = _build_snapshot(embedder)
    diff = diff_response(snapshot, _UPGRADED_TEXT, embedder=embedder)
    # The point of the demo regression: the upgraded response no longer
    # asserts the `eligibility_caveat` slot the baseline declared.
    caveat = next(s for s in diff.slot_deltas if s.name == "eligibility_caveat")
    assert caveat.is_failure


def test_main_writes_html_to_specified_path(tmp_path: Path):
    out_html = tmp_path / "report.html"
    rc = main(
        ["--out-html", str(out_html), "--out-png", str(tmp_path / "x.png"), "--no-screenshot"]
    )
    assert rc == 0
    assert out_html.exists()
    contents = out_html.read_text(encoding="utf-8")
    assert "<!doctype html>" in contents
    assert "Regression demo" in contents
    # The synthetic-disclosure framing should be present in the rendered
    # report's title so a reader doesn't mistake it for a real regression.
    assert "across model versions" in contents
