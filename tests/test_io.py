"""YAML round-trip + sample-snapshot tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from prompt_regression import (
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
    SnapshotValidationError,
    load_snapshot,
    save_snapshot,
)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples" / "snapshots"


def _sample_snapshot() -> Snapshot:
    return Snapshot(
        id="refund-window-pro-v1",
        prompt=Prompt(
            model="claude-haiku-4-5-20251001",
            user="What's the refund window for the Pro plan?",
            system="You are a polite support agent.",
            temperature=0.0,
            max_tokens=256,
        ),
        response_shape=ResponseShape(
            semantic_categories=["refund-window", "plan-tier"],
            structured_slots={
                "refund_days": {"type": "integer"},
                "plan_name": {"type": "string"},
            },
        ),
        canonical=CanonicalResponse(
            text="The Pro plan has a 14-day refund window from purchase.",
            embedding=[0.1, 0.2, -0.05, 0.3],
            embedding_model="text-embedding-3-small",
        ),
    )


def test_round_trip_identity(tmp_path: Path):
    s = _sample_snapshot()
    p = save_snapshot(s, tmp_path / "snap.yml")
    loaded = load_snapshot(p)
    assert loaded == s


def test_save_creates_parent_dirs(tmp_path: Path):
    s = _sample_snapshot()
    p = save_snapshot(s, tmp_path / "deep" / "nested" / "snap.yml")
    assert p.exists()
    assert load_snapshot(p) == s


def test_save_output_is_human_readable_yaml(tmp_path: Path):
    s = _sample_snapshot()
    p = save_snapshot(s, tmp_path / "snap.yml")
    text = p.read_text(encoding="utf-8")
    # Block style, not flow style — keeps PR diffs readable.
    assert "id: refund-window-pro-v1" in text
    assert "prompt:" in text
    assert "{" not in text.splitlines()[0]


def test_load_rejects_top_level_non_mapping(tmp_path: Path):
    p = tmp_path / "bad.yml"
    p.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="mapping"):
        load_snapshot(p)


def test_load_rejects_unknown_schema_version(tmp_path: Path):
    s = _sample_snapshot()
    p = save_snapshot(s, tmp_path / "snap.yml")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["schema_version"] = "99"
    p.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="schema_version"):
        load_snapshot(p)


def test_load_accepts_unquoted_int_schema_version(tmp_path: Path):
    # #75: YAML parses an unquoted `schema_version: 1` as the int 1, not "1".
    # A hand-authored snapshot naturally omits the quotes; it must load
    # identically to the quoted form save_snapshot writes (not be rejected
    # with the baffling "is 1 … supports '1'" message).
    s = _sample_snapshot()
    p = save_snapshot(s, tmp_path / "snap.yml")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["schema_version"] = 1  # unquoted int, the natural hand-authored form
    p.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    # The on-disk line is the bare int, confirming the precondition.
    assert "schema_version: 1\n" in p.read_text(encoding="utf-8")
    loaded = load_snapshot(p)
    assert loaded == s
    assert loaded.schema_version == "1"  # normalized to the canonical string


def test_load_still_rejects_different_int_version(tmp_path: Path):
    # The int tolerance must not swallow a genuinely-different version: an
    # unquoted `schema_version: 2` is still a real mismatch.
    s = _sample_snapshot()
    p = save_snapshot(s, tmp_path / "snap.yml")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["schema_version"] = 2
    p.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="schema_version"):
        load_snapshot(p)


def test_load_propagates_field_errors(tmp_path: Path):
    s = _sample_snapshot()
    p = save_snapshot(s, tmp_path / "snap.yml")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["prompt"]["temperature"] = 9.0
    p.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="temperature"):
        load_snapshot(p)


# --- Committed sample snapshot --------------------------------------------


def test_committed_sample_snapshot_loads():
    """The repo ships a real example snapshot — it must always load cleanly."""
    sample = EXAMPLES_DIR / "refund_window_v1.yml"
    assert sample.exists(), f"sample snapshot missing: {sample}"
    s = load_snapshot(sample)
    assert s.id
    assert s.prompt.model
    assert len(s.canonical.embedding) > 0
    # Re-saving the sample must produce an equivalent snapshot.
    assert Snapshot.from_dict(s.to_dict()) == s
