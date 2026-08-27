"""Lock the README's `diff` / `update` CLI tour to measured output (#138).

Split out of #136, which fixed the `run` examples in the same fence. The
`diff`/`update` half pointed at `snapshots/refund-policy.snapshot.yaml` — a path
that has never existed in this repo, under a bare `snapshots/` root — and
annotated the command with `# verdict: warn` / `# cosine: 0.812`, numbers no run
ever produced. Handoff §10 forbids fabricated benchmark numbers; an annotated
transcript that reads as output is the same failure mode at documentation scale.

`update` is additionally the one destructive subcommand — it rewrites a
snapshot's canonical text in place — so an unrunnable example is worse than
usual: a reader cannot rehearse it before pointing it at their own tree.

Why this lock and not a wider path lock. `test_readme_shell_input_paths_exist`
deliberately only matches `examples/` / `fixtures/` / `tests/` roots, because a
bare relative dir in a generic tour is a plausible placeholder and matching it
would make that lock noisy — which is exactly why it did not catch this. A
behavioural lock catches the class properly: it *runs* the documented command.

The block deliberately covers all three exit channels, so the fence's own claims
are demonstrated rather than asserted in prose:

- pass / exit 0, on the candidate `examples/candidates.jsonl` already carries,
  so its cosine is the same number the `run` table above prints as 0.806
- fail / exit 1, which the fence claimed ("Exits 1 on fail") and never showed
- error / exit 2 on the D-006 embedder mismatch, matching how #136 documented
  the same guard for `run`
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
KITE = "examples/snapshots/creative_kite_v1.yml"
REFUND = "examples/snapshots/refund_window_v1.yml"

PASS_CANDIDATE = (
    "A kite drifts above an empty beach in the late afternoon. The salt wind tugs "
    "the string, a child below laughs and tugs back, and the horizon is a thin "
    "orange line, almost gone."
)
FAIL_CANDIDATE = "The quarterly revenue forecast was revised upward by nine percent."
MISMATCH_CANDIDATE = "Refunds are now available for 30 days after purchase."
NEW_CANONICAL = "A paper kite hangs over the empty sand as the light turns orange."


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _readme_tour() -> str:
    """The shell fence carrying the CLI tour."""
    text = README.read_text(encoding="utf-8")
    start = text.index("# Ad-hoc diff: one snapshot vs one candidate")
    end = text.index("```", start)
    return text[start:end]


# ----------------------------------------------------------------------
# The documented commands, run
# ----------------------------------------------------------------------


def test_the_pass_example_produces_the_documented_verdict_and_cosine() -> None:
    proc = _run("diff", "--snapshot", KITE, "--candidate", PASS_CANDIDATE)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "verdict: pass" in out
    assert "cosine:  0.8058 (threshold 0.75)" in out
    assert "embedder: hash-embedder-128d-ngram2  (snapshot: hash-embedder-128d-ngram2)" in out
    assert "per-snapshot tolerance 0.750 overrides run threshold 0.850" in out


def test_the_pass_cosine_is_the_same_number_the_run_table_reports() -> None:
    """The two examples in one fence must not disagree about one candidate.

    The `run` table above prints `0.806` for this snapshot; the `diff` example
    prints `0.8058`. Same measurement, different rounding — asserted here so a
    future edit to either cannot silently make them describe different runs.
    """
    proc = _run("diff", "--snapshot", KITE, "--candidate", PASS_CANDIDATE)
    match = re.search(r"cosine:\s+([0-9.]+)", proc.stdout)
    assert match, proc.stdout
    cosine = float(match.group(1))
    assert f"{cosine:.3f}" == "0.806"
    assert "0.806" in README.read_text(encoding="utf-8")


def test_the_fail_example_exits_1_as_the_fence_claims() -> None:
    proc = _run("diff", "--snapshot", KITE, "--candidate", FAIL_CANDIDATE)
    assert proc.returncode == 1, proc.stderr
    assert "verdict: fail" in proc.stdout
    assert "cosine:  0.0508 (threshold 0.75)" in proc.stdout
    assert "cosine 0.051 below threshold 0.750" in proc.stdout


def test_the_embedder_mismatch_example_exits_2_with_the_documented_error() -> None:
    proc = _run("diff", "--snapshot", REFUND, "--candidate", MISMATCH_CANDIDATE)
    assert proc.returncode == 2
    combined = proc.stdout + proc.stderr
    assert "text-embedding-3-small-truncated-8d" in combined
    assert "hash-embedder-128d-ngram2" in combined


def test_the_update_example_runs_on_a_copy_and_prints_the_documented_fields(
    tmp_path: Path,
) -> None:
    """`update` rewrites in place, so the documented recipe copies first."""
    copy = tmp_path / "creative_kite_v1.copy.yml"
    shutil.copy(REPO_ROOT / KITE, copy)
    before = copy.read_bytes()

    proc = _run("update", "--snapshot", str(copy), "--canonical", NEW_CANONICAL, "--force")
    assert proc.returncode == 0, proc.stderr
    assert "embedder=hash-embedder-128d-ngram2" in proc.stdout
    assert f"text_len={len(NEW_CANONICAL)}" in proc.stdout
    # The README documents `text_len=65`; that is this string's length.
    assert len(NEW_CANONICAL) == 65
    assert "text_len=65" in proc.stdout
    assert copy.read_bytes() != before, "update did not rewrite the copy"


def test_the_update_example_cannot_touch_a_committed_fixture() -> None:
    """The acceptance criterion that matters most: a reader following the fence
    line by line must not rewrite `examples/`."""
    tour = _readme_tour()
    update_block = tour[tour.index("prompt-snap update") :]
    snapshot_arg = re.search(r"--snapshot\s+(\S+)", update_block)
    assert snapshot_arg, update_block
    target = snapshot_arg.group(1)
    assert not target.startswith("examples/"), (
        f"the update example points at {target}, a committed fixture; it must operate on a copy"
    )
    assert "cp examples/snapshots/" in tour, (
        "the fence must make the copy itself, not just warn about it"
    )
    assert target.lstrip("./") in tour.split("cp ", 1)[1].split("\n", 1)[0], (
        "the copy destination and the --snapshot argument must be the same path"
    )


# ----------------------------------------------------------------------
# The block must stay measured
# ----------------------------------------------------------------------


def test_no_stale_path_or_number_survives_in_the_tour() -> None:
    tour = _readme_tour()
    for stale in (
        "snapshots/refund-policy.snapshot.yaml",
        "cosine:  0.812",
        "0.812",
    ):
        assert stale not in tour, f"the fabricated {stale!r} is back in the CLI tour"


def test_every_snapshot_path_in_the_tour_is_committed() -> None:
    tour = _readme_tour()
    refs = set(re.findall(r"examples/snapshots/[A-Za-z0-9_.-]+", tour))
    assert refs, "no snapshot paths found in the tour — the pattern went stale"
    missing = sorted(r for r in refs if not (REPO_ROOT / r).exists())
    assert not missing, missing


def test_the_lock_is_not_vacuous() -> None:
    """Every number this file asserts must actually appear in the README, or the
    behavioural assertions above would be pinning the tool to itself while the
    documentation drifted."""
    tour = _readme_tour()
    for number in ("0.8058", "0.0508", "0.750", "text_len=65"):
        assert number in tour, f"{number} is asserted here but absent from the README"
    # And the three exit channels are all present.
    assert tour.count("prompt-snap diff") == 3
    assert "verdict: pass" in tour
    assert "verdict: fail" in tour
    assert "error: snapshot was embedded with" in tour
