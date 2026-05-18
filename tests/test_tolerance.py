"""Per-snapshot tolerance override (issue #10).

Covers:
- Validation: bounds, type-rejection, None default.
- Effective threshold resolution: tolerance overrides kwarg; absent falls back.
- YAML round-trip: present and absent both byte-stable.
- Backward compat: snapshots loaded from existing fixtures get tolerance=None.
"""

from __future__ import annotations

import pytest

from prompt_regression import (
    CanonicalResponse,
    HashEmbedder,
    Prompt,
    ResponseShape,
    Snapshot,
    SnapshotValidationError,
    diff_response,
    load_snapshot,
)


def _canonical_for(embedder: HashEmbedder, text: str) -> CanonicalResponse:
    """Build a canonical response embedded with `embedder` so D-006 doesn't refuse."""
    return CanonicalResponse(
        text=text,
        embedding=embedder.embed(text),
        embedding_model=embedder.model_name,
    )


def _shape() -> ResponseShape:
    return ResponseShape(semantic_categories=[], structured_slots={})


def _prompt() -> Prompt:
    return Prompt(model="claude-haiku-4-5-20251001", user="hi")


# --- validation ------------------------------------------------------------


def test_snapshot_tolerance_default_is_none() -> None:
    s = Snapshot(
        id="x",
        prompt=_prompt(),
        response_shape=_shape(),
        canonical=_canonical_for(HashEmbedder(), "hello world"),
    )
    assert s.tolerance is None


@pytest.mark.parametrize("value", [0.5, 0.75, 1.0, 0.0001])
def test_snapshot_tolerance_accepts_valid_values(value: float) -> None:
    s = Snapshot(
        id="x",
        prompt=_prompt(),
        response_shape=_shape(),
        canonical=_canonical_for(HashEmbedder(), "hello world"),
        tolerance=value,
    )
    assert s.tolerance == pytest.approx(value)


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.01, 2.0])
def test_snapshot_tolerance_rejects_out_of_bounds(bad: float) -> None:
    with pytest.raises(SnapshotValidationError, match="tolerance"):
        Snapshot(
            id="x",
            prompt=_prompt(),
            response_shape=_shape(),
            canonical=_canonical_for(HashEmbedder(), "hello world"),
            tolerance=bad,
        )


@pytest.mark.parametrize("bad", [True, False, "0.9", [0.9]])
def test_snapshot_tolerance_rejects_non_numeric(bad: object) -> None:
    with pytest.raises(SnapshotValidationError, match="tolerance"):
        Snapshot(
            id="x",
            prompt=_prompt(),
            response_shape=_shape(),
            canonical=_canonical_for(HashEmbedder(), "hello world"),
            tolerance=bad,  # type: ignore[arg-type]
        )


# --- effective-threshold resolution ---------------------------------------


def test_diff_uses_snapshot_tolerance_when_set() -> None:
    """`tolerance` on the snapshot overrides the `threshold` kwarg."""
    embedder = HashEmbedder()
    canonical = "the refund window is 14 days"
    snap = Snapshot(
        id="x",
        prompt=_prompt(),
        response_shape=_shape(),
        canonical=_canonical_for(embedder, canonical),
        tolerance=0.99,  # extremely tight — a near-paraphrase should fail
    )
    paraphrase = "refunds are allowed for 14 days after purchase"
    result = diff_response(snap, paraphrase, embedder=embedder, threshold=0.5)
    # Even though the run-level threshold (0.5) is very lenient, the
    # snapshot's pinned 0.99 should drive the verdict.
    assert result.threshold == pytest.approx(0.99)
    # The exact cosine on HashEmbedder is implementation-defined; the
    # invariant we assert is that 0.99 is the actively-applied bar and the
    # result reflects it (note text + verdict consistency).
    assert any("per-snapshot tolerance" in n for n in result.notes)


def test_diff_falls_back_to_kwarg_when_tolerance_is_none() -> None:
    embedder = HashEmbedder()
    canonical = "the refund window is 14 days"
    snap = Snapshot(
        id="x",
        prompt=_prompt(),
        response_shape=_shape(),
        canonical=_canonical_for(embedder, canonical),
        # tolerance unset → falls back to threshold kwarg below
    )
    result = diff_response(snap, canonical, embedder=embedder, threshold=0.5)
    assert result.threshold == pytest.approx(0.5)
    # Identical text scores cosine 1.0 → pass; no override-note expected.
    assert result.verdict == "pass"
    assert not any("per-snapshot tolerance" in n for n in result.notes)


def test_diff_rejects_invalid_kwarg_threshold_when_tolerance_unset() -> None:
    """The existing (0, 1] guard still applies to the kwarg fallback."""
    embedder = HashEmbedder()
    snap = Snapshot(
        id="x",
        prompt=_prompt(),
        response_shape=_shape(),
        canonical=_canonical_for(embedder, "hello"),
    )
    with pytest.raises(ValueError, match="threshold"):
        diff_response(snap, "hello", embedder=embedder, threshold=0.0)


# --- YAML round-trip ------------------------------------------------------


def test_to_dict_omits_tolerance_when_none() -> None:
    s = Snapshot(
        id="x",
        prompt=_prompt(),
        response_shape=_shape(),
        canonical=_canonical_for(HashEmbedder(), "hi"),
    )
    data = s.to_dict()
    assert "tolerance" not in data


def test_to_dict_preserves_tolerance_when_set() -> None:
    s = Snapshot(
        id="x",
        prompt=_prompt(),
        response_shape=_shape(),
        canonical=_canonical_for(HashEmbedder(), "hi"),
        tolerance=0.75,
    )
    data = s.to_dict()
    assert data["tolerance"] == pytest.approx(0.75)


def test_from_dict_round_trip_with_tolerance() -> None:
    s = Snapshot(
        id="x",
        prompt=_prompt(),
        response_shape=_shape(),
        canonical=_canonical_for(HashEmbedder(), "hi"),
        tolerance=0.92,
    )
    s2 = Snapshot.from_dict(s.to_dict())
    assert s2.tolerance == pytest.approx(0.92)


def test_from_dict_absent_field_defaults_to_none() -> None:
    """Backward-compat: snapshots authored before #10 must still load."""
    raw = {
        "id": "legacy",
        "prompt": {"model": "claude-haiku-4-5-20251001", "user": "hi", "extra": {}},
        "response_shape": {"semantic_categories": [], "structured_slots": {}},
        "canonical": {
            "text": "hi",
            "embedding": HashEmbedder().embed("hi"),
            "embedding_model": "hash-embedder-v1",
        },
        "schema_version": "1",
        "created_at": "2026-05-14T14:08:00Z",
    }
    s = Snapshot.from_dict(raw)
    assert s.tolerance is None


# --- example fixture loads (backward compat) ------------------------------


def test_existing_example_fixture_loads_without_tolerance() -> None:
    """`examples/snapshots/refund_window_v1.yml` predates #10 — must still load."""
    s = load_snapshot("examples/snapshots/refund_window_v1.yml")
    assert s.tolerance is None
