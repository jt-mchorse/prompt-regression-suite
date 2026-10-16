"""An unknown top-level snapshot key is a schema error, as a nested one is (#261).

`Snapshot.from_dict` builds the three sections with `Section(**data[...])`, so
an unknown key inside `prompt`, `response_shape` or `canonical` was already
refused by the dataclass `__init__`. The top level is read key-by-key with
`data.get(...)`, and nothing looked at what was left over -- so an unknown key
there was dropped. The top level is where `tolerance` lives, the one optional
field that moves the gate. Measured on the shipped kite example with its
`tolerance: 0.75` line respelled, run at `--threshold 0.8`:

    tolerance: 0.95     fail 0.806 (per-snapshot tolerance 0.950 ...)   rc 1
    tolerence: 0.95     pass 0.806                                      rc 0   <--

and `prompt-snap validate` reported the typo'd file `ok`.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from prompt_regression import Snapshot, load_snapshot, save_snapshot
from prompt_regression.schema import SnapshotValidationError
from prompt_regression.validate import validate_snapshots

REPO_ROOT = Path(__file__).resolve().parent.parent
KITE = REPO_ROOT / "examples" / "snapshots" / "creative_kite_v1.yml"
CANDIDATES = REPO_ROOT / "examples" / "candidates.jsonl"

_BASE: dict = {
    "id": "s1",
    "prompt": {"model": "m", "user": "hi"},
    "response_shape": {"semantic_categories": ["greeting"]},
    "canonical": {
        "text": "hello",
        "embedding": [0.6, 0.8],
        "embedding_model": "test-embedder",
    },
}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _kite_with(tmp_path: Path, tolerance_line: str) -> Path:
    """The shipped kite snapshot with its tolerance line replaced, plus its
    one candidate row, in a fresh dir. Returns the candidates path."""
    text = KITE.read_text(encoding="utf-8")
    assert "\ntolerance: 0.75\n" in text  # anti-vacuous: the line we rewrite exists
    snaps = tmp_path / "snapshots"
    snaps.mkdir()
    (snaps / KITE.name).write_text(
        text.replace("\ntolerance: 0.75\n", f"\n{tolerance_line}\n"), encoding="utf-8"
    )
    kite_row = next(
        line
        for line in CANDIDATES.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("snapshot") == KITE.name
    )
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text(kite_row + "\n", encoding="utf-8")
    return candidates


def test_correctly_spelled_tolerance_fails_the_kite_at_threshold_0_8(tmp_path: Path) -> None:
    """Control: the bar the typo was meant to set really does fail this row,
    so a green typo'd run below is the dropped key and not the candidate."""
    candidates = _kite_with(tmp_path, "tolerance: 0.95")
    proc = _run(
        "run",
        "--snapshots",
        str(tmp_path / "snapshots"),
        "--candidates",
        str(candidates),
        "--threshold",
        "0.8",
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "per-snapshot tolerance 0.950" in proc.stdout


def test_a_typod_tolerance_is_refused_by_run_at_exit_2(tmp_path: Path) -> None:
    candidates = _kite_with(tmp_path, "tolerence: 0.95")
    proc = _run(
        "run",
        "--snapshots",
        str(tmp_path / "snapshots"),
        "--candidates",
        str(candidates),
        "--threshold",
        "0.8",
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "'tolerence'" in proc.stderr


def test_a_typod_tolerance_is_a_schema_finding_in_validate(tmp_path: Path) -> None:
    _kite_with(tmp_path, "tolerence: 0.95")
    report = validate_snapshots(tmp_path / "snapshots")
    assert report.n_valid == 0
    assert [f.code for f in report.findings] == ["schema"]
    assert "'tolerence'" in report.findings[0].reason


def test_validate_cli_exits_nonzero_on_the_typo(tmp_path: Path) -> None:
    _kite_with(tmp_path, "tolerence: 0.95")
    proc = _run("validate", str(tmp_path / "snapshots"))
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "tolerence" in proc.stdout + proc.stderr


@pytest.mark.parametrize("key", ["tolerence", "Tolerance", "note", "embedding_model", "bogus"])
def test_from_dict_names_every_unknown_top_level_key(key: str) -> None:
    data = {**copy.deepcopy(_BASE), key: 0.9}
    with pytest.raises(SnapshotValidationError, match=f"top-level fields: {key!r}"):
        Snapshot.from_dict(data)


def test_several_unknown_keys_are_all_named() -> None:
    data = {**copy.deepcopy(_BASE), "tolerence": 0.9, "nots": "x"}
    with pytest.raises(SnapshotValidationError) as exc:
        Snapshot.from_dict(data)
    assert "'tolerence'" in str(exc.value)
    assert "'nots'" in str(exc.value)


def test_a_non_string_top_level_key_is_refused_not_a_crash() -> None:
    """YAML happily produces `1: x` or `true: x` as an int/bool key."""
    data = {**copy.deepcopy(_BASE), 1: "x"}
    with pytest.raises(SnapshotValidationError, match="top-level fields: 1"):
        Snapshot.from_dict(data)


def test_every_known_key_still_loads() -> None:
    """The neighbouring wrong fix -- an allow-list typed out by hand -- would
    drop one of the optional keys. Set all eight."""
    data = {
        **copy.deepcopy(_BASE),
        "schema_version": "1",
        "created_at": "2026-01-01T00:00:00Z",
        "notes": "n",
        "tolerance": 0.9,
    }
    s = Snapshot.from_dict(data)
    assert (s.notes, s.tolerance, s.created_at) == ("n", 0.9, "2026-01-01T00:00:00Z")


def test_what_the_writer_emits_the_reader_accepts(tmp_path: Path) -> None:
    """Read path no stricter than the write path: `save_snapshot` of a
    snapshot with every optional field set must load back equal."""
    s = Snapshot.from_dict({**copy.deepcopy(_BASE), "notes": "n", "tolerance": 0.9})
    assert set(s.to_dict()) == {
        "id",
        "prompt",
        "response_shape",
        "canonical",
        "schema_version",
        "created_at",
        "notes",
        "tolerance",
    }
    path = save_snapshot(s, tmp_path / "s.yml")
    assert load_snapshot(path) == s


def test_the_shipped_examples_still_load() -> None:
    for path in sorted((REPO_ROOT / "examples" / "snapshots").glob("*.yml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        load_snapshot(path)


def test_schema_doc_top_level_table_lists_every_field() -> None:
    """docs/schema.md's table is the list an author checks a key against; it
    omitted `tolerance`, the key this issue is about."""
    from dataclasses import fields

    doc = (REPO_ROOT / "docs" / "schema.md").read_text(encoding="utf-8")
    section = doc.split("## Top-level fields", 1)[1].split("\n## ", 1)[0]
    rows = {
        line.split("|")[1].strip().strip("`")
        for line in section.splitlines()
        if line.startswith("| `")
    }
    assert rows == {f.name for f in fields(Snapshot)}
