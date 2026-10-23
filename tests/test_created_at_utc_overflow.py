"""A tz-aware `created_at` with no UTC form is a finding, not a crash (#291).

#209 normalized an unquoted `created_at` timestamp to its UTC string with
`astimezone(UTC)`. At either end of the year range that conversion leaves the
range -- `9999-12-31T23:00:00-05:00` is in year 10000 in UTC, and
`0001-01-01T00:30:00+01:00` in year 0 -- and raises `OverflowError`, which no
read seam caught. Measured on `main` (dd8b17e):

    prompt-snap validate d -> Traceback ... OverflowError: date value out of range
                              (exit 1; the valid sibling file is never reported)

and `stats`, `diff --snapshot` and `run --snapshots` the same way. The #223
class (an impossible YAML date escaping the read paths) in the code #209 added.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from prompt_regression.io import load_snapshot
from prompt_regression.schema import SnapshotValidationError

KITE = Path(__file__).resolve().parents[1] / "examples" / "snapshots" / "creative_kite_v1.yml"

# Both ends of the range: one converts forward past year 9999, one back past 1.
OUT_OF_RANGE = [
    "9999-12-31T23:00:00-05:00",
    "0001-01-01T00:30:00+01:00",
]


def _kite_text(created_at: str) -> str:
    text, n = re.subn(r"(?m)^created_at: .*$", f"created_at: {created_at}", KITE.read_text("utf-8"))
    assert n == 1
    return text


def _write(path: Path, created_at: str) -> Path:
    path.write_text(_kite_text(created_at), encoding="utf-8")
    return path


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("created_at", OUT_OF_RANGE)
def test_load_snapshot_refuses_it_as_a_validation_error(tmp_path: Path, created_at: str) -> None:
    with pytest.raises(SnapshotValidationError, match=re.escape(created_at)) as info:
        load_snapshot(_write(tmp_path / "a.yml", created_at))
    assert "Snapshot.created_at" in str(info.value)


@pytest.mark.parametrize("created_at", OUT_OF_RANGE)
def test_validate_reports_it_and_still_reports_the_sibling(tmp_path: Path, created_at: str) -> None:
    _write(tmp_path / "a.yml", created_at)
    _write(tmp_path / "b.yml", "2026-05-18T16:10:00Z")
    proc = _cli("validate", str(tmp_path))
    assert "Traceback" not in proc.stderr, proc.stderr
    # 1 is `validate`'s documented "findings" code; the report is complete.
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert re.search(r"(?m)^a\.yml \[schema\]: Snapshot\.created_at ", proc.stderr), proc.stderr
    assert "files=2 valid=1 findings=1" in proc.stdout


@pytest.mark.parametrize("created_at", OUT_OF_RANGE)
def test_diff_exits_2(tmp_path: Path, created_at: str) -> None:
    snap = _write(tmp_path / "a.yml", created_at)
    proc = _cli("diff", "--snapshot", str(snap), "--candidate", "a kite")
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Snapshot.created_at" in proc.stderr


@pytest.mark.parametrize("created_at", OUT_OF_RANGE)
def test_stats_exits_2(tmp_path: Path, created_at: str) -> None:
    _write(tmp_path / "a.yml", created_at)
    proc = _cli("stats", str(tmp_path))
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.returncode == 2, proc.stdout + proc.stderr


@pytest.mark.parametrize("created_at", OUT_OF_RANGE)
def test_run_exits_2(tmp_path: Path, created_at: str) -> None:
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    _write(snaps / "a.yml", created_at)
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text(
        json.dumps({"snapshot": "a.yml", "candidate": "a kite"}) + "\n", encoding="utf-8"
    )
    proc = _cli("run", "--snapshots", str(snaps), "--candidates", str(candidates))
    assert "Traceback" not in proc.stderr, proc.stderr
    # `run` aborts on the first unloadable snapshot by design; the abort is exit 2.
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Snapshot.created_at" in proc.stderr


# Controls: an ordinary offset, and the range edges whose conversion stays in
# range, still normalize to their UTC string as #209 shipped.
@pytest.mark.parametrize(
    ("created_at", "expected"),
    [
        ("2026-05-18T18:10:00+02:00", "2026-05-18T16:10:00Z"),
        ("9999-12-31T23:00:00+05:00", "9999-12-31T18:00:00Z"),
        ("0001-01-01T00:30:00-01:00", "0001-01-01T01:30:00Z"),
        ("9999-12-31T23:59:59Z", "9999-12-31T23:59:59Z"),
    ],
)
def test_an_in_range_offset_still_loads(tmp_path: Path, created_at: str, expected: str) -> None:
    assert load_snapshot(_write(tmp_path / "a.yml", created_at)).created_at == expected
