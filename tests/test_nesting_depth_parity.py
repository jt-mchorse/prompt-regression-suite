"""The reader refuses any nesting the writer cannot write back (#278).

#232 made a too-deep snapshot a `parse` finding, but its limit was the stack's:
PyYAML's composer costs two frames per level and its representer three, so a
`prompt.extra` 340-480 levels deep loaded, validated and diffed, and
`update --force` then died in `save_snapshot` with a `RecursionError` traceback
at exit 1. A self-referencing alias (`&a [*a]`) took the same route through the
save's round-trip comparison. Both halves now share one explicit cap.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from prompt_regression import io as prs_io
from prompt_regression.cli import main
from prompt_regression.io import load_snapshot, save_snapshot
from prompt_regression.schema import SnapshotValidationError

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLE = _ROOT / "examples" / "snapshots" / "refund_window_v1.yml"
# The top-level mapping, `prompt` and `extra` are three levels before `k`.
_ABOVE_K = 3
# A literal rather than the source's constant, so the two controls below still
# run against a tree without it; the derivation lock pins the two together.
_CAP = 100


def _with_extra(tmp_path: Path, extra: str) -> Path:
    src = _EXAMPLE.read_text(encoding="utf-8")
    assert "  extra: {}\n" in src  # anti-vacuity: the substitution lands
    d = tmp_path / "snaps"
    d.mkdir()
    p = d / "deep.yml"
    p.write_text(src.replace("  extra: {}\n", f"  extra: {extra}\n"), encoding="utf-8")
    return p


def _lists(levels: int) -> str:
    return "{k: " + "[" * levels + "]" * levels + "}"


def _update(p: Path) -> int:
    canonical = yaml.safe_load(_EXAMPLE.read_text(encoding="utf-8"))["canonical"]["text"]
    return main(["update", "--snapshot", str(p), "--force", "--canonical", canonical])


def test_at_the_cap_round_trips_through_update(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Control: the deepest legal snapshot loads, re-baselines and loads back.
    p = _with_extra(tmp_path, _lists(_CAP - _ABOVE_K))
    before = load_snapshot(p).prompt.extra
    assert _update(p) == 0
    assert "Traceback" not in capsys.readouterr().err
    assert load_snapshot(p).prompt.extra == before


def test_one_past_the_cap_is_refused_at_load(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = _with_extra(tmp_path, _lists(_CAP - _ABOVE_K + 1))
    with pytest.raises(yaml.YAMLError, match="#278"):
        load_snapshot(p)
    assert main(["validate", str(p.parent)]) == 1
    out = capsys.readouterr()
    assert "deep.yml [parse]" in out.out + out.err


@pytest.mark.parametrize("levels", [340, 400])
def test_the_reported_depths_no_longer_reach_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], levels: int
) -> None:
    p = _with_extra(tmp_path, _lists(levels))
    before = p.read_bytes()
    assert _update(p) == 2
    err = capsys.readouterr().err
    assert "could not load snapshot" in err
    assert "Traceback" not in err
    assert p.read_bytes() == before


def test_a_self_referencing_alias_is_refused_at_load(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Sibling: tiny file, infinite depth; the save's round-trip `!=` overflowed.
    p = _with_extra(tmp_path, "{k: &a [*a]}")
    assert main(["validate", str(p.parent)]) == 1
    out = capsys.readouterr()
    assert "deep.yml [parse]" in out.out + out.err
    assert _update(p) == 2
    assert "recursive alias" in capsys.readouterr().err


def test_an_alias_chain_past_the_cap_is_refused(tmp_path: Path) -> None:
    # Every literal run of brackets is under the cap; the expanded structure is not.
    per = 60
    chain = [f"a0: &a0 {'[' * per}{']' * per}"]
    chain += [f"a{i}: &a{i} {'[' * per}*a{i - 1}{']' * per}" for i in range(1, 3)]
    assert per + _ABOVE_K + 1 < _CAP  # anti-vacuity
    p = _with_extra(tmp_path, "{" + ", ".join(chain) + "}")
    with pytest.raises(yaml.YAMLError, match=r"nested 18\d levels deep"):
        load_snapshot(p)


def test_the_writer_refuses_what_the_reader_would(tmp_path: Path) -> None:
    snap = load_snapshot(_EXAMPLE)
    deep: object = 1
    for _ in range(_CAP - _ABOVE_K + 1):
        deep = [deep]
    snap.prompt.extra = {"k": deep}
    out = tmp_path / "out.yml"
    with pytest.raises(SnapshotValidationError, match="#278"):
        save_snapshot(snap, out)
    assert not out.exists()


def test_the_writer_writes_the_cap(tmp_path: Path) -> None:
    # Control for the arm above: one level shallower is written and read back.
    snap = load_snapshot(_EXAMPLE)
    deep: object = 1
    for _ in range(_CAP - _ABOVE_K):
        deep = [deep]
    snap.prompt.extra = {"k": deep}
    out = tmp_path / "out.yml"
    save_snapshot(snap, out)
    assert load_snapshot(out).prompt.extra == {"k": deep}


def _deepest_dump(limit: int) -> int:
    def nest(levels: int) -> object:
        x: object = 1
        for _ in range(levels):
            x = [x]
        return x

    lo, hi = 1, 4000
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(limit)
    try:
        while lo < hi:
            mid = (lo + hi + 1) // 2
            try:
                yaml.safe_dump(nest(mid))
                lo = mid
            except RecursionError:
                hi = mid - 1
    finally:
        sys.setrecursionlimit(old)
    return lo


def test_the_cap_fits_the_writers_measured_stack_cost() -> None:
    # The derivation, re-measured: frames per level is the slope of the deepest
    # dumpable nesting between two recursion limits. The cap must cost the
    # writer at most a third of the default limit of 1000, so a PyYAML change
    # that makes the representer deeper, or a raised cap, shows up here.
    frames_per_level = 1000 / (_deepest_dump(3000) - _deepest_dump(2000))
    assert 2.5 < frames_per_level < 3.5  # anti-vacuity: the measurement is the known ~3
    assert prs_io._MAX_NESTING_DEPTH == _CAP
    assert frames_per_level * _CAP <= 1000 / 3
