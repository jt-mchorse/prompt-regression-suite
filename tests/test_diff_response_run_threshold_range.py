"""`diff_response` range-checks the run `threshold` even when a snapshot
`tolerance` overrides it (#292).

Measured on `dd8b17e` with `examples/snapshots/creative_kite_v1.yml`
(tolerance 0.75):

    diff_response(s, ..., threshold=float("nan")).notes
    -> ['per-snapshot tolerance 0.75 overrides run threshold nan', ...]

5.0 and -1.0 were accepted the same way. Only the *effective* threshold was
checked against `(0, 1]`, and the override had already replaced the run value
by then. `cli._validate_thresholds` documents that the library-level raises
"stay loud"; with a tolerance on the snapshot they did not fire.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from prompt_regression.diff import HashEmbedder, diff_response
from prompt_regression.io import load_snapshot

_KITE = Path(__file__).resolve().parents[1] / "examples" / "snapshots" / "creative_kite_v1.yml"
_CANDIDATE = "a kite on a beach"

_BAD = [
    pytest.param(float("nan"), id="nan"),
    pytest.param(-1.0, id="negative"),
    pytest.param(5.0, id="above-one"),
    pytest.param(0.0, id="zero"),
]


def _with_tolerance():
    snap = load_snapshot(_KITE)
    assert snap.tolerance == 0.75  # the fixture the repro was measured on
    return snap


def _without_tolerance():
    return dataclasses.replace(load_snapshot(_KITE), tolerance=None)


@pytest.mark.parametrize("threshold", _BAD)
def test_bad_run_threshold_raises_when_snapshot_has_tolerance(threshold: float) -> None:
    # Red against the unfixed code: the tolerance replaced the run value before
    # the range check, so these returned a DiffResult.
    with pytest.raises(ValueError, match=r"threshold must be in \(0, 1\]"):
        diff_response(_with_tolerance(), _CANDIDATE, embedder=HashEmbedder(), threshold=threshold)


@pytest.mark.parametrize("threshold", _BAD)
def test_bad_run_threshold_raises_without_tolerance(threshold: float) -> None:
    # Control: with no tolerance the run threshold *is* the effective one, so
    # this already raised before #292. Pins that the message did not change.
    with pytest.raises(ValueError, match=r"threshold must be in \(0, 1\]; got "):
        diff_response(
            _without_tolerance(), _CANDIDATE, embedder=HashEmbedder(), threshold=threshold
        )


def test_bad_run_threshold_error_is_bare_value_error() -> None:
    # The CLI relies on this being a *bare* ValueError, not one of the typed
    # per-row errors the `run` loop records -- a bad run threshold is a whole-run
    # misconfiguration, not a per-snapshot one.
    with pytest.raises(ValueError, match=r"got 5\.0$") as info:
        diff_response(_with_tolerance(), _CANDIDATE, embedder=HashEmbedder(), threshold=5.0)
    assert type(info.value) is ValueError
    assert str(info.value) == "threshold must be in (0, 1]; got 5.0"


def test_valid_run_threshold_is_still_overridden_by_tolerance() -> None:
    # Control: a valid run threshold still diffs, the tolerance still wins, and
    # the override note is unchanged.
    result = diff_response(_with_tolerance(), _CANDIDATE, embedder=HashEmbedder(), threshold=0.9)
    assert result.threshold == 0.75
    assert result.notes[0] == "per-snapshot tolerance 0.750 overrides run threshold 0.900"


@pytest.mark.parametrize("threshold", [1.0, 1e-9])
def test_run_threshold_bounds_are_accepted_under_a_tolerance(threshold: float) -> None:
    # Control: the inclusive upper bound and a tiny positive value are in range
    # and must not be rejected by the new check.
    result = diff_response(
        _with_tolerance(), _CANDIDATE, embedder=HashEmbedder(), threshold=threshold
    )
    assert result.threshold == 0.75
