"""The warn/fail boundary is exact, shown, and never contradicted by a rendering (#203).

`run` decides `warn` vs `fail` at a second boundary, the warn floor
`threshold - warn_band`. Measured on main (11c1374), two hash-embedder rows at
the default threshold 0.85 and `--warn-band 0.05` printed::

    warn      0.800   .../a-just-above-floor.yml
    fail      0.800   .../b-just-below-floor.yml

(true cosines 0.80044 and 0.79967): the table widened against the threshold
only, and the floor appeared nowhere in the output. The floor itself was a float
subtraction, so `0.75 - 0.18 == 0.5700000000000001` made a cosine of exactly
0.57 a `fail`.
"""

from __future__ import annotations

import math
import random
import re
from fractions import Fraction
from pathlib import Path

import pytest

from prompt_regression.cli import _format_text_table, _row_for
from prompt_regression.diff import cosine, diff_response, warn_floor
from prompt_regression.html_report import ReportEntry, render_report
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot


class _FixedEmbedder:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    @property
    def model_name(self) -> str:
        return "fixed-warn-floor-embedder"

    def embed(self, text: str) -> list[float]:
        return self._vectors[text]


def _snapshot() -> Snapshot:
    return Snapshot(
        id="warn-floor",
        prompt=Prompt(model="claude-haiku-4-5", user="Describe the refund policy"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text="CANON", embedding=[1.0, 0.0], embedding_model="fixed-warn-floor-embedder"
        ),
        created_at="2026-01-01T00:00:00Z",
    )


def _diff(candidate_vec: list[float], threshold: float, warn_band: float):
    return diff_response(
        _snapshot(),
        "CAND",
        embedder=_FixedEmbedder({"CANON": [1.0, 0.0], "CAND": candidate_vec}),
        threshold=threshold,
        warn_band=warn_band,
    )


def _at(cos_target: float) -> list[float]:
    theta = math.acos(cos_target)
    return [math.cos(theta), math.sin(theta)]


_TWO_DECIMAL_PAIRS = [
    (t / 100, b / 100) for t in range(70, 100) for b in range(1, 31) if t - b >= 0
]


def test_the_floor_is_the_decimal_difference() -> None:
    wrong_before = sum(
        1
        for t, b in _TWO_DECIMAL_PAIRS
        if max(0.0, t - b) != float(Fraction(round(t * 100 - b * 100), 100))
    )
    assert wrong_before > 0  # the float subtraction really does miss some
    assert all(
        warn_floor(t, b) == float(Fraction(round(t * 100 - b * 100), 100))
        for t, b in _TWO_DECIMAL_PAIRS
    )
    assert warn_floor(0.85, 0.05) == 0.8
    assert warn_floor(0.03, 0.05) == 0.0  # clamped, as the band always was


def test_a_cosine_exactly_on_the_floor_is_a_warn() -> None:
    candidate = [0.57, math.sqrt(1 - 0.57 * 0.57)]
    assert cosine(candidate, [1.0, 0.0]) == 0.57  # bit-exact, or this arm is vacuous
    assert 0.75 - 0.18 > 0.57  # ... and the old floor really is above it
    result = _diff(candidate, threshold=0.75, warn_band=0.18)
    assert result.verdict == "warn"
    assert result.warn_floor == 0.57


def _table_cosines(rows: list[dict]) -> dict[str, str]:
    text = _format_text_table(rows, failed=0, skipped=0, total=len(rows))
    out = {}
    for line in text.splitlines():
        m = re.match(r"^(pass|warn|fail)\s+(\S+)\s+(\S+)$", line)
        if m:
            out[m.group(3)] = m.group(2)
    return out


def test_the_table_never_prints_a_cosine_on_the_wrong_side_of_either_boundary() -> None:
    # Search, not construct: margins on both sides of the floor and the threshold.
    rng = random.Random(203)
    threshold, band = 0.85, 0.05
    floor = warn_floor(threshold, band)
    rows = []
    for i in range(300):
        boundary = rng.choice([floor, threshold])
        margin = rng.choice([1e-3, 4e-4, 1e-4, 3e-5, 1e-6]) * rng.choice([-1, 1])
        result = _diff(_at(boundary + margin), threshold, band)
        rows.append(_row_for(Path(f"s{i}.yml"), _snapshot(), result))
    printed = _table_cosines(rows)
    verdicts = {r["snapshot_path"]: r["verdict"] for r in rows}
    seen = set()
    for path, text in printed.items():
        back = float(text)
        expected = "pass" if back >= threshold else "warn" if back >= floor else "fail"
        assert expected == verdicts[path], (path, text, verdicts[path])
        seen.add(verdicts[path])
    assert seen == {"pass", "warn", "fail"}  # every verdict occurs in the population


def test_the_issue_rows_and_their_notes() -> None:
    warn = _diff(_at(0.8004448151580841), 0.85, 0.05)
    fail = _diff(_at(0.7996709849747747), 0.85, 0.05)
    assert (warn.verdict, fail.verdict) == ("warn", "fail")
    printed = _table_cosines(
        [_row_for(Path("a.yml"), _snapshot(), warn), _row_for(Path("b.yml"), _snapshot(), fail)]
    )
    assert printed["a.yml"] != printed["b.yml"]
    # The fail note names the boundary it fell below.
    (note,) = fail.notes
    m = re.fullmatch(r"cosine (\S+) below threshold (\S+) and below warn floor (\S+)", note)
    assert m is not None, note
    assert float(m.group(1)) < float(m.group(3)) == 0.8


def test_without_a_warn_band_nothing_changes() -> None:
    result = _diff(_at(0.84), 0.85, 0.0)
    assert result.warn_floor is None
    assert result.notes == ["cosine 0.840 below threshold 0.850"]
    row = _row_for(Path("x.yml"), _snapshot(), result)
    assert row["warn_floor"] is None


@pytest.mark.parametrize(("cos", "verdict"), [(0.80044, "warn"), (0.79967, "fail")])
def test_the_html_meta_line_states_the_floor_and_agrees_with_its_badge(
    cos: float, verdict: str
) -> None:
    result = _diff(_at(cos), 0.85, 0.05)
    assert result.verdict == verdict
    html = render_report(
        [ReportEntry(snapshot_id="warn-floor", diff=result, candidate_text="CAND")]
    )
    m = re.search(
        r"cosine <code>([^<]+)</code> · threshold <code>([^<]+)</code> · warn floor <code>([^<]+)</code>",
        html,
    )
    assert m is not None
    back, floor = float(m.group(1)), float(m.group(3))
    assert floor == 0.8
    assert (back >= floor) is (verdict == "warn")
