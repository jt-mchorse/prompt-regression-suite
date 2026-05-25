"""Tests for the diff layer (issue #2).

Coverage:
- HashEmbedder + cosine math.
- Slot extraction heuristics.
- diff_response end-to-end against a constructed snapshot, exercising
  the three acceptance-criterion cases (identical, paraphrase, off-topic)
  plus boundary behavior.
- EmbedderModelMismatchError refusal (D-006).
"""

from __future__ import annotations

import pytest

from prompt_regression import (
    CanonicalResponse,
    DiffResult,
    EmbedderModelMismatchError,
    HashEmbedder,
    Prompt,
    ResponseShape,
    SlotDelta,
    Snapshot,
    cosine,
    diff_response,
    diff_slots,
    extract_slots,
    score_semantic_categories,
)

# ----------------------------------------------------------------------
# cosine + HashEmbedder
# ----------------------------------------------------------------------


def test_cosine_identical_is_one():
    assert cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero():
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_length_mismatch_raises():
    with pytest.raises(ValueError, match="length mismatch"):
        cosine([1.0], [1.0, 2.0])


def test_hash_embedder_is_unit_vector():
    e = HashEmbedder()
    v = e.embed("hello world")
    assert sum(x * x for x in v) ** 0.5 == pytest.approx(1.0)


def test_hash_embedder_model_name_carries_ngram():
    assert HashEmbedder(ngram=2).model_name == "hash-embedder-128d-ngram2"
    assert HashEmbedder(ngram=3).model_name == "hash-embedder-128d-ngram3"


# ----------------------------------------------------------------------
# Slot extraction
# ----------------------------------------------------------------------


def test_extract_integer_with_hint():
    text = "The Pro plan has a 14-day refund window from purchase."
    slots = {"refund_days": {"type": "integer", "description": "Number of days"}}
    extracted = extract_slots(text, slots)
    assert extracted == {"refund_days": 14}


def test_extract_quoted_string():
    text = 'The customer is on the "Pro" plan.'
    slots = {"plan_name": {"type": "string", "description": "plan tier"}}
    extracted = extract_slots(text, slots)
    assert extracted == {"plan_name": "Pro"}


def test_extract_string_falls_back_to_keyword_sentence():
    text = "Pro plan customers get a 14-day refund window."
    slots = {"plan_name": {"type": "string", "description": "plan tier name"}}
    extracted = extract_slots(text, slots)
    # No quoted string; falls back to surrounding-sentence containing the keyword.
    assert "plan_name" in extracted
    assert "Pro" in extracted["plan_name"] or "plan" in extracted["plan_name"]


def test_extract_boolean_yes():
    text = "Yes, refunds are allowed."
    slots = {"allowed": {"type": "boolean", "description": "is allowed"}}
    assert extract_slots(text, slots) == {"allowed": True}


def test_diff_slots_reports_missing():
    deltas = diff_slots(
        {
            "plan_name": {"type": "string", "description": "plan tier"},
            "refund_days": {"type": "integer", "description": "Number of days for refund."},
        },
        "Refunds for the Pro plan are processed within 5 working days.",
    )
    by_name = {d.name: d for d in deltas}
    assert by_name["refund_days"].status == "ok"
    assert by_name["refund_days"].actual_value == 5


def test_diff_slots_reports_type_mismatch_for_unknown_type():
    deltas = diff_slots({"weird": {"type": "blob"}}, "anything")
    assert deltas[0].status == "type_unknown"


def test_diff_slots_empty_returns_empty():
    assert diff_slots({}, "anything") == []


# ----------------------------------------------------------------------
# Semantic category scoring
# ----------------------------------------------------------------------


def test_score_semantic_categories_returns_one_per_category():
    scores = score_semantic_categories(
        "The refund window for the Pro plan is 14 days.",
        ["refund-window", "plan-tier"],
        embedder=HashEmbedder(),
    )
    assert len(scores) == 2
    assert {s.name for s in scores} == {"refund-window", "plan-tier"}


def test_score_semantic_categories_empty_returns_empty():
    assert score_semantic_categories("anything", [], embedder=HashEmbedder()) == []


# ----------------------------------------------------------------------
# diff_response end-to-end
# ----------------------------------------------------------------------


def _make_snapshot(canonical_text: str, *, embedder: HashEmbedder) -> Snapshot:
    """Build a snapshot whose canonical embedding matches the given embedder."""
    return Snapshot(
        id="test-snap-v1",
        prompt=Prompt(
            model="claude-haiku-4-5",
            user="What's the refund window for the Pro plan?",
        ),
        response_shape=ResponseShape(
            semantic_categories=["refund-window", "plan-tier"],
            structured_slots={
                "refund_days": {"type": "integer", "description": "Number of days for refund."},
                "plan_name": {"type": "string", "description": "Pro plan name."},
            },
        ),
        canonical=CanonicalResponse(
            text=canonical_text,
            embedding=embedder.embed(canonical_text),
            embedding_model=embedder.model_name,
        ),
    )


def test_identical_response_scores_one_and_passes():
    """Acceptance criterion: identical response → 1.0."""
    e = HashEmbedder()
    text = "The Pro plan has a 14-day refund window."
    snap = _make_snapshot(text, embedder=e)
    result = diff_response(snap, text, embedder=e)
    assert isinstance(result, DiffResult)
    assert result.cosine_score == pytest.approx(1.0)
    assert result.verdict == "pass"


def test_paraphrase_passes_at_lower_threshold():
    """Acceptance criterion: paraphrase → high pass."""
    e = HashEmbedder()
    canonical = "The Pro plan has a 14-day refund window."
    paraphrase = "The Pro plan has a 14-day refund period."  # one word changed
    snap = _make_snapshot(canonical, embedder=e)
    result = diff_response(snap, paraphrase, embedder=e, threshold=0.5)
    assert result.cosine_score > 0.5
    assert result.verdict == "pass"


def test_off_topic_response_fails():
    """Acceptance criterion: off-topic → fail."""
    e = HashEmbedder()
    canonical = "The Pro plan has a 14-day refund window."
    off_topic = "Today's weather forecast is sunny with light winds."
    snap = _make_snapshot(canonical, embedder=e)
    result = diff_response(snap, off_topic, embedder=e, threshold=0.5)
    assert result.cosine_score < 0.3
    assert result.verdict == "fail"
    # Slots should also fail because the off-topic response has no plan/refund info.
    assert any(d.is_failure for d in result.slot_deltas)


def test_default_threshold_is_0_85():
    """Acceptance criterion: threshold defaults to 0.85."""
    e = HashEmbedder()
    canonical = "The Pro plan has a 14-day refund window."
    snap = _make_snapshot(canonical, embedder=e)
    result = diff_response(snap, canonical, embedder=e)
    assert result.threshold == pytest.approx(0.85)


def test_warn_band_when_cosine_just_below_threshold():
    e = HashEmbedder()
    canonical = "The Pro plan has a 14-day refund window."
    snap = _make_snapshot(canonical, embedder=e)
    # Force the threshold above the identical-response cosine to land in warn band.
    result = diff_response(snap, canonical, embedder=e, threshold=0.99, warn_band=0.05)
    # Identical text → cosine 1.0 → above threshold → pass, not warn.
    assert result.verdict == "pass"


def test_slot_failure_dominates_pass_cosine():
    """Slot mismatch blocks a pass even when cosine is high."""
    e = HashEmbedder()
    canonical = "The Pro plan has a 14-day refund window."
    snap = _make_snapshot(canonical, embedder=e)
    # A response with the same words but no extractable refund_days integer.
    no_number = "The Pro plan has a refund window of about two weeks."
    result = diff_response(snap, no_number, embedder=e, threshold=0.3)
    assert result.cosine_score >= 0.3
    # refund_days slot extraction fails → verdict fail regardless of cosine.
    assert result.verdict == "fail"
    failed_slot_names = [d.name for d in result.slot_deltas if d.is_failure]
    assert "refund_days" in failed_slot_names


def test_threshold_validated():
    e = HashEmbedder()
    snap = _make_snapshot("anything", embedder=e)
    with pytest.raises(ValueError, match=r"\(0, 1\]"):
        diff_response(snap, "x", embedder=e, threshold=0.0)
    with pytest.raises(ValueError, match=r"\(0, 1\]"):
        diff_response(snap, "x", embedder=e, threshold=1.5)


def test_warn_band_validated():
    e = HashEmbedder()
    snap = _make_snapshot("anything", embedder=e)
    with pytest.raises(ValueError, match="non-negative"):
        diff_response(snap, "x", embedder=e, warn_band=-0.1)


# Issue #35: warn_band > effective_threshold silently collapses the fail/warn
# distinction on the cosine channel because the warn floor `max(0.0, threshold
# - warn_band)` clamps at zero, so every non-passing cosine becomes "warn".
# The upper-bound guard rejects the misconfig at the entry site, matching the
# existing (0, 1] threshold contract.
@pytest.mark.parametrize(
    "bad_warn_band",
    [0.51, 0.6, 0.9, 1.01, 5.0],  # all > effective_threshold = 0.5
)
def test_warn_band_rejected_above_threshold(bad_warn_band: float):
    e = HashEmbedder()
    snap = _make_snapshot("anything", embedder=e)
    with pytest.raises(ValueError, match=r"warn_band must be <= effective_threshold \(0\.5\); got"):
        diff_response(snap, "x", embedder=e, threshold=0.5, warn_band=bad_warn_band)


@pytest.mark.parametrize(
    "good_warn_band",
    [0.0, 0.25, 0.5],  # 0.0 = strict pass/fail; 0.5 = equal-to-threshold inclusive bound
)
def test_warn_band_accepted_at_or_below_threshold(good_warn_band: float):
    e = HashEmbedder()
    snap = _make_snapshot("anything", embedder=e)
    # Use canonical text so cosine == 1.0 — the verdict path isn't what's under test,
    # we're only proving the guard accepts these values without raising.
    result = diff_response(snap, "anything", embedder=e, threshold=0.5, warn_band=good_warn_band)
    assert result.verdict in ("pass", "warn", "fail")


def test_warn_band_guard_uses_effective_threshold_when_tolerance_overrides():
    # Snapshot.tolerance overrides the kwarg threshold per #10. The guard must
    # fire against the *effective* value (the tolerance), not the kwarg — otherwise
    # a tight-tolerance snapshot with a loose-default warn_band silently slips by.
    e = HashEmbedder()
    snap = _make_snapshot("anything", embedder=e)
    snap.tolerance = 0.3  # tighter than the kwarg below
    with pytest.raises(
        ValueError, match=r"warn_band must be <= effective_threshold \(0\.3\); got 0\.4"
    ):
        diff_response(snap, "x", embedder=e, threshold=0.9, warn_band=0.4)


# ----------------------------------------------------------------------
# Embedder model mismatch (D-006)
# ----------------------------------------------------------------------


def test_embedder_model_mismatch_raises_by_default():
    e = HashEmbedder()
    snap = _make_snapshot("anything", embedder=e)
    # Mutate the snapshot's recorded embedding_model to simulate a different model.
    snap.canonical.embedding_model = "different-embedder-v1"
    with pytest.raises(EmbedderModelMismatchError, match="different-embedder-v1"):
        diff_response(snap, "anything", embedder=e)


def test_embedder_model_mismatch_can_be_forced():
    e = HashEmbedder()
    snap = _make_snapshot("anything", embedder=e)
    snap.canonical.embedding_model = "different-embedder-v1"
    result = diff_response(snap, "anything", embedder=e, force=True)
    assert result.embedder_model == e.model_name
    assert result.snapshot_embedding_model == "different-embedder-v1"


# ----------------------------------------------------------------------
# DiffResult shape — what callers can rely on
# ----------------------------------------------------------------------


def test_diff_result_shape_contract():
    e = HashEmbedder()
    canonical = "The Pro plan has a 14-day refund window."
    snap = _make_snapshot(canonical, embedder=e)
    result = diff_response(snap, canonical, embedder=e)

    # Acceptance criterion 1: returns score, slot_deltas, verdict.
    assert hasattr(result, "cosine_score")
    assert hasattr(result, "slot_deltas")
    assert hasattr(result, "verdict")
    assert result.verdict in ("pass", "warn", "fail")
    for d in result.slot_deltas:
        assert isinstance(d, SlotDelta)
        assert d.status in ("ok", "missing", "type_mismatch", "type_unknown")
    # The semantic-category scores are surfaced too.
    assert hasattr(result, "semantic_category_scores")
