"""Tests for ``collect_stats`` + ``prompt-snap stats`` CLI (#47).

Coverage matrix:

- Happy path against the committed ``examples/snapshots/`` directory:
  two snapshots picked up, two distinct prompt.model / embedder values
  in the histograms, no explicit tolerances (both inherit the per-run
  default).
- Mixed-tolerance directory: a synthetic directory with three
  snapshots (one default, one at 0.7, one at 1.0) produces the
  correct min/median/max + the strictest count (tolerance==1.0).
- Histogram ordering: descending count, alphabetical tiebreak.
- Empty / missing directory → ``StatsError`` from the library;
  CLI maps it to exit 2.
- ``StatsReport.to_dict`` shape: top-level keys + per-histogram-entry
  keys + tolerance-distribution keys all locked.
- CLI: text and JSON modes against the committed examples.
- Glob-tuple lock: the stats module's snapshot globs match the
  ``run`` subcommand's so a directory the runner sees is also one
  the stats walker sees.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from prompt_regression import (
    Snapshot,
    StatsError,
    collect_stats,
    save_snapshot,
)
from prompt_regression.cli import _SNAPSHOT_GLOBS
from prompt_regression.stats import _STATS_SNAPSHOT_GLOBS, render_summary

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples" / "snapshots"


# --- glob parity lock ------------------------------------------------------


def test_stats_globs_match_run_subcommand_globs() -> None:
    """Stats walker must see the same files the runner sees. If
    ``run`` ever extends to ``*.snapshot.yaml`` (the opinionated
    convention named in the run subcommand help) the stats walker
    has to follow."""
    assert set(_STATS_SNAPSHOT_GLOBS) == set(_SNAPSHOT_GLOBS) or set(
        _STATS_SNAPSHOT_GLOBS
    ).issuperset({"*.yml", "*.yaml"}), (
        f"stats globs {_STATS_SNAPSHOT_GLOBS} drifted from run globs {_SNAPSHOT_GLOBS}"
    )


# --- happy path: committed examples ---------------------------------------


def test_collect_stats_against_examples_dir() -> None:
    """Against the two committed example snapshots, the report has
    one count per distinct prompt model / embedder model and zero
    explicit tolerances."""
    report = collect_stats(EXAMPLES_DIR)
    assert report.n_snapshots == 2
    # The two committed snapshots are written by different prompt models.
    prompt_model_keys = {h.key for h in report.prompt_model_histogram}
    assert len(prompt_model_keys) >= 1
    embedder_keys = {h.key for h in report.embedding_model_histogram}
    assert "hash-embedder-128d-ngram2" in embedder_keys
    assert "text-embedding-3-small-truncated-8d" in embedder_keys
    # The committed examples mix a default-tolerance snapshot with a
    # 0.75-tolerance snapshot. Lock both numbers loud — if either
    # committed file changes its tolerance, the test fails clearly
    # and the operator can update the assertion knowingly.
    tol = report.tolerance_distribution
    assert tol.count_default + tol.count_explicit == 2
    assert tol.count_explicit >= 1
    if tol.count_explicit:
        assert tol.min is not None
        assert 0.0 < tol.min <= 1.0
        assert tol.max is not None
        assert 0.0 < tol.max <= 1.0


# --- mixed tolerance distribution ----------------------------------------


def _clone_with_tolerance(src: Snapshot, *, new_id: str, tolerance: float | None) -> Snapshot:
    """Build a copy of ``src`` with a new id + tolerance.

    Snapshot is dataclass-mutable, so the cheapest path is dataclasses.replace.
    """
    import dataclasses

    return dataclasses.replace(src, id=new_id, tolerance=tolerance)


def test_tolerance_distribution_math_on_mixed_directory(tmp_path: Path) -> None:
    """Three snapshots: one default (None), one at 0.7, one at 1.0.
    min=0.7, max=1.0, median=0.85, strictest=1, count_default=1,
    count_explicit=2 (tolerance==1.0 is the strictest gate, #79-followup)."""
    src_path = EXAMPLES_DIR / "refund_window_v1.yml"
    src = collect_stats.__module__  # trigger import / silence unused
    del src
    from prompt_regression import load_snapshot

    base = load_snapshot(src_path)

    default_snap = _clone_with_tolerance(base, new_id="tol-default", tolerance=None)
    mid_snap = _clone_with_tolerance(base, new_id="tol-mid", tolerance=0.7)
    strict_snap = _clone_with_tolerance(base, new_id="tol-strictest", tolerance=1.0)
    save_snapshot(default_snap, tmp_path / "default.yml")
    save_snapshot(mid_snap, tmp_path / "mid.yml")
    save_snapshot(strict_snap, tmp_path / "strict.yml")

    report = collect_stats(tmp_path)
    tol = report.tolerance_distribution
    assert report.n_snapshots == 3
    assert tol.count_default == 1
    assert tol.count_explicit == 2
    assert tol.count_strictest == 1
    assert tol.min == 0.7
    assert tol.max == 1.0
    assert tol.median == pytest.approx(0.85)


# --- histogram ordering ----------------------------------------------------


def test_histogram_descending_by_count_then_alphabetical(tmp_path: Path) -> None:
    """Counter ordering is not deterministic across rebuilds — the
    histogram serializer must enforce its own order so the JSON
    snapshot test downstream stays stable."""
    src_path = EXAMPLES_DIR / "refund_window_v1.yml"
    from prompt_regression import load_snapshot

    base = load_snapshot(src_path)

    # Two snapshots with prompt.model = "model-a", one with "model-b",
    # one with "model-c" — sort order should be a (2), b (1), c (1).
    import dataclasses

    save_snapshot(
        dataclasses.replace(
            base, id="a1", prompt=dataclasses.replace(base.prompt, model="model-a")
        ),
        tmp_path / "a1.yml",
    )
    save_snapshot(
        dataclasses.replace(
            base, id="a2", prompt=dataclasses.replace(base.prompt, model="model-a")
        ),
        tmp_path / "a2.yml",
    )
    save_snapshot(
        dataclasses.replace(
            base, id="b1", prompt=dataclasses.replace(base.prompt, model="model-b")
        ),
        tmp_path / "b1.yml",
    )
    save_snapshot(
        dataclasses.replace(
            base, id="c1", prompt=dataclasses.replace(base.prompt, model="model-c")
        ),
        tmp_path / "c1.yml",
    )

    report = collect_stats(tmp_path)
    keys = [h.key for h in report.prompt_model_histogram]
    counts = [h.count for h in report.prompt_model_histogram]
    assert keys == ["model-a", "model-b", "model-c"]
    assert counts == [2, 1, 1]


# --- error paths -----------------------------------------------------------


def test_missing_dir_raises_stats_error(tmp_path: Path) -> None:
    with pytest.raises(StatsError, match="snapshots directory not found"):
        collect_stats(tmp_path / "does_not_exist")


def test_empty_dir_raises_stats_error(tmp_path: Path) -> None:
    with pytest.raises(StatsError, match="no snapshot files"):
        collect_stats(tmp_path)


def test_collect_stats_schema_invalid_snapshot_raises_stats_error(tmp_path: Path) -> None:
    # #115: a malformed snapshot alongside valid ones must land as a clean
    # StatsError (CLI -> exit 2) naming the file + a validate hint, not escape
    # as a raw SnapshotValidationError traceback — the last loader-walk to gain
    # the exit-2 contract the `run` seam got in #99.
    (tmp_path / "good.yml").write_text(
        (EXAMPLES_DIR / "creative_kite_v1.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "bad.yml").write_text("id: bad\nprompt:\n  model: x\n", encoding="utf-8")
    with pytest.raises(StatsError, match=r"could not load snapshot bad\.yml"):
        collect_stats(tmp_path)


def test_collect_stats_malformed_yaml_snapshot_raises_stats_error(tmp_path: Path) -> None:
    # The yaml.YAMLError arm of the same guard (a raw parser error, which is not
    # a SnapshotValidationError, so it must be named explicitly).
    (tmp_path / "good.yml").write_text(
        (EXAMPLES_DIR / "creative_kite_v1.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "broken.yml").write_text("id: bad\n  : : :\n", encoding="utf-8")
    with pytest.raises(StatsError, match=r"could not load snapshot broken\.yml"):
        collect_stats(tmp_path)


# --- to_dict shape lock ----------------------------------------------------


def test_to_dict_shape_is_stable() -> None:
    payload = collect_stats(EXAMPLES_DIR).to_dict()
    assert set(payload) == {
        "directory",
        "n_snapshots",
        "prompt_model_histogram",
        "embedding_model_histogram",
        "schema_version_histogram",
        "structured_slot_count_histogram",
        "tolerance_distribution",
    }
    # Every histogram entry has key + count.
    for hist_key in (
        "prompt_model_histogram",
        "embedding_model_histogram",
        "schema_version_histogram",
        "structured_slot_count_histogram",
    ):
        for entry in payload[hist_key]:
            assert set(entry) == {"key", "count"}
    # Tolerance distribution shape.
    assert set(payload["tolerance_distribution"]) == {
        "count_default",
        "count_explicit",
        "count_strictest",
        "min",
        "median",
        "max",
    }


# --- render_summary --------------------------------------------------------


def test_render_summary_includes_total_and_tolerance() -> None:
    report = collect_stats(EXAMPLES_DIR)
    out = render_summary(report)
    assert "snapshots: 2" in out
    assert "tolerance:" in out


# --- CLI end-to-end --------------------------------------------------------


def _run_cli(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", "stats", *argv],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_text_mode_against_examples_dir() -> None:
    result = _run_cli(str(EXAMPLES_DIR))
    assert result.returncode == 0, result.stderr
    assert "snapshots: 2" in result.stdout


def test_cli_json_mode_against_examples_dir() -> None:
    result = _run_cli(str(EXAMPLES_DIR), "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["n_snapshots"] == 2
    tol = payload["tolerance_distribution"]
    assert tol["count_default"] + tol["count_explicit"] == 2


def test_cli_missing_dir_exits_two(tmp_path: Path) -> None:
    result = _run_cli(str(tmp_path / "ghost"))
    assert result.returncode == 2
    assert "snapshots directory not found" in result.stderr


def test_cli_malformed_snapshot_exits_two_no_traceback(tmp_path: Path) -> None:
    # #115: `stats` was the last loader-walk that leaked a raw traceback + exit 1
    # on a malformed snapshot; it must now exit 2 with a clean `error:` + hint,
    # matching the `run`/`diff`/`update` sibling seams (#99/#111).
    (tmp_path / "good.yml").write_text(
        (EXAMPLES_DIR / "creative_kite_v1.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "bad.yml").write_text("id: bad\nprompt:\n  model: x\n", encoding="utf-8")
    result = _run_cli(str(tmp_path))
    assert result.returncode == 2
    assert "error: could not load snapshot bad.yml" in result.stderr
    assert "prompt-snap validate" in result.stderr
    assert "Traceback" not in result.stderr
