"""An unquoted `created_at` loads (#209), the sibling of #75's `schema_version`.

YAML's safe loader reads `created_at: 2026-05-18T16:10:00Z` as a `datetime`,
and `Snapshot.from_dict`'s `_require_str` refused the whole snapshot. Measured
on `main` with the shipped `creative_kite_v1.yml`, `created_at` unquoted:

    prompt-snap validate   -> kite.yml [schema]: Snapshot.created_at must be a
                              string, got datetime   (exit 1)

`docs/schema.md` documents the field as an ISO-8601 UTC string, and a
hand-authored snapshot (the D-003 use case) naturally leaves it unquoted.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from prompt_regression.io import load_snapshot, save_snapshot
from prompt_regression.schema import SnapshotValidationError

KITE = Path(__file__).resolve().parents[1] / "examples" / "snapshots" / "creative_kite_v1.yml"


def _with_created_at(tmp_path: Path, line: str) -> Path:
    text = KITE.read_text(encoding="utf-8")
    text, n = re.subn(r"(?m)^created_at: .*$", line, text)
    assert n == 1
    p = tmp_path / "kite.yml"
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("created_at: 2026-05-18T16:10:00Z", "2026-05-18T16:10:00Z"),
        ("created_at: 2026-05-18T18:10:00+02:00", "2026-05-18T16:10:00Z"),
        ("created_at: 2026-05-18 16:10:00", "2026-05-18T16:10:00Z"),  # YAML: no zone = UTC
        ("created_at: 2026-05-18T16:10:00.5Z", "2026-05-18T16:10:00.500000Z"),
        ("created_at: 2026-05-18", "2026-05-18"),
        ("created_at: '2026-05-18T16:10:00Z'", "2026-05-18T16:10:00Z"),  # control: quoted
    ],
)
def test_an_unquoted_timestamp_loads_as_its_utc_string(
    tmp_path: Path, line: str, expected: str
) -> None:
    assert load_snapshot(_with_created_at(tmp_path, line)).created_at == expected


def test_a_non_timestamp_is_still_refused(tmp_path: Path) -> None:
    with pytest.raises(SnapshotValidationError, match="created_at must be a string"):
        load_snapshot(_with_created_at(tmp_path, "created_at: 5"))


def test_the_normalized_value_round_trips_through_save(tmp_path: Path) -> None:
    snap = load_snapshot(_with_created_at(tmp_path, "created_at: 2026-05-18T16:10:00Z"))
    out = tmp_path / "saved.yml"
    save_snapshot(snap, out)
    assert load_snapshot(out).created_at == "2026-05-18T16:10:00Z"
    assert "created_at: '2026-05-18T16:10:00Z'" in out.read_text(encoding="utf-8")


def test_the_cli_validates_a_hand_authored_snapshot(tmp_path: Path) -> None:
    _with_created_at(tmp_path, "created_at: 2026-05-18T16:10:00Z")
    proc = subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", "validate", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "valid=1" in proc.stdout
