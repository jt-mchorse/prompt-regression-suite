"""Two candidate rows naming one snapshot, by path and by id, are refused (#237).

`_load_candidates` refuses the same key twice. A row keyed by a snapshot's path
and another keyed by its id name one snapshot through its two spellings; `run`
used the path row, so the id row was reported "matched no snapshot" (false),
and under --allow-unmatched-candidates its candidate was never compared and the
run exited 0.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from prompt_regression.cli import main

_EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "snapshots"
_PASSING = "The Pro plan has a 14-day refund window from the original purchase date."


def _snapshots(tmp_path: Path) -> Path:
    d = tmp_path / "snaps"
    d.mkdir()
    for p in _EXAMPLES.glob("*.yml"):
        shutil.copy(p, d / p.name)
    return d


def _candidates(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    p = tmp_path / "c.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


@pytest.mark.parametrize("flag", [[], ["--allow-unmatched-candidates"]], ids=["strict", "allow"])
def test_a_snapshot_keyed_by_path_and_by_id_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flag: list[str]
) -> None:
    snaps = _snapshots(tmp_path)
    cands = _candidates(
        tmp_path,
        [
            {"snapshot": "refund_window_v1.yml", "candidate": _PASSING},
            {"snapshot": "refund-window-pro-v1", "candidate": "I cannot help with refunds."},
        ],
    )
    rc = main(["run", "--snapshots", str(snaps), "--candidates", str(cands), *flag])
    out = capsys.readouterr()
    assert rc == 2
    assert "'refund_window_v1.yml'" in out.err
    assert "'refund-window-pro-v1'" in out.err
    assert "matched no snapshot" not in out.err + out.out
    assert "verdict" not in out.out  # no table


@pytest.mark.parametrize(
    "key", ["refund_window_v1.yml", "refund-window-pro-v1"], ids=["path", "id"]
)
def test_one_row_by_either_key_still_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], key: str
) -> None:
    snaps = _snapshots(tmp_path)
    cands = _candidates(tmp_path, [{"snapshot": key, "candidate": _PASSING}])
    rc = main(["run", "--snapshots", str(snaps), "--candidates", str(cands)])
    assert rc in (0, 1)  # compared; the verdict is the diff's business
    assert "refund_window_v1.yml" in capsys.readouterr().out


def test_a_true_orphan_is_still_only_reported_under_the_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snaps = _snapshots(tmp_path)
    cands = _candidates(
        tmp_path,
        [
            {"snapshot": "refund_window_v1.yml", "candidate": _PASSING},
            {"snapshot": "no-such-snapshot", "candidate": "x"},
        ],
    )
    rc = main(
        [
            "run",
            "--snapshots",
            str(snaps),
            "--candidates",
            str(cands),
            "--allow-unmatched-candidates",
        ]
    )
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert "'no-such-snapshot' matched no snapshot" in out
