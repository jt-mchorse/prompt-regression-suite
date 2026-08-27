"""A run that compared nothing must not exit 0 -- including under the flag (#153).

`#150` (D-010) closed the road where a candidates file's keys all missed: that
reaches the same "nothing was checked" state as the zero-row file
`_load_candidates` already refuses, so it exits 2. The same change added
`--allow-unmatched-candidates` for one legitimate workflow -- a single candidates
file shared across several snapshot directories -- and that flag exists precisely
to turn the orphan rule off.

So the comment in `#150` that declined a separate `skipped == total` rule, on the
grounds that "the only other way to reach `skipped == total` is an all-orphan
file, which this catches", was true of every branch except the one the same
change created. With the flag, the orphan rule deliberately does not fire, and a
`skipped == total` rule is not redundant -- it is the only rule.

Measured on the shipped `examples/`, changing only the candidate keys and the
flag::

    case                                              exit   summary
    control, no flag                                    1    skipped=0 unmatched=0
    ALL keys orphaned, no flag                          2    (orphan rule)
    ALL keys orphaned, --allow-unmatched-candidates     0    skipped=2 of 2      <--
    control, --allow-unmatched-candidates               1    skipped=0 unmatched=0
    PARTIAL (1 of 2 snapshots), no flag                 0    skipped=1 of 2

Row three compared not one snapshot against anything and exited green.

The table below is one grid rather than a set of one-off tests, and the rows that
must stay **green** are as load-bearing as the row that must go red: closing a
false-accept by failing everything would be a worse tool, and the false-positive
risk is exactly what `#150` was worried about when it declined the rule.
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

FLAG = "--allow-unmatched-candidates"


def _rows() -> list[dict]:
    return [
        json.loads(line)
        for line in CANDIDATES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _key_field(row: dict) -> str:
    """The shipped file uses both documented conventions -- a relative path under
    `"snapshot"` and a `snapshot.id` under `"id"`. Orphaning a row means breaking
    whichever one it uses, not assuming a field name."""
    return "snapshot" if "snapshot" in row else "id"


def _write(tmp_path: Path, name: str, rows: list[dict]) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def _run(candidates: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "prompt_regression.cli",
            "run",
            "--snapshots",
            str(SNAPSHOTS),
            "--candidates",
            str(candidates),
            *extra,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    rows = _rows()
    assert len(rows) == 2, "the grid below assumes the shipped two-row example"

    def orphaned(row: dict) -> dict:
        out = dict(row)
        field = _key_field(row)
        out[field] = "typo-" + str(out[field])
        return out

    return {
        "control": _write(tmp_path, "control.jsonl", rows),
        "all_orphan": _write(tmp_path, "all_orphan.jsonl", [orphaned(r) for r in rows]),
        "partial": _write(tmp_path, "partial.jsonl", rows[:1]),
        # One real key + one orphan: the shared-file workflow the flag exists for.
        "one_matches": _write(tmp_path, "one_matches.jsonl", [rows[0], orphaned(rows[1])]),
    }


# (file, extra args, expected exit, a fragment that must appear somewhere)
GRID = [
    ("control", (), 1, "skipped=0"),
    ("control", (FLAG,), 1, "skipped=0"),
    ("all_orphan", (), 2, "matched no snapshot"),
    ("all_orphan", (FLAG,), 2, "the run checked nothing"),
    ("partial", (), 0, "skipped=1"),
    ("partial", (FLAG,), 0, "skipped=1"),
    ("one_matches", (FLAG,), 0, "skipped=1"),
]


@pytest.mark.parametrize(
    ("name", "extra", "expected_exit", "fragment"),
    GRID,
    ids=[f"{n}{'-flag' if e else ''}" for n, e, _x, _f in GRID],
)
def test_exit_code_grid(
    files: dict[str, Path], name: str, extra: tuple[str, ...], expected_exit: int, fragment: str
) -> None:
    proc = _run(files[name], *extra)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == expected_exit, combined
    assert fragment in combined, combined


def test_the_flag_cannot_switch_off_the_nothing_compared_rule(files: dict[str, Path]) -> None:
    """The row the fix exists for, stated on its own.

    `--allow-unmatched-candidates` turns off the *orphan* rule by design. This is
    the rule it must not be able to turn off: a run that compared zero snapshots
    is meaningless whatever the reason, which is the same argument
    `_load_candidates` makes when it refuses a zero-row file.
    """
    proc = _run(files["all_orphan"], FLAG)
    assert proc.returncode == 2
    assert "total=2 skipped=2" in proc.stderr
    assert "the run checked nothing" in proc.stderr
    # The diagnostic has to say what to do about it, not just that it happened.
    assert "--snapshots" in proc.stderr


def test_the_orphan_rule_still_fires_first_without_the_flag(files: dict[str, Path]) -> None:
    """Both rules apply to the no-flag all-orphan file, and the orphan rule's
    message is the better one there because it lists the offending keys. Order
    matters, so it is pinned."""
    proc = _run(files["all_orphan"])
    assert proc.returncode == 2
    assert "matched no snapshot" in proc.stderr
    assert "the run checked nothing" not in proc.stderr


def test_the_shared_file_workflow_the_flag_exists_for_stays_green(
    files: dict[str, Path],
) -> None:
    """The flag's own help names this case: "a single candidates file shared
    across several snapshot directories". Pointed at a directory where *some*
    rows match, it must keep working: the orphan is reported, the snapshot that
    did match is compared, and the exit code reflects that comparison and nothing
    else."""
    proc = _run(files["one_matches"], FLAG)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "unmatched=1" in proc.stdout
    assert "skipped=1" in proc.stdout
    assert "the run checked nothing" not in proc.stderr


def test_an_empty_snapshots_dir_still_has_its_own_message(tmp_path: Path) -> None:
    """`total == 0` never reaches the new rule, so the comparison is never the
    vacuous `0 == 0`. Pinned because if that guard ever moved, `skipped == total`
    would start firing on it with the wrong diagnostic."""
    empty = tmp_path / "no_snapshots"
    empty.mkdir()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "prompt_regression.cli",
            "run",
            "--snapshots",
            str(empty),
            "--candidates",
            str(CANDIDATES),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "no snapshot files under" in proc.stderr
    assert "the run checked nothing" not in proc.stderr
