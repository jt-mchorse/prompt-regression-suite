"""`run --format html` reports what it did not compare (#249).

Measured on `64191f6` with the shipped examples and a candidates file holding
the kite row plus one keyed `renamed_v2.yml`, under `--allow-unmatched-candidates`:

    text:  total=2 failed=0 skipped=1 unmatched=1     exit 0
    html:  1 snapshots · 1 pass · 0 warn · 0 fail      -- no `refund`, no `renamed_v2`

D-010 records the flag as turning off "the failure, not the report". Text and
JSON kept the report (#150); the HTML, the artifact CI uploads, dropped both the
skipped snapshot and the unmatched key, and read as a complete clean run.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from prompt_regression.cli import main
from prompt_regression.html_report import render_report

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
_KITE_ROW = (_EXAMPLES / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0]


def _html(tmp_path: Path, *rows: str) -> tuple[int, str]:
    snaps = tmp_path / "snaps"
    shutil.copytree(_EXAMPLES / "snapshots", snaps)
    cands = tmp_path / "c.jsonl"
    cands.write_text("\n".join([_KITE_ROW, *rows]) + "\n", encoding="utf-8")
    out = tmp_path / "r.html"
    rc = main(
        [
            "run",
            "--snapshots",
            str(snaps),
            "--candidates",
            str(cands),
            "--allow-unmatched-candidates",
            "--format",
            "html",
            "--out",
            str(out),
        ]
    )
    return rc, out.read_text(encoding="utf-8")


def _stats(page: str) -> dict[str, int]:
    return {
        label: int(n)
        for n, label in re.findall(r'<div class="stat \w+"><strong>(\d+)</strong>(\w+)</div>', page)
    }


def test_the_issue_run_reports_the_skipped_snapshot_and_the_unmatched_key(
    tmp_path: Path,
) -> None:
    rc, page = _html(tmp_path, '{"snapshot": "renamed_v2.yml", "candidate": "x"}')
    assert rc == 0
    assert _stats(page) == {
        "snapshots": 1,
        "pass": 1,
        "warn": 0,
        "fail": 0,
        "skipped": 1,
        "unmatched": 1,
    }
    assert "<code>refund-window-pro-v1</code>" in page
    assert "<code>&#x27;renamed_v2.yml&#x27;</code>" in page


def test_skipped_alone_is_reported(tmp_path: Path) -> None:
    # Partial candidates file, no orphan: the ordinary road to `skipped`.
    rc, page = _html(tmp_path)
    assert rc == 0
    assert _stats(page)["skipped"] == 1
    assert "unmatched" not in _stats(page)
    assert "<code>refund-window-pro-v1</code>" in page


def test_a_key_is_escaped(tmp_path: Path) -> None:
    _, page = _html(tmp_path, '{"snapshot": "<b>x</b>.yml", "candidate": "x"}')
    assert "<b>x</b>" not in page
    assert "&lt;b&gt;x&lt;/b&gt;" in page


def test_a_run_with_nothing_left_out_renders_exactly_as_before() -> None:
    # The stats and lists appear only when non-empty, like #71's `error` stat.
    assert render_report([], skipped=(), unmatched=()) == render_report([])
    assert 'class="stat skipped"' not in render_report([])
