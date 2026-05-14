"""Schema-level validation tests for the snapshot dataclasses."""

from __future__ import annotations

import pytest

from prompt_regression import (
    SCHEMA_VERSION,
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
    SnapshotValidationError,
)


def _valid_canonical() -> CanonicalResponse:
    return CanonicalResponse(
        text="The refund window for that plan is 14 days from purchase.",
        embedding=[0.1, 0.2, -0.05, 0.3],
        embedding_model="text-embedding-3-small",
    )


def _valid_prompt() -> Prompt:
    return Prompt(
        model="claude-haiku-4-5-20251001",
        user="What's the refund window for the Pro plan?",
        system="You are a polite support agent.",
        temperature=0.0,
        max_tokens=256,
    )


def _valid_shape() -> ResponseShape:
    return ResponseShape(
        semantic_categories=["refund-window", "plan-tier"],
        structured_slots={
            "refund_days": {"type": "integer"},
            "plan_name": {"type": "string"},
        },
    )


# --- Prompt ---------------------------------------------------------------


def test_prompt_minimal_valid():
    p = Prompt(model="claude-haiku-4-5-20251001", user="hi")
    assert p.system is None
    assert p.temperature is None
    assert p.max_tokens is None
    assert p.extra == {}


def test_prompt_temperature_bounds():
    with pytest.raises(SnapshotValidationError, match="temperature"):
        Prompt(model="m", user="u", temperature=2.5)
    with pytest.raises(SnapshotValidationError, match="temperature"):
        Prompt(model="m", user="u", temperature=-0.1)


def test_prompt_temperature_bool_is_rejected():
    with pytest.raises(SnapshotValidationError, match="temperature"):
        Prompt(model="m", user="u", temperature=True)


def test_prompt_max_tokens_must_be_positive_int():
    with pytest.raises(SnapshotValidationError, match="max_tokens"):
        Prompt(model="m", user="u", max_tokens=0)
    with pytest.raises(SnapshotValidationError, match="max_tokens"):
        Prompt(model="m", user="u", max_tokens=-1)
    with pytest.raises(SnapshotValidationError, match="max_tokens"):
        Prompt(model="m", user="u", max_tokens=12.5)  # type: ignore[arg-type]


def test_prompt_empty_strings_rejected():
    with pytest.raises(SnapshotValidationError, match="model"):
        Prompt(model="", user="u")
    with pytest.raises(SnapshotValidationError, match="user"):
        Prompt(model="m", user="")


def test_prompt_extra_round_trips():
    p = Prompt(model="m", user="u", extra={"top_p": 0.9, "tools": [{"name": "search"}]})
    assert p.extra["top_p"] == 0.9
    assert p.extra["tools"][0]["name"] == "search"


# --- ResponseShape --------------------------------------------------------


def test_response_shape_defaults():
    s = ResponseShape()
    assert s.semantic_categories == []
    assert s.structured_slots == {}


def test_response_shape_rejects_duplicate_categories():
    with pytest.raises(SnapshotValidationError, match="duplicate"):
        ResponseShape(semantic_categories=["a", "a"])


def test_response_shape_rejects_non_string_category():
    with pytest.raises(SnapshotValidationError):
        ResponseShape(semantic_categories=[1, 2])  # type: ignore[list-item]


def test_response_shape_slot_requires_type():
    with pytest.raises(SnapshotValidationError, match="type"):
        ResponseShape(structured_slots={"x": {}})


def test_response_shape_slot_type_must_be_allowed():
    with pytest.raises(SnapshotValidationError, match="type"):
        ResponseShape(structured_slots={"x": {"type": "datetime"}})


def test_response_shape_accepts_all_allowed_types():
    slots = {
        "a": {"type": "string"},
        "b": {"type": "number"},
        "c": {"type": "integer"},
        "d": {"type": "boolean"},
        "e": {"type": "array"},
        "f": {"type": "object"},
        "g": {"type": "null"},
    }
    s = ResponseShape(structured_slots=slots)
    assert set(s.structured_slots.keys()) == set(slots.keys())


# --- CanonicalResponse ----------------------------------------------------


def test_canonical_embedding_must_be_non_empty():
    with pytest.raises(SnapshotValidationError, match="non-empty"):
        CanonicalResponse(text="t", embedding=[], embedding_model="m")


def test_canonical_embedding_floats_coerced():
    c = CanonicalResponse(text="t", embedding=[1, 2, 3], embedding_model="m")  # type: ignore[list-item]
    assert c.embedding == [1.0, 2.0, 3.0]
    assert all(isinstance(v, float) for v in c.embedding)


def test_canonical_embedding_rejects_strings():
    with pytest.raises(SnapshotValidationError):
        CanonicalResponse(text="t", embedding=["0.1"], embedding_model="m")  # type: ignore[list-item]


# --- Snapshot -------------------------------------------------------------


def test_snapshot_valid_round_trip_dict():
    s = Snapshot(
        id="refund-window-v1",
        prompt=_valid_prompt(),
        response_shape=_valid_shape(),
        canonical=_valid_canonical(),
    )
    d = s.to_dict()
    rebuilt = Snapshot.from_dict(d)
    assert rebuilt == s


def test_snapshot_defaults_schema_version_to_current():
    s = Snapshot(
        id="x",
        prompt=_valid_prompt(),
        response_shape=_valid_shape(),
        canonical=_valid_canonical(),
    )
    assert s.schema_version == SCHEMA_VERSION


def test_snapshot_from_dict_rejects_missing_section():
    s = Snapshot(
        id="x",
        prompt=_valid_prompt(),
        response_shape=_valid_shape(),
        canonical=_valid_canonical(),
    )
    bad = s.to_dict()
    del bad["canonical"]
    with pytest.raises(SnapshotValidationError, match="canonical"):
        Snapshot.from_dict(bad)


def test_snapshot_from_dict_rejects_unknown_field():
    s = Snapshot(
        id="x",
        prompt=_valid_prompt(),
        response_shape=_valid_shape(),
        canonical=_valid_canonical(),
    )
    bad = s.to_dict()
    bad["prompt"]["unknown_field"] = 1
    with pytest.raises(SnapshotValidationError):
        Snapshot.from_dict(bad)


def test_snapshot_notes_optional_and_omitted_when_none():
    s = Snapshot(
        id="x",
        prompt=_valid_prompt(),
        response_shape=_valid_shape(),
        canonical=_valid_canonical(),
    )
    assert "notes" not in s.to_dict()


def test_snapshot_notes_round_trip_when_present():
    s = Snapshot(
        id="x",
        prompt=_valid_prompt(),
        response_shape=_valid_shape(),
        canonical=_valid_canonical(),
        notes="captured against staging traffic on 2026-05-14",
    )
    assert s.to_dict()["notes"].startswith("captured")
    assert Snapshot.from_dict(s.to_dict()) == s


def test_snapshot_rejects_non_mapping_payload():
    with pytest.raises(SnapshotValidationError):
        Snapshot.from_dict("not a mapping")  # type: ignore[arg-type]
