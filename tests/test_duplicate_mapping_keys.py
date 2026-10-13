"""A key repeated in one mapping is refused, not resolved last-wins (#243).

PyYAML's `safe_load` and `json.loads` both keep the last of two equal keys
without a word. A snapshot with a second `tolerance:` line passed `validate`
clean and `run` diffed against whichever came last (pass at exit 0 against a
tolerance the other line contradicts); a candidates row with two `candidate`
keys diffed whichever came last.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest
import yaml

from prompt_regression import io as prs_io
from prompt_regression.cli import _load_candidates, main

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"
KITE = EXAMPLES / "snapshots" / "creative_kite_v1.yml"
KITE_HEAD = "id: creative-kite-poem-v1\n"


def _kite_with(tmp_path: Path, insert: str) -> Path:
    src = KITE.read_text(encoding="utf-8")
    assert src.startswith(KITE_HEAD)  # anti-vacuity: the insertion point exists
    d = tmp_path / "snaps"
    d.mkdir()
    (d / KITE.name).write_text(src.replace(KITE_HEAD, KITE_HEAD + insert, 1), encoding="utf-8")
    return d


def _kite_row() -> dict:
    row = json.loads((EXAMPLES / "candidates.jsonl").read_text(encoding="utf-8").split("\n")[0])
    assert row["snapshot"] == KITE.name
    return row


def test_validate_reports_a_repeated_top_level_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "\ntolerance: 0.75" in KITE.read_text(encoding="utf-8")  # the other copy
    d = _kite_with(tmp_path, "tolerance: 0.95\n")
    rc = main(["validate", str(d)])
    out = capsys.readouterr()
    assert rc == 1
    assert "[parse]" in out.out + out.err
    assert "duplicate key 'tolerance'" in out.out + out.err


def test_run_refuses_the_snapshot_instead_of_passing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = _kite_with(tmp_path, "tolerance: 0.95\n")
    cands = tmp_path / "c.jsonl"
    cands.write_text(json.dumps(_kite_row()) + "\n", encoding="utf-8")
    rc = main(["run", "--snapshots", str(d), "--candidates", str(cands)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "duplicate key 'tolerance'" in err


def test_a_nested_repeated_key_is_refused() -> None:
    text = "slots:\n  days:\n    type: integer\n  days:\n    type: string\n"
    with pytest.raises(yaml.YAMLError, match="duplicate key 'days'"):
        prs_io.safe_load_yaml(io.StringIO(text))


def test_a_merge_key_override_still_loads() -> None:
    text = "base: &b {type: integer, description: d}\nslot:\n  <<: *b\n  type: string\n"
    data = prs_io.safe_load_yaml(io.StringIO(text))
    assert data["slot"] == {"type": "string", "description": "d"}


@pytest.mark.parametrize("path", sorted((EXAMPLES / "snapshots").glob("*.yml")), ids=str)
def test_the_shipped_snapshots_still_load(path: Path) -> None:
    prs_io.load_snapshot(path)


def test_a_candidates_row_with_two_candidate_keys_is_refused(tmp_path: Path) -> None:
    row = _kite_row()
    line = json.dumps(row)[:-1] + ', "candidate": "kite"}'
    assert json.loads(line)["candidate"] == "kite"  # anti-vacuity: last-wins by default
    path = tmp_path / "c.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"c\.jsonl:1: invalid JSON: duplicate key 'candidate'"):
        _load_candidates(path)


def test_the_shipped_candidates_still_load(tmp_path: Path) -> None:
    shutil.copy(EXAMPLES / "candidates.jsonl", tmp_path / "c.jsonl")
    assert len(_load_candidates(tmp_path / "c.jsonl")) == 2
