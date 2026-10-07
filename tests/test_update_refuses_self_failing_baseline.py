"""`update` refuses a canonical that fails the snapshot's own slots (#207).

It saved the new text unchecked: re-baselining `refund_window_v1` with
"Sorry, I don't know the policy." exited 0 and `validate` was clean, but a
diff of that same text against the new baseline failed (cosine 1.0, all three
slots missing). A baseline that cannot pass against itself makes every later
run of that text red.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from prompt_regression.cli import main
from prompt_regression.io import load_snapshot

ROOT = Path(__file__).resolve().parent.parent
REFUND = ROOT / "examples" / "snapshots" / "refund_window_v1.yml"


def _copy(tmp_path: Path) -> Path:
    path = tmp_path / "refund_window_v1.yml"
    shutil.copy(REFUND, path)
    return path


def test_a_canonical_missing_its_slots_is_refused_and_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _copy(tmp_path)
    before = path.read_bytes()
    rc = main(
        [
            "update",
            "--snapshot",
            str(path),
            "--canonical",
            "Sorry, I don't know the policy.",
            "--force",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    for slot in ("refund_days: missing", "plan_name: missing", "eligibility_caveat: missing"):
        assert slot in err
    assert path.read_bytes() == before


def test_a_canonical_meeting_its_slots_updates_and_then_passes_against_itself(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _copy(tmp_path)
    text = "The Pro plan has a 30-day refund window, minus usage fees."
    assert main(["update", "--snapshot", str(path), "--canonical", text, "--force"]) == 0
    assert load_snapshot(path).canonical.text == text
    capsys.readouterr()
    assert main(["diff", "--snapshot", str(path), "--candidate", text]) == 0
    assert "verdict: pass" in capsys.readouterr().out


def test_a_snapshot_without_slots_still_updates(tmp_path: Path) -> None:
    path = _copy(tmp_path)
    snap = load_snapshot(path)
    snap.response_shape.structured_slots = {}
    from prompt_regression.io import save_snapshot

    save_snapshot(snap, path)
    assert (
        main(["update", "--snapshot", str(path), "--canonical", "Anything at all.", "--force"]) == 0
    )
