"""A 309+ digit integer in a float-converted field is a schema error (#221).

``float()`` of an ``int`` past the double range raises ``OverflowError``
instead of returning ``inf`` — so the finiteness/range checks that reject the
float spelling (``1.0e+400``) never ran, and the raw ``OverflowError`` escaped
every loader seam (they catch ``SnapshotValidationError``): ``validate``,
``stats``, ``diff`` and ``run`` all crashed with a traceback at exit 1.
"""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from prompt_regression import Snapshot, SnapshotValidationError
from prompt_regression.validate import validate_snapshots

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples/snapshots/creative_kite_v1.yml"
_HUGE = 10**400


def _set_tolerance(d: dict[str, Any], v: Any) -> None:
    d["tolerance"] = v


def _set_temperature(d: dict[str, Any], v: Any) -> None:
    d["prompt"]["temperature"] = v


def _set_embedding(d: dict[str, Any], v: Any) -> None:
    d["canonical"]["embedding"][0] = v


_FIELDS = [
    pytest.param(_set_tolerance, "Snapshot.tolerance", id="tolerance"),
    pytest.param(_set_temperature, "Prompt.temperature", id="temperature"),
    pytest.param(_set_embedding, r"CanonicalResponse.embedding\[0\]", id="embedding"),
]


def _base() -> dict[str, Any]:
    return yaml.safe_load(_EXAMPLE.read_text(encoding="utf-8"))


def _write(tmp_path: Path, setter: Any, value: Any) -> Path:
    d = copy.deepcopy(_base())
    setter(d, value)
    snap_dir = tmp_path / "snaps"
    snap_dir.mkdir()
    (snap_dir / "s.yml").write_text(yaml.safe_dump(d), encoding="utf-8")
    return snap_dir


@pytest.mark.parametrize(("setter", "field"), _FIELDS)
def test_huge_int_is_a_schema_error_naming_the_field(setter: Any, field: str) -> None:
    d = _base()
    setter(d, _HUGE)
    with pytest.raises(SnapshotValidationError, match=field):
        Snapshot.from_dict(d)


@pytest.mark.parametrize(("setter", "field"), _FIELDS)
def test_validate_reports_a_schema_finding(tmp_path: Path, setter: Any, field: str) -> None:
    report = validate_snapshots(_write(tmp_path, setter, _HUGE))
    assert [f.code for f in report.findings] == ["schema"]
    assert "too large for a float" in report.findings[0].reason


@pytest.mark.parametrize(("setter", "field"), _FIELDS)
def test_stats_cli_exits_2_not_a_traceback(tmp_path: Path, setter: Any, field: str) -> None:
    snap_dir = _write(tmp_path, setter, _HUGE)
    proc = subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", "stats", str(snap_dir)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, proc.stderr
    assert "Traceback" not in proc.stderr
    assert proc.stderr.startswith("error:")


def test_largest_convertible_int_still_reaches_the_range_check() -> None:
    # Control: a 308-digit int converts to a finite float, so it must still be
    # judged by the existing range rule — the fix only changes the overflow arm.
    d = _base()
    d["tolerance"] = 10**308
    with pytest.raises(SnapshotValidationError, match=r"must be in \(0, 1\]"):
        Snapshot.from_dict(d)


def test_float_spelling_of_the_same_magnitude_was_already_rejected() -> None:
    # Control: the float branch never overflowed; yaml reads 1.0e+400 as inf.
    d = _base()
    d["tolerance"] = yaml.safe_load("v: 1.0e+400")["v"]
    with pytest.raises(SnapshotValidationError, match="Snapshot.tolerance"):
        Snapshot.from_dict(d)
