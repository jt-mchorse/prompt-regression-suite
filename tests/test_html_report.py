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
from prompt_regression.html_report import (
    ErrorEntry,
    ReportEntry,
    _safe_anchor,
    render_report,
)


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


def test_error_entry_renders_section_and_counts_toward_summary():
    # Issue #71: an ErrorEntry (no DiffResult) must render its own section and
    # be counted in `total` + an `error` stat, so the HTML can't read "all pass"
    # when a snapshot actually errored.
    entries = [
        ReportEntry("ok-one", _diff(verdict="pass"), "ok"),
        ErrorEntry("broke", "embedder model 'x' != snapshot model 'y'"),
    ]
    html = render_report(entries)
    assert '<section class="section error"' in html
    assert 'id="snapshot-broke"' in html
    assert "embedder model &#x27;x&#x27; != snapshot model &#x27;y&#x27;" in html
    # total counts both; the error stat appears with count 1.
    assert ">2</strong>snapshots" in html.replace("<strong", ">")
    assert ">1</strong>error" in html.replace("<strong", ">")


def test_no_error_entries_keeps_header_without_error_stat():
    # The error stat is suppressed when there are no errors, preserving the
    # original four-stat header.
    html = render_report([ReportEntry("a", _diff(verdict="pass"), "ok")])
    assert ">error</div>" not in html


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


def test_slot_row_css_class_matches_status_including_type_unknown():
    """Each slot row's CSS class is driven by its status so the report colors
    it correctly. Regression for #87: since #83 made `is_failure` False for
    `type_unknown`, the old `is_failure`-keyed class painted a type_unknown
    slot `slot-ok` (green) — falsely clean — instead of amber
    `slot-type_unknown`."""
    diff = _diff(
        verdict="fail",
        slots=[
            SlotDelta("a_ok", "string", "v", "ok"),
            SlotDelta("b_missing", "integer", None, "missing"),
            SlotDelta("c_mismatch", "integer", "x", "type_mismatch"),
            SlotDelta("d_unknown", "array", None, "type_unknown"),
        ],
    )
    html = render_report([ReportEntry("slots-v1", diff, "cand", "base")])

    # Map each rendered <tr class="slot-..."> to the status in its 4th <td>.
    # Bound each row at </tr> so the last row doesn't read into later tables.
    class_by_status = {}
    for chunk in html.split('<tr class="slot-')[1:]:
        row = chunk.split("</tr>")[0]
        klass = "slot-" + row.split('"', 1)[0]
        status = row.split("<td>")[-1].split("</td>")[0]
        class_by_status[status] = klass

    assert class_by_status["ok"] == "slot-ok"
    assert class_by_status["missing"] == "slot-missing"
    assert class_by_status["type_mismatch"] == "slot-type_mismatch"
    # The fix: type_unknown is amber-class, not slot-ok.
    assert class_by_status["type_unknown"] == "slot-type_unknown"


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


def test_colliding_snapshot_ids_get_unique_anchors():
    # Regression (#107): `_safe_anchor` collapses case + separator style, so
    # `"My Test"`, `"my-test"`, `"my_test"` all slugify to `snapshot-my-test`.
    # Emitting them raw produced three sections with the same `id=` — invalid
    # HTML, and every `#snapshot-my-test` deep-link jumped to the first one.
    # render_report must disambiguate so each section has a document-unique id.
    import re

    entries = [
        ReportEntry("My Test", _diff(verdict="pass"), "ok"),
        ReportEntry("my-test", _diff(verdict="warn"), "ok"),
        ReportEntry("my_test", _diff(verdict="fail"), "ok"),
    ]
    html = render_report(entries)

    ids = re.findall(r'id="(snapshot-[^"]*)"', html)
    assert len(ids) == 3, ids
    assert len(set(ids)) == 3, f"duplicate section ids: {ids}"
    # GitHub-style disambiguation: first keeps the base, then -1, -2.
    assert ids == ["snapshot-my-test", "snapshot-my-test-1", "snapshot-my-test-2"]
    # Every header anchor link targets an id that actually exists exactly once,
    # so no deep-link silently resolves to the wrong section.
    for href in re.findall(r'href="#(snapshot-[^"]*)"', html):
        assert ids.count(href) == 1, f"href #{href} is ambiguous among {ids}"


def test_suffixed_anchor_does_not_collide_with_literal_id():
    # The disambiguator loops against all assigned anchors, so a synthesized
    # `-1` suffix can't clash with a real snapshot literally named to hit it.
    import re

    entries = [
        ReportEntry("dup", _diff(verdict="pass"), "ok"),
        ReportEntry("dup", _diff(verdict="pass"), "ok"),  # -> snapshot-dup-1
        ReportEntry("dup-1", _diff(verdict="pass"), "ok"),  # must NOT reuse snapshot-dup-1
    ]
    html = render_report(entries)
    ids = re.findall(r'id="(snapshot-[^"]*)"', html)
    assert len(set(ids)) == 3, f"duplicate section ids: {ids}"


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
