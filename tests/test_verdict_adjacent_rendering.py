"""A value published beside its own verdict cannot contradict it (#179).

D-012 (#175) and D-013 (#177) are about a value and the **threshold** it was
compared against, both in one string, and both of their population arms *require*
a threshold to be in the string. The `run` command publishes a cosine beside its
`verdict` with the threshold nowhere in the output, so no arm in this suite could
reach either surface below.

The JSON surface contradicted its own verdict field
---------------------------------------------------

`cli.py` built each row with `"cosine": round(result.cosine_score, 4)` beside an
**unrounded** `"threshold"`. The verdict is decided at full precision. Measured
at the shipped `DEFAULT_THRESHOLD = 0.85`:

    true=0.84999 -> {"cosine": 0.85, "threshold": 0.85, "verdict": "fail"}

A consumer re-deriving `cosine >= threshold` from this repo's own
machine-readable output gets `pass`. That is #175's "mixed precision is worse
than matched" on the one surface where a *machine* compares the two numbers —
and it is invisible to D-012's and D-013's arms by construction, because those
walk f-strings and this was a `round()` in a dict literal.

The text table showed one number with two verdicts, in adjacent rows
--------------------------------------------------------------------

    verdict   cosine  snapshot
    -------- -------  ------------------------
    fail      0.850   snapshots/just-below.yml
    pass      0.850   snapshots/exactly-at.yml
    pass      0.850   snapshots/just-above.yml

One published number, two verdicts, in a **single table** rather than across two
runs. And the gate is `>=`, so `0.850` beside `fail` claims both "at or above the
threshold" and "did not reach it".

Per row, against that row's own threshold: per-snapshot tolerances make two rows
legitimately showing one cosine with different verdicts *correct*, so a
run-level number would be the wrong unit.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from prompt_regression.cli import (
    _TABLE_COSINE_PLACES,
    _TABLE_COSINE_WIDTH,
    _format_text_table,
    _row_for,
)
from prompt_regression.diff import (
    COMPARISON_PLACES,
    DEFAULT_THRESHOLD,
    DiffResult,
    render_classified,
    render_comparison,
)

_ROOT = Path(__file__).resolve().parents[1]

#: Margins either side of the three-place boundary, matching the sweep
#: `tests/test_comparison_rendering_matches_verdict.py` uses.
_MARGINS = [1e-1, 1e-2, 1e-3, 5e-4, 1e-4, 1e-5, 1e-6, 1e-8, 1e-10, 1e-12, 1e-14]
_IDS = [f"{m:g}" for m in _MARGINS]
_THRESHOLDS = [DEFAULT_THRESHOLD, 0.75, 0.9, 0.5, 0.0, 0.8501, 0.33333333333333331]


def _band(value: float, boundary: float) -> int:
    """Independent restatement of the property, so the arms do not import the rule."""
    if value < boundary:
        return -1
    if value > boundary:
        return 1
    return 0


def _row(cosine: float | None, threshold: float, name: str) -> dict:
    verdict = "error" if cosine is None else ("pass" if cosine >= threshold else "fail")
    return {
        "cosine": cosine,
        "threshold": threshold,
        "verdict": verdict,
        "snapshot_path": f"snapshots/{name}.yml",
        "notes": [],
    }


def _table(rows: list[dict]) -> str:
    failed = sum(1 for r in rows if r["verdict"] == "fail")
    return _format_text_table(rows, failed=failed, skipped=0, total=len(rows))


def _column_ends(table: str) -> set[int]:
    """Where each data row's cosine cell ends. Constant iff the column aligns."""
    ends = set()
    for line in table.splitlines():
        if line.startswith(("#", "verdict", "--", "    - ", "unmatched")):
            continue
        cell = line.split()[1]
        ends.add(line.index(cell) + len(cell))
    return ends


def _cosine_cells(table: str) -> list[str]:
    """The cosine column of every data row, as published."""
    out = []
    for line in table.splitlines():
        if line.startswith(("#", "verdict", "--", "    - ", "unmatched")):
            continue
        out.append(line.split()[1])
    return out


# --------------------------------------------------------------------------
# The JSON surface
# --------------------------------------------------------------------------


def _published_row(cosine: float, threshold: float) -> dict:
    """A row as `cli._row_for` actually builds it, serialized as `--json` emits it.

    Through the real builder, not a hand-made dict. A first draft of the arm
    below constructed its own row and stayed **green** against a probe that put
    `round(..., 4)` back — the `llm-cost-optimizer#227` vacuity shape, where
    every arm calls the helper directly and a call-site revert goes unnoticed.
    """
    result = DiffResult(
        cosine_score=cosine,
        semantic_category_scores=(),
        slot_deltas=(),
        verdict="pass" if cosine >= threshold else "fail",
        threshold=threshold,
        embedder_model="hash-embedder-128d-ngram2",
        snapshot_embedding_model="hash-embedder-128d-ngram2",
        notes=(),
    )
    # `_row_for` reads only `snap.id`, so a stub keeps this arm about the row
    # shape rather than about `Snapshot`'s own (strict) validation.
    snap = SimpleNamespace(id="s")
    row = _row_for(Path("snapshots/s.yml"), snap, result)  # type: ignore[arg-type]
    return json.loads(json.dumps(row))


@pytest.mark.parametrize("threshold", _THRESHOLDS, ids=[f"{t:g}" for t in _THRESHOLDS])
@pytest.mark.parametrize("margin", _MARGINS, ids=_IDS)
def test_a_json_row_never_contradicts_its_own_verdict(threshold: float, margin: float) -> None:
    """Re-derive the verdict from the two numbers the row publishes.

    The strongest available form of the criterion: no rendering rule is needed
    on a machine surface if the values are comparable as published. Before #179
    the score was `round(..., 4)` and the threshold exact, so the pair and the
    `verdict` field disagreed.
    """
    for cosine in (threshold - margin, threshold, threshold + margin):
        published = _published_row(cosine, threshold)
        rederived = "pass" if published["cosine"] >= published["threshold"] else "fail"
        assert rederived == published["verdict"], (
            f"published cosine={published['cosine']!r} threshold="
            f"{published['threshold']!r} re-derives as {rederived}, but the row "
            f"says verdict={published['verdict']!r}"
        )


def test_the_old_rounding_really_did_contradict_the_verdict() -> None:
    """Pin the defect, so the arm above is not a tautology.

    If `round(x, 4)` ever stopped collapsing a near-threshold cosine onto the
    threshold, the guard would be defending against nothing.
    """
    cosine, threshold = 0.84999, 0.85
    assert (cosine >= threshold) is False, "this input really is a fail"
    assert round(cosine, 4) == threshold, "the old rounding collapsed it onto the threshold"
    assert (round(cosine, 4) >= threshold) is True, (
        "which is what made the published pair re-derive as a pass"
    )


# --------------------------------------------------------------------------
# The text table
# --------------------------------------------------------------------------


@pytest.mark.parametrize("threshold", _THRESHOLDS, ids=[f"{t:g}" for t in _THRESHOLDS])
@pytest.mark.parametrize("margin", _MARGINS, ids=_IDS)
def test_a_published_cosine_falls_in_the_same_band_as_its_verdict(
    threshold: float, margin: float
) -> None:
    """Three levels, not two.

    A "would the verdict flip" check is satisfied by a below-threshold value
    rendering **at** the threshold — which is exactly the string a passing row
    produces, so the collision survives it.
    """
    for cosine in (threshold - margin, threshold, threshold + margin):
        cell = render_classified(cosine, threshold, places=_TABLE_COSINE_PLACES)
        assert _band(float(cell), threshold) == _band(cosine, threshold), (
            f"{cosine!r} against threshold {threshold!r} published {cell!r}, which "
            f"reads back in band {_band(float(cell), threshold)} rather than "
            f"{_band(cosine, threshold)}"
        )


def test_one_table_never_shows_one_number_with_two_verdicts() -> None:
    """The harm exactly as the reader meets it: adjacent rows of one table."""
    threshold = DEFAULT_THRESHOLD
    rows = [
        _row(threshold - 1e-10, threshold, "just-below"),
        _row(threshold, threshold, "exactly-at"),
        _row(threshold + 1e-10, threshold, "just-above"),
    ]
    assert [r["verdict"] for r in rows] == ["fail", "pass", "pass"], (
        "the fixture must contain both verdicts or it cannot express the defect"
    )
    cells = _cosine_cells(_table(rows))
    by_verdict: dict[str, set[str]] = {}
    for row, cell in zip(rows, cells, strict=True):
        by_verdict.setdefault(row["verdict"], set()).add(cell)
    assert not (by_verdict["fail"] & by_verdict["pass"]), (
        f"a published cosine appears with both verdicts in one table: {by_verdict}"
    )


def test_the_column_and_the_rule_widen_with_the_widest_cell() -> None:
    """A widened cell must not break the alignment of every other row.

    The width is derived from the set rather than hardcoded, and the header and
    the dashed rule derive from the same number — three places where a
    hand-maintained constant would drift apart.
    """
    threshold = DEFAULT_THRESHOLD
    table = _table(
        [
            _row(threshold - 1e-10, threshold, "narrow"),
            _row(0.5, threshold, "ordinary"),
        ]
    )
    lines = table.splitlines()
    header, rule = lines[1], lines[2]
    # The column is right-aligned, so what has to be constant is where each cell
    # *ends*, not where it starts. Checking the start is what a first draft of
    # this arm did, and it fails on a correctly aligned table.
    assert header.index("cosine") + len("cosine") == rule.index("  ", 9), (
        f"the header and the dashed rule disagree on the column width:\n{header}\n{rule}"
    )
    # The header's label sits exactly one column right of the numbers, which is
    # how this table has always rendered (`{'cosine':>7}` over `{:>6.3f} `).
    # Preserved rather than corrected: four README blocks pin the shipped
    # spelling byte-for-byte, and "fix the header alignment" is not this issue.
    ends = _column_ends(table)
    assert len(ends) == 1, f"the cosine column is not aligned across rows:\n{table}"
    assert ends.pop() + 1 == header.index("cosine") + len("cosine"), (
        f"the header no longer sits one column right of the cells:\n{header}\n{table}"
    )


def test_an_ordinary_table_is_byte_identical() -> None:
    """The README blocks pin this surface four separate ways, and must not move.

    `_TABLE_COSINE_WIDTH` is a floor rather than the width, which is what keeps a
    table with no near-threshold row exactly as it has always rendered.
    """
    rows = [
        {
            "cosine": 0.806,
            "threshold": 0.75,
            "verdict": "pass",
            "snapshot_path": "examples/snapshots/creative_kite_v1.yml",
            "notes": ["per-snapshot tolerance 0.750 overrides run threshold 0.850"],
        },
        {
            "cosine": None,
            "threshold": DEFAULT_THRESHOLD,
            "verdict": "error",
            "snapshot_path": "examples/snapshots/refund_window_v1.yml",
            "notes": [],
        },
    ]
    assert _format_text_table(rows, failed=1, skipped=0, total=2) == (
        "# prompt-snap run  total=2 failed=1 skipped=0 unmatched=0\n"
        "verdict   cosine  snapshot\n"
        "-------- -------  ------------------------\n"
        "pass      0.806   examples/snapshots/creative_kite_v1.yml\n"
        "    - per-snapshot tolerance 0.750 overrides run threshold 0.850\n"
        "error      -.--   examples/snapshots/refund_window_v1.yml\n"
    )
    assert _TABLE_COSINE_WIDTH == 6
    assert _TABLE_COSINE_PLACES == COMPARISON_PLACES


def test_a_missing_cosine_still_renders_in_the_widened_column() -> None:
    """`-.--` is right-aligned against the derived width, not a fixed literal."""
    threshold = DEFAULT_THRESHOLD
    table = _table([_row(threshold - 1e-10, threshold, "narrow"), _row(None, threshold, "errored")])
    cells = _cosine_cells(table)
    assert cells[1] == "-.--"
    assert len(_column_ends(table)) == 1, f"the error row broke the alignment:\n{table}"


def test_per_row_thresholds_are_respected() -> None:
    """Two rows showing one cosine with different verdicts is *correct* here.

    Per-snapshot tolerances are a documented feature — the README's own example
    carries "per-snapshot tolerance 0.750 overrides run threshold 0.850" — so a
    run-level number in the header would be the wrong unit, and a rule that
    forced the two rows apart would be wrong about the data.
    """
    rows = [_row(0.8, 0.75, "lenient"), _row(0.8, 0.85, "strict")]
    assert [r["verdict"] for r in rows] == ["pass", "fail"]
    cells = _cosine_cells(_table(rows))
    assert cells == ["0.800", "0.800"], (
        "both rows are far from their own thresholds, so neither needs widening — "
        "the identical rendering is truthful here"
    )


# --------------------------------------------------------------------------
# The helper
# --------------------------------------------------------------------------


def test_the_delegating_neighbour_is_wrong_on_two_inputs() -> None:
    """`render_comparison(value, boundary, places=...)[0]` is the obvious neighbour.

    One widening loop instead of two, on the argument that two renderings
    differing at width `w` must straddle the boundary. It is wrong on **signed
    zero** (`-0.000` and `0.000` are different strings for one value, and
    `float("-0.000")` is not below `0.0`) and on a **boundary not representable
    at `places`** (for `value == boundary == 0.8501` the pairwise rule
    short-circuits on equality and returns `0.850`, which reads back below a
    boundary the value sits on).

    Neither is reachable through `_format_text_table` today — a cosine lives in
    `[-1, 1]` and the shipped threshold is round — which is the point.
    """
    for value, boundary in [(-1e-4, 0.0), (0.8501, 0.8501)]:
        delegated, _ = render_comparison(value, boundary, places=COMPARISON_PLACES)
        assert _band(float(delegated), boundary) != _band(value, boundary)
        assert _band(
            float(render_classified(value, boundary, places=COMPARISON_PLACES)), boundary
        ) == _band(value, boundary)


def test_a_value_at_the_boundary_renders_there() -> None:
    for threshold in _THRESHOLDS:
        cell = render_classified(threshold, threshold, places=COMPARISON_PLACES)
        assert _band(float(cell), threshold) == 0


# --------------------------------------------------------------------------
# The population
# --------------------------------------------------------------------------


def test_no_run_surface_publishes_a_bare_fixed_width_cosine() -> None:
    """Discover the sites; the existing arms cannot, and that is why this exists.

    D-012's and D-013's walks require a **threshold** in the same string. This
    one is keyed on a cosine rendered at a fixed width *anywhere* in `cli.py`,
    which is the surface where the threshold is absent. The two partition the
    package rather than overlapping.
    """
    import ast
    import re

    source = (_ROOT / "prompt_regression" / "cli.py").read_text(encoding="utf-8")
    fixed = re.compile(r">?\d*\.\d+[fg]")
    offenders = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.JoinedStr):
            continue
        for part in node.values:
            if not isinstance(part, ast.FormattedValue) or part.format_spec is None:
                continue
            spec = "".join(c.value for c in part.format_spec.values if isinstance(c, ast.Constant))
            src = ast.unparse(part.value).lower()
            if "cosine" in src and fixed.search(spec):
                offenders.append(f"cli.py:{node.lineno} {ast.unparse(part.value)}:{spec}")
    assert not offenders, (
        f"these publish a cosine at a fixed width without routing it through a "
        f"rule that knows its threshold: {offenders} (#179)"
    )


def _rounded_cosines(source: str) -> list[str]:
    """Every `round(...)` applied to something named like a cosine, in *source*."""
    import ast

    out = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "round"
            and node.args
            and "cosine" in ast.unparse(node.args[0]).lower()
        ):
            out.append(f"line {node.lineno}: {ast.unparse(node)}")
    return out


def test_the_round_detector_finds_the_shape_it_looks_for() -> None:
    """Proved against a known-positive rather than against the live file.

    This arm's first draft asserted the walk found at least one `round()` in
    `cli.py` — and #179 removed the only one, so the non-vacuity check was
    itself vacuous the moment the fix landed. A detector is proved by showing it
    fires on the defect, not by counting nodes in a file that no longer has any.
    """
    positive = _rounded_cosines('row = {"cosine": round(result.cosine_score, 4)}')
    assert len(positive) == 1, positive
    assert "round(result.cosine_score, 4)" in positive[0]
    assert _rounded_cosines('row = {"cosine": result.cosine_score}') == []
    assert _rounded_cosines("x = round(elapsed_ms, 2)") == [], (
        "the detector must not flag rounding of things that are not compared against a threshold"
    )


def test_no_run_row_field_is_rounded_away_from_its_comparand() -> None:
    """The `round()` half, which no f-string walk can reach.

    Keyed on a `round(...)` applied to a score in `cli.py`. The threshold it is
    compared against is published exact, so rounding the score is what made the
    pair disagree with the verdict beside it.
    """
    source = (_ROOT / "prompt_regression" / "cli.py").read_text(encoding="utf-8")
    offenders = _rounded_cosines(source)
    assert not offenders, (
        f"these round a cosine that is published beside an unrounded threshold: {offenders} (#179)"
    )


def test_the_population_arms_are_not_vacuous() -> None:
    """The f-string walk reaches real nodes, so a pass means something.

    The `round()` walk's non-vacuity is `test_the_round_detector_finds_the_shape_it_looks_for`
    instead, and deliberately: counting `round()` calls in `cli.py` was this
    arm's first draft, and #179 removed the only one — so the check would have
    gone green over an empty set from the moment the fix landed.
    """
    import ast

    tree = ast.parse((_ROOT / "prompt_regression" / "cli.py").read_text(encoding="utf-8"))
    joined = [n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)]
    assert len(joined) >= 20, f"the f-string walk found only {len(joined)} nodes"
