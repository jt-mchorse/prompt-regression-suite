"""`save_snapshot` compares a shared YAML node once, not once per path (#286).

The #199 check loads both renderings back and compares them. With `!=` that
walked the fully expanded structure, and `safe_dump` writes a shared node once
under an anchor, so a 3 KB `prompt.extra` of ten aliases per level, a file that
loads, validates and diffs in 0.1 s, took 19 s at ten levels on 3.11 and
196 s on 3.14 in `update --force`, x10 per level.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from prompt_regression.io import load_snapshot, save_snapshot

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "snapshots" / "creative_kite_v1.yml"
# Twelve levels is ~10^12 expanded leaves: the unfixed comparison cannot finish
# inside the budget on any machine, the fixed one takes a fraction of a second.
LEVELS = 12
BUDGET_SECONDS = 30


def _alias_snapshot(tmp_path: Path, levels: int, leaf: str = "x") -> Path:
    lines = ["  extra:", f"    l0: &l0 [{', '.join([leaf] * 10)}]"]
    for i in range(1, levels + 1):
        lines.append(f"    l{i}: &l{i} [{', '.join([f'*l{i - 1}'] * 10)}]")
    src = EXAMPLE.read_text(encoding="utf-8")
    assert src.count("  extra: {}") == 1
    path = tmp_path / "aliases.yml"
    path.write_text(src.replace("  extra: {}", "\n".join(lines)), encoding="utf-8")
    return path


def _assert_alias_graph(extra: dict, levels: int, leaf: str = "x") -> None:
    # Checked by identity, level by level: `==` on this graph is the bug.
    assert extra["l0"] == [leaf] * 10
    for i in range(1, levels + 1):
        assert len(extra[f"l{i}"]) == 10
        assert all(m is extra[f"l{i - 1}"] for m in extra[f"l{i}"]), i


def test_update_force_on_a_wide_alias_graph_finishes(tmp_path: Path) -> None:
    path = _alias_snapshot(tmp_path, LEVELS)
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")]),
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "prompt_regression.cli", "update", "--snapshot", str(path)]
            + ["--canonical", "A kite drifts over the sand.", "--force"],
            capture_output=True,
            text=True,
            env=env,
            timeout=BUDGET_SECONDS,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"update --force did not finish in {BUDGET_SECONDS}s on a {LEVELS}-level alias graph"
        )
    assert proc.returncode == 0, proc.stderr
    snap = load_snapshot(path)
    assert snap.canonical.text == "A kite drifts over the sand."
    _assert_alias_graph(snap.prompt.extra, LEVELS)


def test_same_loaded_yaml_agrees_with_eq() -> None:
    from prompt_regression.io import _same_loaded_yaml

    shared = [1, 2]
    cases = [
        ({"a": [1, 2]}, {"a": [1, 2]}),
        ({"a": [1, 2]}, {"a": [1, 3]}),
        ({"a": 1}, {"b": 1}),
        ({"a": 1}, {"a": 1, "b": 2}),
        ([1, 2], (1, 2)),
        ([1.0], [1]),
        ([float("nan")], [float("nan")]),
        ([("k", shared)], [("k", [1, 2])]),
        ([shared, shared], [[1, 2], [1, 9]]),
        ({"s": {1, 2}}, {"s": {2, 1}}),
        ("a\x85b", "a b"),
    ]
    for a, b in cases:
        assert _same_loaded_yaml(a, b) == (a == b), (a, b)
        assert _same_loaded_yaml(b, a) == (b == a), (b, a)


# ---- controls (green before and after) ----


def test_control_a_shallow_alias_graph_round_trips(tmp_path: Path) -> None:
    path = _alias_snapshot(tmp_path, 3)
    snap = load_snapshot(path)
    save_snapshot(snap, path)
    _assert_alias_graph(load_snapshot(path).prompt.extra, 3)


def test_control_nel_inside_a_shared_node_still_picks_the_escaped_rendering(
    tmp_path: Path,
) -> None:
    # The difference #199 looks for sits under an anchor here, reached by
    # every alias: a comparison that skipped shared nodes would miss it.
    path = _alias_snapshot(tmp_path, 3, leaf='"a\\x85b"')
    snap = load_snapshot(path)
    assert snap.prompt.extra["l0"][0] == "a\x85b"
    save_snapshot(snap, path)
    assert "a\\Nb" in path.read_text(encoding="utf-8")  # the escaped form of NEL
    _assert_alias_graph(load_snapshot(path).prompt.extra, 3, leaf="a\x85b")


def test_control_the_shipped_example_saves_byte_identical(tmp_path: Path) -> None:
    out = tmp_path / "kite.yml"
    save_snapshot(load_snapshot(EXAMPLE), out)
    assert out.read_text(encoding="utf-8") == EXAMPLE.read_text(encoding="utf-8")
