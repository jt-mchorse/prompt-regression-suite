"""STAGE 3 claims what its output shows, and only a failing verdict passes (#205).

The banner said ``--threshold 0.9 (benign drift → fail)`` and a comment said
0.9 flipped the verdict from ``pass`` to ``fail``. The kite snapshot carries
``tolerance: 0.75``, which overrides ``--threshold`` (#6), and the candidate is
a rewrite at cosine ~0.04: the verdict was ``fail`` with or without the flag,
and the notes line printed under the banner said so. Separately, the stage
accepted every non-negative exit code, so a diff that never produced a verdict
(exit 2, a missing snapshot) printed "that's the demo" and the capture exited 0.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from tests.test_capture_demo_smoke import _load_capture_module


def _diff_json(capture_demo, *extra: str) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "prompt_regression.cli",
        "diff",
        "--snapshot",
        str(capture_demo.REPO_ROOT / capture_demo.STAGE3_SNAPSHOT_REL),
        "--candidate",
        capture_demo.STAGE3_CANDIDATE_TEXT,
        *extra,
        "--format",
        "json",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    return json.loads(r.stdout)


def _run(capture_demo, tmp_path: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = capture_demo.main(["--pause-seconds", "0", "--no-open", "--output-dir", str(tmp_path)])
    return rc, out.getvalue(), err.getvalue()


def test_the_threshold_flag_changes_nothing_the_tolerance_decides() -> None:
    capture_demo = _load_capture_module()
    with_flag = _diff_json(capture_demo, "--threshold", capture_demo.STAGE3_THRESHOLD)
    without = _diff_json(capture_demo)
    assert with_flag["verdict"] == without["verdict"] == "fail"
    assert with_flag["threshold"] == without["threshold"] == 0.75
    assert any("overrides run threshold 0.900" in n for n in with_flag["notes"])


def test_the_banner_says_the_tolerance_overrides_the_flag(tmp_path: Path) -> None:
    capture_demo = _load_capture_module()
    rc, out, _ = _run(capture_demo, tmp_path)
    assert rc == 0
    banner = next(line for line in out.splitlines() if "STAGE 3" in line)
    assert "overrides --threshold 0.9" in banner
    for claim in ("benign", "→ fail", "flips"):
        assert claim not in banner


@pytest.mark.parametrize(
    ("attr", "value", "code"),
    [
        pytest.param(
            "STAGE3_SNAPSHOT_REL",
            "examples/snapshots/does_not_exist.yml",
            2,
            id="no-verdict-exit-2",
        ),
        pytest.param(
            "STAGE3_CANDIDATE_TEXT",
            "A kite drifts above an empty beach in the late afternoon. Salt wind tugs the "
            "string, and a child below laughs and tugs back. The horizon is a thin line of "
            "orange, almost gone.",
            0,
            id="a-pass-exit-0",
        ),
    ],
)
def test_anything_but_a_failing_verdict_aborts_the_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attr: str, value: str, code: int
) -> None:
    capture_demo = _load_capture_module()
    monkeypatch.setattr(capture_demo, attr, value)
    rc, out, err = _run(capture_demo, tmp_path)
    assert rc == 1
    assert f"did not produce a failing verdict (prompt-snap diff exit {code})" in err
    assert "that's the demo" not in out
