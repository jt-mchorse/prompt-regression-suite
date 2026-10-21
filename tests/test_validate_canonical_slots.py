"""A snapshot that fails a diff against its own canonical is a finding (#276).

#207 made `update` refuse a canonical that fails the snapshot's own
`structured_slots` and left the other two ways into that state alone: editing
the YAML by hand -- which `update`'s refusal tells the operator to do -- and the
library `save_snapshot`. Measured on `main` 376609b, the shipped kite example
with one integer slot `line_count` added:

    prompt-snap validate s                            -> ok ... findings=0   rc 0
    prompt-snap diff --candidate "<its own canonical>" -> verdict: fail
                                                          [FAIL] line_count: missing

The type-mismatch arm is the other `is_failure` status; the controls are a
canonical that satisfies its slots and a `type_unknown` slot, which `diff` does
not fail either.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from prompt_regression.cli import main
from prompt_regression.diff import HashEmbedder
from prompt_regression.io import load_snapshot, save_snapshot
from prompt_regression.schema import SnapshotValidationError
from prompt_regression.validate import validate_snapshots

ROOT = Path(__file__).resolve().parent.parent
KITE = ROOT / "examples" / "snapshots" / "creative_kite_v1.yml"


def _kite_with_slots(tmp_path: Path, slots: dict, text: str | None = None) -> Path:
    """The shipped kite snapshot with *slots* (and optionally *text*) swapped in."""
    data = yaml.safe_load(KITE.read_text(encoding="utf-8"))
    data["response_shape"]["structured_slots"] = slots
    if text is not None:
        data["canonical"]["text"] = text
        data["canonical"]["embedding"] = list(HashEmbedder().embed(text))
    d = tmp_path / "snaps"
    d.mkdir()
    path = d / "kite.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _findings(path: Path) -> list[tuple[str, str]]:
    report = validate_snapshots(path.parent)
    return [(f.code, f.reason) for f in report.findings]


def test_a_canonical_missing_its_own_slot_is_a_finding(tmp_path: Path) -> None:
    path = _kite_with_slots(tmp_path, {"line_count": {"type": "integer"}})
    report = validate_snapshots(path.parent)
    assert [f.code for f in report.findings] == ["canonical_slots"]
    assert "line_count: missing" in report.findings[0].reason
    assert report.n_valid == 0
    assert not report.ok


def test_a_canonical_with_the_wrong_type_is_a_finding(tmp_path: Path) -> None:
    # A decimal in an integer slot is a `type_mismatch`, not its last digits (#211).
    path = _kite_with_slots(
        tmp_path,
        {"kites": {"type": "integer", "description": "kites"}},
        text="There were 2.5 kites above the empty beach.",
    )
    (finding,) = _findings(path)
    assert finding[0] == "canonical_slots"
    assert "kites: type_mismatch" in finding[1]


def test_every_failing_slot_is_named(tmp_path: Path) -> None:
    path = _kite_with_slots(
        tmp_path, {"line_count": {"type": "integer"}, "is_rhyming": {"type": "boolean"}}
    )
    (finding,) = _findings(path)
    assert "line_count: missing" in finding[1]
    assert "is_rhyming: missing" in finding[1]


def test_the_cli_exits_one_and_the_json_carries_the_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _kite_with_slots(tmp_path, {"line_count": {"type": "integer"}})
    assert main(["validate", str(path.parent), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert [f["code"] for f in payload["findings"]] == ["canonical_slots"]


def test_the_finding_agrees_with_what_diff_says(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The finding's premise, checked through `diff` rather than restated."""
    path = _kite_with_slots(tmp_path, {"line_count": {"type": "integer"}})
    text = load_snapshot(path).canonical.text
    assert main(["diff", "--snapshot", str(path), "--candidate", text]) == 1
    out = capsys.readouterr().out
    assert "verdict: fail" in out
    assert "line_count: missing" in out


def test_a_duplicate_id_does_not_hide_the_slot_finding(tmp_path: Path) -> None:
    """Checked after the id rather than instead of it: one file, two findings."""
    path = _kite_with_slots(tmp_path, {"line_count": {"type": "integer"}})
    (path.parent / "a_first.yml").write_bytes(KITE.read_bytes())  # same id, sorts first
    report = validate_snapshots(path.parent)
    assert [(f.path, f.code) for f in report.findings] == [
        ("kite.yml", "duplicate_id"),
        ("kite.yml", "canonical_slots"),
    ]
    assert report.n_valid == 1


# --- controls: green before and after ---------------------------------------


def test_control_a_canonical_meeting_its_slots_is_clean(tmp_path: Path) -> None:
    path = _kite_with_slots(
        tmp_path,
        {"kites": {"type": "integer", "description": "kites"}},
        text="There were 3 kites above the empty beach.",
    )
    report = validate_snapshots(path.parent)
    assert report.findings == ()
    assert report.ok


def test_control_a_type_unknown_slot_is_not_a_finding(tmp_path: Path) -> None:
    # `diff` does not fail an array slot (#77), so neither does `validate`.
    path = _kite_with_slots(tmp_path, {"lines": {"type": "array"}})
    assert validate_snapshots(path.parent).ok


def test_control_the_shipped_examples_are_clean() -> None:
    assert validate_snapshots(ROOT / "examples" / "snapshots").ok


# --- the library writer ------------------------------------------------------


def test_save_snapshot_refuses_and_leaves_the_file_untouched(tmp_path: Path) -> None:
    path = _kite_with_slots(tmp_path, {})
    snap = load_snapshot(path)
    before = path.read_bytes()
    snap.response_shape.structured_slots = {"line_count": {"type": "integer"}}
    with pytest.raises(SnapshotValidationError, match="line_count: missing"):
        save_snapshot(snap, path)
    assert path.read_bytes() == before


def test_save_snapshot_refuses_before_creating_a_new_file(tmp_path: Path) -> None:
    snap = load_snapshot(KITE)
    snap.response_shape.structured_slots = {"line_count": {"type": "integer"}}
    dest = tmp_path / "new.yml"
    with pytest.raises(SnapshotValidationError):
        save_snapshot(snap, dest)
    assert not dest.exists()


def test_control_save_snapshot_writes_a_canonical_meeting_its_slots(tmp_path: Path) -> None:
    path = _kite_with_slots(
        tmp_path,
        {"kites": {"type": "integer", "description": "kites"}},
        text="There were 3 kites above the empty beach.",
    )
    snap = load_snapshot(path)
    out = tmp_path / "out.yml"
    save_snapshot(snap, out)
    assert load_snapshot(out) == snap
