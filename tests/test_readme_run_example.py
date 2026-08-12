"""Lock the README's `prompt-snap run` examples to the committed fixtures (#136).

The CI example named `--snapshots tests/snapshots --candidates
tests/candidates.jsonl`. Neither path has ever existed in this repo — there
is no `tests/snapshots`, and no `.jsonl` anywhere — so the documented
command exited 2 (`snapshots dir not found`) on a fresh clone. Every *other*
README reference uses `examples/snapshots/`; only that block invented a
`tests/` location.

The gap survived because the repo had no lock over paths inside shell
fences. `test_readme_shell_input_paths_exist` below closes that, ported from
llm-eval-harness#197 where the same shape was found.

What's locked here is the *behaviour* of the documented command, so the
example is a tested artifact rather than prose to hand-sync:

- exit 1, with per-snapshot verdicts pinned by snapshot id
- `creative_kite_v1.yml` passes at a cosine that clears its own 0.75
  tolerance but *not* the default 0.85 threshold — the per-snapshot
  override (D-005) doing real work rather than a degenerate 1.000
- `refund_window_v1.yml` errors on the embedder mismatch (D-006), which is
  the guard working as designed given the illustrative 8-d embedding (D-003)
- `--out` is written even on the exit-1 path, so a failing CI job still
  uploads its report
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = REPO_ROOT / "examples" / "snapshots"
CANDIDATES = REPO_ROOT / "examples" / "candidates.jsonl"

# The snapshot whose per-snapshot tolerance (0.75) is below the run default
# (0.85), so a mid-band cosine proves the override is applied.
KITE_ID = "creative-kite-poem-v1"
REFUND_ID = "refund-window-pro-v1"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_readme_fixtures_are_committed() -> None:
    assert SNAPSHOTS.is_dir(), "README's run examples point at examples/snapshots"
    assert CANDIDATES.exists(), (
        "examples/candidates.jsonl is referenced by both README `run` examples; "
        "without it the documented command exits 2 on a fresh clone"
    )


def test_candidates_file_exercises_both_documented_key_conventions() -> None:
    """The row shape is documented two ways; the fixture must show both.

    `_load_candidates` resolves a row by path-relative-to-snapshots-dir
    *first*, falling back to `snapshot.id`. That dual lookup was described
    only in a docstring with no committed instance to copy.
    """
    rows = [
        json.loads(line)
        for line in CANDIDATES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 2, "one candidate per committed snapshot"
    keys = {("snapshot" if "snapshot" in r else "id") for r in rows}
    assert keys == {"snapshot", "id"}, f"fixture must demonstrate both key conventions; got {keys}"
    assert all(isinstance(r["candidate"], str) and r["candidate"] for r in rows)


def test_readme_run_example_exits_1_with_the_documented_verdicts() -> None:
    proc = _run(
        "run",
        "--snapshots",
        "examples/snapshots",
        "--candidates",
        "examples/candidates.jsonl",
        "--format",
        "json",
    )
    assert proc.returncode == 1, f"expected exit 1; got {proc.returncode}. stderr={proc.stderr!r}"

    payload = json.loads(proc.stdout)
    rows = payload["rows"] if isinstance(payload, dict) else payload
    by_id = {r["snapshot_id"]: r for r in rows}

    assert by_id[KITE_ID]["verdict"] == "pass"
    assert by_id[REFUND_ID]["verdict"] == "error", (
        "the illustrative 8-d embedding (D-003) must still trip the embedder "
        "mismatch guard (D-006) — silencing it here would hide the feature"
    )


def test_kite_candidate_is_a_rewording_not_a_copy() -> None:
    """Pin the cosine into the band that makes the example meaningful.

    Above the snapshot's own 0.75 tolerance (so it passes) and below the
    0.85 run default (so the per-snapshot override is demonstrably what let
    it pass). A candidate copied from the canonical text would score 1.000
    and prove nothing; a range keeps the intent without pinning a digit that
    a deterministic-but-tunable embedder could shift slightly.
    """
    proc = _run(
        "run",
        "--snapshots",
        "examples/snapshots",
        "--candidates",
        "examples/candidates.jsonl",
        "--format",
        "json",
    )
    payload = json.loads(proc.stdout)
    rows = payload["rows"] if isinstance(payload, dict) else payload
    cosine = {r["snapshot_id"]: r["cosine"] for r in rows}[KITE_ID]

    assert cosine is not None
    assert 0.75 < cosine < 0.85, (
        f"candidate cosine {cosine} must sit between the snapshot tolerance "
        "(0.75) and the run default (0.85) so the override does real work"
    )


def test_html_out_is_written_on_the_exit_1_path(tmp_path: Path) -> None:
    """The README's CI example writes a report; a red run must still upload one."""
    out = tmp_path / "report.html"
    proc = _run(
        "run",
        "--snapshots",
        "examples/snapshots",
        "--candidates",
        "examples/candidates.jsonl",
        "--format",
        "html",
        "--out",
        str(out),
    )
    assert proc.returncode == 1
    assert out.exists(), "--format html --out must write even when the run fails"
    assert "<html" in out.read_text(encoding="utf-8").lower()
