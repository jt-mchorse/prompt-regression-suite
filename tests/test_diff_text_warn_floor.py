"""`prompt-snap diff`'s text widens the cosine against the warn floor too (#231).

#203 gave `run`'s table, the HTML report and the JSON the floor-aware rendering
and listed exactly those surfaces. `_format_diff_text` kept widening only
against the threshold, and the `warn` note never named the floor. Measured on
main with `examples/snapshots/creative_kite_v1.yml` and `--warn-band 0.0907`:

    verdict: fail                          verdict: warn
    cosine:  0.6593 (threshold 0.7500)     cosine:  0.6593 (threshold 0.7500)
      - cosine 0.65926 ... below warn      - cosine 0.659 ... but inside
        floor 0.65930                        warn band

So one printed cosine came with two verdicts, and the warn note's `0.659`
read as below the floor it claimed to be inside.
"""

from __future__ import annotations

import math
import re

import pytest

from prompt_regression.cli import _format_diff_text
from prompt_regression.diff import diff_response
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot


class _FixedEmbedder:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    @property
    def model_name(self) -> str:
        return "fixed-diff-floor-embedder"

    def embed(self, text: str) -> list[float]:
        return self._vectors[text]


def _snapshot() -> Snapshot:
    return Snapshot(
        id="diff-floor",
        prompt=Prompt(model="claude-haiku-4-5", user="Describe the kite"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text="CANON", embedding=[1.0, 0.0], embedding_model="fixed-diff-floor-embedder"
        ),
        created_at="2026-01-01T00:00:00Z",
    )


def _at(cos_target: float) -> list[float]:
    theta = math.acos(cos_target)
    return [math.cos(theta), math.sin(theta)]


def _text(cos_target: float, *, threshold: float, warn_band: float) -> tuple[str, object]:
    result = diff_response(
        _snapshot(),
        "CAND",
        embedder=_FixedEmbedder({"CANON": [1.0, 0.0], "CAND": _at(cos_target)}),
        threshold=threshold,
        warn_band=warn_band,
    )
    return _format_diff_text(result), result


def _cosine_line(text: str) -> str:
    return next(line for line in text.splitlines() if line.startswith("cosine:"))


def _side(value: float, boundary: float) -> int:
    return (value > boundary) - (value < boundary)


# The measured case's geometry: threshold 0.75, band 0.0907, floor 0.6593.
_T, _B = 0.75, 0.0907
_FLOOR = 0.6593


def test_a_warn_and_a_fail_either_side_of_the_floor_print_different_cosines() -> None:
    fail_text, fail = _text(_FLOOR - 0.00004, threshold=_T, warn_band=_B)
    warn_text, warn = _text(_FLOOR + 0.00002, threshold=_T, warn_band=_B)
    assert (fail.verdict, warn.verdict) == ("fail", "warn")  # type: ignore[attr-defined]
    fail_val = re.search(r"cosine:\s+(\S+)", fail_text).group(1)  # type: ignore[union-attr]
    warn_val = re.search(r"cosine:\s+(\S+)", warn_text).group(1)  # type: ignore[union-attr]
    assert fail_val != warn_val
    assert "warn floor 0.6593" in _cosine_line(fail_text)
    assert "warn floor 0.6593" in _cosine_line(warn_text)


@pytest.mark.parametrize("offset", [-3e-5, -1e-5, -2e-6, 2e-6, 1e-5, 3e-5])
def test_every_printed_cosine_reads_on_the_true_side_of_both_boundaries(offset: float) -> None:
    text, result = _text(_FLOOR + offset, threshold=_T, warn_band=_B)
    true = result.cosine_score  # type: ignore[attr-defined]
    floor = result.warn_floor  # type: ignore[attr-defined]
    printed = [float(m) for m in re.findall(r"cosine:?\s+(-?\d\.\d+)", text)]
    assert len(printed) == 2, text  # the cosine line and the note
    for value in printed:
        assert _side(value, floor) == _side(true, floor), (value, floor, text)
        assert _side(value, _T) == _side(true, _T), (value, _T, text)


def test_the_warn_note_names_the_floor() -> None:
    text, result = _text(_FLOOR + 0.00002, threshold=_T, warn_band=_B)
    assert result.verdict == "warn"  # type: ignore[attr-defined]
    assert "inside warn band (at or above warn floor 0.6593" in text


def test_without_a_band_the_cosine_line_is_unchanged() -> None:
    # Control: no floor, so no floor part and the threshold-only width.
    text, result = _text(0.8, threshold=0.85, warn_band=0.0)
    assert result.warn_floor is None  # type: ignore[attr-defined]
    assert _cosine_line(text) == "cosine:  0.8000 (threshold 0.8500)"
