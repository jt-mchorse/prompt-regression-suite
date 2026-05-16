"""HTML report rendering tests (#3).

Asserts on the generated HTML structure rather than pixel-perfect output:
- Each entry produces a `<section id="snapshot-...">` with the right verdict class.
- Anchor links are stable and slug-safe.
- Failing entries include the categories table, slots table, and both response panes.
- Passing entries collapse to the one-line note.
- The summary stats reflect the input counts.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import DiffResult, SemanticCategoryScore, SlotDelta
from prompt_regression.html_report import ReportEntry, _safe_anchor, render_report


def _diff(
    verdict: str = "fail",
    cosine_score: float = 0.62,
    threshold: float = 0.85,
    categories=None,
    slots=None,
    notes=None,
) -> DiffResult:
    return DiffResult(
        cosine_score=cosine_score,
        semantic_category_scores=categories or [],
        slot_deltas=slots or [],
        verdict=verdict,
        threshold=threshold,
        embedder_model="hash-v1",
        snapshot_embedding_model="hash-v1",
        notes=notes or [],
    )


def test_summary_stats_reflect_inputs():
    entries = [
        ReportEntry("a", _diff(verdict="pass"), "ok"),
        ReportEntry("b", _diff(verdict="warn"), "ok"),
        ReportEntry("c", _diff(verdict="fail"), "ok"),
        ReportEntry("d", _diff(verdict="fail"), "ok"),
    ]
    html = render_report(entries)
    assert ">4</strong>snapshots" in html.replace("<strong", ">")
    # Counts per verdict appear next to their stat divs.
    assert ">1</strong>pass" in html.replace("<strong", ">")
    assert ">1</strong>warn" in html.replace("<strong", ">")
    assert ">2</strong>fail" in html.replace("<strong", ">")


def test_fail_section_has_categories_slots_responses():
    diff = _diff(
        verdict="fail",
        cosine_score=0.42,
        categories=[SemanticCategoryScore("refund-window", 0.61)],
        slots=[SlotDelta("refund_days", "integer", None, "missing")],
    )
    entry = ReportEntry("refund-v1", diff, candidate_text="some answer", baseline_text="canonical")
    html = render_report([entry])
    assert '<section class="section fail"' in html
    assert 'id="snapshot-refund-v1"' in html
    assert "Semantic categories" in html
    assert "refund-window" in html
    assert "0.610" in html
    assert "Structured slots" in html
    assert "refund_days" in html
    assert "missing" in html
    assert "Responses (baseline vs candidate)" in html
    assert "canonical" in html
    assert "some answer" in html


def test_pass_section_collapses_details():
    diff = _diff(verdict="pass", cosine_score=0.97)
    entry = ReportEntry("clean-v1", diff, candidate_text="x", baseline_text="x")
    html = render_report([entry])
    assert "All channels passed; details elided." in html
    # Passing sections should not render the categories/slots tables.
    assert "Semantic categories" not in html
    assert "Structured slots" not in html
    assert "Responses (baseline vs candidate)" not in html


def test_warn_section_still_renders_tables():
    # Warn is between pass and fail; we render full details so the
    # operator can see *why* the warn fired before promoting to fail.
    diff = _diff(
        verdict="warn",
        cosine_score=0.86,
        threshold=0.85,
        categories=[SemanticCategoryScore("plan-tier", 0.78)],
        slots=[SlotDelta("plan_name", "string", "Pro", "ok")],
    )
    entry = ReportEntry("warn-1", diff, candidate_text="x", baseline_text="y")
    html = render_report([entry])
    assert '<section class="section warn"' in html
    assert "plan-tier" in html
    assert "plan_name" in html


def test_anchor_slugifies_unsafe_characters():
    assert _safe_anchor("Refund Window v1") == "refund-window-v1"
    assert _safe_anchor("foo/bar.baz") == "foobarbaz"
    assert _safe_anchor("UPPER_under-score") == "upper-under-score"
    # Defensive: never returns empty.
    assert _safe_anchor("!!!") == "snapshot"


def test_notes_block_renders_when_present():
    diff = _diff(verdict="warn", notes=["embedder model mismatch overridden via force=True"])
    entry = ReportEntry("n", diff, "x", baseline_text="y")
    html = render_report([entry])
    assert "embedder model mismatch" in html
    assert '<ul class="notes">' in html


def test_no_notes_block_when_absent():
    entry = ReportEntry("n", _diff(verdict="pass"), "x", baseline_text="y")
    html = render_report([entry])
    assert '<ul class="notes">' not in html


def test_empty_categories_and_slots_show_muted_callout():
    diff = _diff(verdict="fail", categories=[], slots=[])
    entry = ReportEntry("e", diff, candidate_text="x", baseline_text="y")
    html = render_report([entry])
    assert "No semantic categories declared." in html
    assert "No structured slots declared." in html


def test_renders_full_html_document_with_title():
    html = render_report([], title="Custom Title")
    assert "<!doctype html>" in html
    assert "<title>Custom Title</title>" in html
    # Empty list still renders the page shell.
    assert "snapshots" in html


def test_escapes_html_unsafe_content():
    diff = _diff(verdict="fail")
    entry = ReportEntry(
        snapshot_id="snap<script>",
        diff=diff,
        candidate_text="<img src=x onerror=alert(1)>",
        baseline_text="</section><h1>injected</h1>",
    )
    html = render_report([entry])
    # Raw `<script>` should be HTML-escaped in the title.
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html  # escaped to &lt;img...
    assert "&lt;img src=x" in html
    # The fake `</section>` in baseline must not break out of the section.
    assert "&lt;/section&gt;" in html


def test_meta_line_includes_threshold_and_embedder():
    diff = _diff(
        verdict="fail",
        threshold=0.9,
    )
    entry = ReportEntry("e", diff, "x", baseline_text="y")
    html = render_report([entry])
    assert "0.900" in html  # threshold
    assert "hash-v1" in html  # embedder + snapshot model


@pytest.fixture
def html_against_three_entries() -> str:
    return render_report(
        [
            ReportEntry("alpha", _diff(verdict="pass"), "a", "a"),
            ReportEntry(
                "bravo",
                _diff(
                    verdict="fail",
                    cosine_score=0.5,
                    slots=[SlotDelta("count", "integer", "five", "type_mismatch")],
                ),
                candidate_text="five",
                baseline_text="5",
            ),
            ReportEntry("charlie", _diff(verdict="warn"), "c", "c"),
        ]
    )


def test_all_entries_get_distinct_anchors(html_against_three_entries: str):
    html = html_against_three_entries
    for snap_id in ("alpha", "bravo", "charlie"):
        assert f'id="snapshot-{snap_id}"' in html


def test_entries_preserve_input_order(html_against_three_entries: str):
    html = html_against_three_entries
    a = html.index("snapshot-alpha")
    b = html.index("snapshot-bravo")
    c = html.index("snapshot-charlie")
    assert a < b < c
