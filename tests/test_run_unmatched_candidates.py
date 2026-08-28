"""A candidates file that matches nothing must not exit 0 (#150, D-010).

`prompt-snap run` derived its exit code from `failed` alone, and a candidate
row whose key matched no snapshot was dropped with no note, no count and no
diagnostic. So a candidates file keyed by absolute path, or by a since-renamed
`snapshot.id`, or with a typo, produced a clean-looking report and a green CI
step having verified nothing. Measured on the shipped `examples/`, changing
only the two keys:

    candidates file                     first line of output                exit
    correct (control)                   total=2 failed=1 skipped=0            1
    zero rows                           error: no candidate rows loaded       2
    2 rows, neither key matches         total=2 failed=0 skipped=2            0   <--
    2 rows, one key matches             total=2 failed=0 skipped=1            0   <--

`_load_candidates` already refused the zero-rows file, because "a run with
nothing to check is meaningless". A file with rows that all miss reaches the
identical state by a quieter road. And the lookup's own comment names this
harm for the neighbouring case where the candidate *value* is empty:
"silently skips it, letting the worst regression pass CI green."

This file used to close by saying there was deliberately no separate
`skipped == total` rule. That was true of the world without
`--allow-unmatched-candidates`, which the same change introduced -- see
`tests/test_run_nothing_compared.py` (#153), which measures the third road to
the same state and closes it. The partial-file test below is unchanged: its
assertions were always right, only the reason attached to them was too broad.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = REPO_ROOT / "examples" / "snapshots"
CANDIDATES = REPO_ROOT / "examples" / "candidates.jsonl"

# The two keys the shipped candidates file uses, one per documented convention.
KITE_KEY = "creative_kite_v1.yml"  # relative path
REFUND_KEY = "refund-window-pro-v1"  # snapshot.id


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _run_with(candidates: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run(
        "run",
        "--snapshots",
        str(SNAPSHOTS),
        "--candidates",
        str(candidates),
        *extra,
    )


def _rewrite(tmp_path: Path, replacements: dict[str, str]) -> Path:
    text = CANDIDATES.read_text(encoding="utf-8")
    for old, new in replacements.items():
        assert old in text, f"{old!r} is no longer in examples/candidates.jsonl"
        text = text.replace(old, new)
    p = tmp_path / "candidates.jsonl"
    p.write_text(text, encoding="utf-8")
    return p


def test_the_control_still_exits_1() -> None:
    """Without this, a change that failed *every* run would pass every case below."""
    proc = _run_with(CANDIDATES)
    assert proc.returncode == 1, proc.stderr
    assert "unmatched=0" in proc.stdout


def test_every_key_unmatched_exits_2_and_names_the_keys(tmp_path: Path) -> None:
    bad = _rewrite(
        tmp_path,
        {KITE_KEY: "creative_kite_v1.YML.typo", REFUND_KEY: "refund-window-pro-v1-TYPO"},
    )
    proc = _run_with(bad)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "creative_kite_v1.YML.typo" in proc.stderr
    assert "refund-window-pro-v1-TYPO" in proc.stderr
    # Named, not merely counted: "2 rows matched nothing" is not actionable.
    assert "matched no snapshot" in proc.stderr


def test_one_key_unmatched_also_exits_2(tmp_path: Path) -> None:
    """The half-broken file is the likelier real case — one snapshot renamed —
    and it is the one that most looks fine in the report."""
    bad = _rewrite(tmp_path, {REFUND_KEY: "refund-window-pro-v1-TYPO"})
    proc = _run_with(bad)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "refund-window-pro-v1-TYPO" in proc.stderr
    assert "creative_kite_v1" not in proc.stderr, "the matched key must not be listed"


def test_allow_flag_reports_without_failing(tmp_path: Path) -> None:
    """The flag turns off the failure, not the report.

    CHANGED in #153, and it is the one pre-existing assertion that change moves.
    This used to typo BOTH keys and assert exit 0 — which is precisely the hole
    #153 closes: with every key orphaned, nothing is compared, and a run that
    compared nothing must not be green whatever the flag says. The all-orphan
    case now exits 2, pinned in `tests/test_run_nothing_compared.py`.

    The property this test was written for is untouched and is asserted here on
    the shape that actually has it: one key orphaned, one matching, so the orphan
    is *reported* and the run still checks something.
    """
    bad = _rewrite(tmp_path, {REFUND_KEY: "refund-window-pro-v1-TYPO"})
    proc = _run_with(bad, "--allow-unmatched-candidates")
    assert proc.returncode == 0, proc.stderr
    assert "unmatched=1" in proc.stdout
    assert "skipped=1" in proc.stdout
    # Still visible, just not fatal — the flag turns off the failure, not the report.
    assert "refund-window-pro-v1-TYPO" in proc.stdout


def test_json_output_carries_the_keys_not_just_a_count(tmp_path: Path) -> None:
    bad = _rewrite(tmp_path, {REFUND_KEY: "refund-window-pro-v1-TYPO"})
    proc = _run_with(bad, "--allow-unmatched-candidates", "--format", "json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["unmatched_candidates"] == ["refund-window-pro-v1-TYPO"]
    assert payload["skipped"] == 1


def test_a_partial_candidates_file_is_still_green(tmp_path: Path) -> None:
    """The workflow a `skipped == total` rule must not break.

    A candidates file covering only *some* snapshots has `skipped > 0` and zero
    orphans — a legitimate workflow, and `skipped < total` by definition, so the
    rule added in #153 cannot fire here. This test predates that rule and its
    assertions are unchanged; what changed is the claim that used to be attached
    to them, that no such rule could ever be needed. See
    `tests/test_run_nothing_compared.py`.
    """
    only_kite = tmp_path / "candidates.jsonl"
    lines = [
        line
        for line in CANDIDATES.read_text(encoding="utf-8").splitlines()
        if REFUND_KEY not in line
    ]
    assert len(lines) == 1, "expected exactly one row to survive the filter"
    only_kite.write_text("\n".join(lines) + "\n", encoding="utf-8")

    proc = _run_with(only_kite)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "skipped=1" in proc.stdout
    assert "unmatched=0" in proc.stdout


def test_a_zero_row_candidates_file_is_unchanged(tmp_path: Path) -> None:
    """The guard this one generalizes must keep its own message and exit code."""
    empty = tmp_path / "candidates.jsonl"
    empty.write_text("", encoding="utf-8")
    proc = _run_with(empty)
    assert proc.returncode == 2
    assert "no candidate rows loaded" in proc.stderr


def test_two_rows_keyed_at_the_same_snapshot_are_caught(tmp_path: Path) -> None:
    """The ambiguity the orphan rule newly catches.

    The relative path wins over the id, so a file carrying both keys for one
    snapshot silently discarded the id-keyed row's candidate — including when
    the two rows disagreed about what the model returned.
    """
    both = tmp_path / "candidates.jsonl"
    both.write_text(
        json.dumps({"snapshot": KITE_KEY, "candidate": "one"})
        + "\n"
        + json.dumps({"id": "creative-kite-poem-v1", "candidate": "a DIFFERENT response"})
        + "\n",
        encoding="utf-8",
    )
    proc = _run_with(both)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "creative-kite-poem-v1" in proc.stderr


@pytest.mark.parametrize(
    ("row", "fragment"),
    [
        ('{"snapshot": "", "id": "creative-kite-poem-v1", "candidate": "x"}', "non-empty"),
        ('{"snapshot": "", "candidate": "x"}', "non-empty"),
        ('{"id": "", "candidate": "x"}', "non-empty"),
    ],
    ids=["empty-snapshot-with-id", "empty-snapshot-only", "empty-id"],
)
def test_an_empty_key_is_rejected_not_re_keyed(tmp_path: Path, row: str, fragment: str) -> None:
    """`row.get("snapshot") or row.get("id")` could not tell absent from
    present-and-falsy, so a row carrying `"snapshot": ""` was silently re-keyed
    by `id`. That is the shape the lookup's own comment argues against."""
    p = tmp_path / "candidates.jsonl"
    p.write_text(row + "\n", encoding="utf-8")
    proc = _run_with(p)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert fragment in proc.stderr
