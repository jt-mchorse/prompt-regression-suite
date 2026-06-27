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

import math

import pytest

from prompt_regression import (
    CanonicalResponse,
    DiffResult,
    EmbedderModelMismatchError,
    EmbeddingDimensionMismatchError,
    HashEmbedder,
    NonFiniteEmbeddingError,
    Prompt,
    ResponseShape,
    SemanticCategoryScore,
    SlotDelta,
    Snapshot,
    cosine,
    diff_response,
    diff_slots,
    extract_slots,
    score_semantic_categories,
)


def test_diff_response_dimension_mismatch_raises():
    # A snapshot whose embedding_model matches the active embedder (so the
    # D-006 name guard passes) but whose stored vector is a different length
    # must raise a catchable EmbeddingDimensionMismatchError, not crash cosine()
    # with a raw ValueError that would abort a whole `run` batch.
    e = HashEmbedder()  # produces 128-dim vectors
    snap = Snapshot(
        id="dim-mismatch-v1",
        prompt=Prompt(model="claude-haiku-4-5", user="?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text="hello world",
            embedding=[0.1] * 64,  # 64 dims — half what HashEmbedder emits
            embedding_model=e.model_name,  # but the model name still matches
        ),
    )
    with pytest.raises(EmbeddingDimensionMismatchError, match="64"):
        diff_response(snap, "hello world", embedder=e)


class _NonFiniteEmbedder:
    """BYO embedder (Protocol) that returns a candidate vector with one
    non-finite component — simulating an API hiccup / 0-division in a
    custom wrapper. Dimension matches HashEmbedder so the dimension guard
    passes and we exercise the finiteness guard specifically."""

    def __init__(self, model_name: str, dims: int, bad: float) -> None:
        self._model_name = model_name
        self._dims = dims
        self._bad = bad

    @property
    def model_name(self) -> str:
        return self._model_name  # matches the stored snapshot so the D-006 guard passes

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dims
        vec[0] = self._bad
        return vec


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_diff_response_non_finite_candidate_raises(bad: float):
    # The stored embedding's finiteness is enforced at schema load; a BYO
    # embedder returning a non-finite candidate component would otherwise
    # produce a `nan` cosine_score (silently a misleading `fail`). It must
    # raise a catchable NonFiniteEmbeddingError instead.
    e = HashEmbedder()
    text = "The Pro plan has a 14-day refund window."
    snap = Snapshot(
        id="nonfinite-v1",
        prompt=Prompt(model="claude-haiku-4-5", user="?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text=text, embedding=e.embed(text), embedding_model=e.model_name
        ),
    )
    bad_embedder = _NonFiniteEmbedder(e.model_name, len(e.embed(text)), bad)
    with pytest.raises(NonFiniteEmbeddingError, match="non-finite"):
        diff_response(snap, text, embedder=bad_embedder)


def test_diff_response_finite_candidate_still_diffs():
    # Regression: a normal finite embedder is unaffected by the new guard.
    e = HashEmbedder()
    text = "The Pro plan has a 14-day refund window."
    snap = Snapshot(
        id="finite-v1",
        prompt=Prompt(model="claude-haiku-4-5", user="?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text=text, embedding=e.embed(text), embedding_model=e.model_name
        ),
    )
    result = diff_response(snap, text, embedder=e)
    assert math.isfinite(result.cosine_score)
    assert result.cosine_score == pytest.approx(1.0)


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


@pytest.mark.parametrize("slot_type", ["array", "object", "null"])
def test_diff_slots_unextracted_schema_valid_type_is_type_unknown(slot_type):
    # #77: array/object/null are schema-valid (schema._ALLOWED_SLOT_TYPES) but
    # have no extractor, so diff_slots must report them as `type_unknown` ("the
    # tool did not try") — not `missing` ("the model failed to produce it").
    # Pre-fix they fell through to `missing` because the gate keyed on
    # SLOT_TYPE_PYTHON, which lists these types. `missing` would mark every diff
    # of such a snapshot as a (false) model regression, permanently.
    deltas = diff_slots({"x": {"type": slot_type}}, "a list [1,2,3] and an object {k: v}")
    assert len(deltas) == 1
    assert deltas[0].status == "type_unknown"
    assert deltas[0].status != "missing"


def test_diff_slots_extractable_types_unaffected_by_type_unknown_gate():
    # Guard the fix's blast radius: the extractable types still produce real
    # verdicts — a present integer is `ok`, an absent one is `missing` (a true
    # regression), neither swallowed by the type_unknown branch.
    present = diff_slots({"n": {"type": "integer"}}, "the count is 42")[0]
    absent = diff_slots({"n": {"type": "integer"}}, "no numbers here")[0]
    assert present.status == "ok"
    assert present.actual_value == 42
    assert absent.status == "missing"


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


class _CategoryNonFiniteEmbedder:
    """BYO embedder that embeds finite for most inputs but returns a
    non-finite component for one specific text (a category label) — models a
    custom embedder that glitches on some inputs and not others. Dimension
    matches HashEmbedder so the dimension guard passes and we exercise the
    finiteness guard on the semantic-category channel specifically (#69)."""

    def __init__(self, model_name: str, dims: int, poison_text: str, bad: float) -> None:
        self._model_name = model_name
        self._dims = dims
        self._poison_text = poison_text
        self._bad = bad

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, text: str) -> list[float]:
        vec = [0.1] * self._dims
        if text == self._poison_text:
            vec[0] = self._bad
        return vec


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_score_semantic_categories_raises_on_non_finite_category(bad: float):
    # #67's guard covers the main cosine_score path; the semantic-category
    # channel re-embeds the candidate and each category label and called
    # cosine() unguarded, so a non-finite category embedding produced a `nan`
    # cosine_to_response that leaked into the report. Must raise instead.
    dims = len(HashEmbedder().embed("x"))
    embedder = _CategoryNonFiniteEmbedder("hash-v1", dims, poison_text="refunds", bad=bad)
    with pytest.raises(NonFiniteEmbeddingError, match="non-finite"):
        score_semantic_categories("a finite candidate", ["plans", "refunds"], embedder=embedder)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_diff_response_non_finite_category_raises_even_when_candidate_finite(bad: float):
    # End-to-end: the candidate embeds finite (passes the #67 main-path guard),
    # but a category label embeds non-finite. Before the fix this slipped
    # through to a `nan` cosine_to_response; now it raises a catchable error the
    # `run` batch records per-row.
    e = HashEmbedder()
    text = "The Pro plan has a 14-day refund window."
    snap = Snapshot(
        id="cat-nonfinite-v1",
        prompt=Prompt(model="claude-haiku-4-5", user="?"),
        response_shape=ResponseShape(
            semantic_categories=["plan-tier", "refunds"], structured_slots={}
        ),
        canonical=CanonicalResponse(
            text=text, embedding=e.embed(text), embedding_model=e.model_name
        ),
    )
    dims = len(e.embed(text))
    bad_embedder = _CategoryNonFiniteEmbedder(e.model_name, dims, poison_text="refunds", bad=bad)
    with pytest.raises(NonFiniteEmbeddingError, match="non-finite"):
        diff_response(snap, text, embedder=bad_embedder)


def test_score_semantic_categories_finite_embedder_unchanged():
    # Regression: a finite embedder still returns one score per category.
    scores = score_semantic_categories(
        "The refund window for the Pro plan is 14 days.",
        ["refund-window", "plan-tier"],
        embedder=HashEmbedder(),
    )
    assert len(scores) == 2
    assert all(math.isfinite(s.cosine_to_response) for s in scores)


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


# A non-finite warn_band is NaN-blind to the sign checks (`NaN < 0` and
# `NaN > threshold` are both False), so it slips past both and collapses the
# cosine warn floor `max(0.0, threshold - NaN)` to 0.0 — demoting every failing
# cosine to "warn" and silently disabling the gate (the #35 collapse via a value
# `>` can't catch). Reject it loudly, like the sibling threshold range check.
@pytest.mark.parametrize("bad_warn_band", [float("nan"), float("inf"), float("-inf")])
def test_warn_band_rejects_non_finite(bad_warn_band: float):
    e = HashEmbedder()
    snap = _make_snapshot("anything", embedder=e)
    with pytest.raises(ValueError, match="warn_band must be finite"):
        diff_response(snap, "x", embedder=e, threshold=0.8, warn_band=bad_warn_band)


def test_nan_warn_band_would_demote_fail_to_warn_without_the_guard():
    # Pins the consequence the guard prevents: an off-topic candidate (cosine
    # well below threshold) must be "fail", never "warn". With a NaN warn_band
    # and no guard the verdict was "warn"; the guard now makes this raise.
    e = HashEmbedder()
    snap = _make_snapshot("The refund period is 14 days.", embedder=e)
    with pytest.raises(ValueError, match="warn_band must be finite"):
        diff_response(
            snap,
            "Completely unrelated sentence.",
            embedder=e,
            threshold=0.8,
            warn_band=float("nan"),
        )


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


def test_tolerance_one_is_strictest_only_identical_passes():
    # tolerance is the required cosine floor (the gate is `cosine >= tolerance`),
    # so tolerance=1.0 is the STRICTEST setting: it passes only an
    # embedding-identical response and fails any drift. The stats summary's
    # `count_strictest` counts exactly these snapshots — it used to be mislabeled
    # `count_always_pass`/"always_pass", the inverse of the behavior. Pin the
    # semantics so the label can't silently re-invert.
    e = HashEmbedder()
    text = "the quick brown fox jumps over the lazy dog"
    # No structured slots, so the verdict is driven by the cosine channel alone.
    snap = Snapshot(
        id="strictest-v1",
        prompt=Prompt(model="claude-haiku-4-5", user="?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text=text, embedding=e.embed(text), embedding_model=e.model_name
        ),
        tolerance=1.0,
    )
    identical = diff_response(snap, text, embedder=e)
    assert identical.verdict == "pass"
    assert identical.cosine_score == pytest.approx(1.0)
    drifted = diff_response(snap, "an entirely unrelated paragraph about taxes", embedder=e)
    assert drifted.verdict == "fail"  # any drift fails at the strictest tolerance


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


# ----------------------------------------------------------------------
# #51: observability-parity — explicit .to_dict() field contracts
# (no dataclasses.asdict). Same pattern as
# python-async-llm-pipelines#45, rag-production-kit#51,
# llm-cost-optimizer#51/#53, vector-search-at-scale#40.
# ----------------------------------------------------------------------


class TestSlotDeltaToDict:
    def test_field_set_is_pinned(self):
        d = SlotDelta(name="x", expected_type="string", actual_value="hello", status="ok").to_dict()
        assert sorted(d.keys()) == ["actual_value", "expected_type", "name", "status"]

    def test_values_round_trip(self):
        d = SlotDelta(name="customer_id", expected_type="string", actual_value="C-42", status="ok")
        assert d.to_dict() == {
            "name": "customer_id",
            "expected_type": "string",
            "actual_value": "C-42",
            "status": "ok",
        }

    def test_actual_value_can_be_none_when_missing(self):
        d = SlotDelta(name="x", expected_type="integer", actual_value=None, status="missing")
        out = d.to_dict()
        assert out["actual_value"] is None
        assert out["status"] == "missing"


class TestSemanticCategoryScoreToDict:
    def test_field_set_is_pinned(self):
        d = SemanticCategoryScore(name="refund", cosine_to_response=0.42).to_dict()
        assert sorted(d.keys()) == ["cosine_to_response", "name"]

    def test_values_round_trip(self):
        s = SemanticCategoryScore(name="refund-eligibility", cosine_to_response=0.81)
        assert s.to_dict() == {
            "name": "refund-eligibility",
            "cosine_to_response": 0.81,
        }


def _diff_result_for_contract() -> DiffResult:
    e = HashEmbedder()
    canonical = "The Pro plan has a 14-day refund window."
    snap = Snapshot(
        id="t",
        prompt=Prompt(model="claude-3-haiku-20240307", user="What is the refund window?"),
        response_shape=ResponseShape(
            semantic_categories=["refund-eligibility"],
            structured_slots={"days": {"type": "integer", "description": "days"}},
        ),
        canonical=CanonicalResponse(
            text=canonical, embedding=e.embed(canonical), embedding_model=e.model_name
        ),
    )
    return diff_response(snap, canonical, embedder=e)


class TestDiffResultToDict:
    def test_field_set_is_pinned(self):
        d = _diff_result_for_contract().to_dict()
        assert sorted(d.keys()) == [
            "cosine_score",
            "embedder_model",
            "notes",
            "semantic_category_scores",
            "slot_deltas",
            "snapshot_embedding_model",
            "threshold",
            "verdict",
        ]

    def test_nested_shapes_owned_by_nested_to_dicts(self):
        d = _diff_result_for_contract().to_dict()
        if d["slot_deltas"]:
            assert sorted(d["slot_deltas"][0].keys()) == [
                "actual_value",
                "expected_type",
                "name",
                "status",
            ]
        if d["semantic_category_scores"]:
            assert sorted(d["semantic_category_scores"][0].keys()) == [
                "cosine_to_response",
                "name",
            ]

    def test_notes_is_a_list_copy(self):
        # Mutating the returned dict's notes list must not bleed back
        # into the frozen DiffResult instance.
        result = _diff_result_for_contract()
        out = result.to_dict()
        out["notes"].append("leaked")
        assert "leaked" not in result.notes


class TestCliSerializeDiffMatchesToDict:
    """Acceptance regression: cli._serialize_diff delegates to to_dict (#51)."""

    def test_cli_serialize_diff_equals_to_dict(self):
        from prompt_regression.cli import _serialize_diff  # type: ignore[attr-defined]

        result = _diff_result_for_contract()
        assert _serialize_diff(result) == result.to_dict()
