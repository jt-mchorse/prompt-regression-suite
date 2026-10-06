"""A configured operand reads back as the value that was set (#181, D-015).

`render_comparison`'s loop stops as soon as the two rendered strings differ. That
is D-012's contract and it is the right one for an *ordering*: the reader can see
which number is larger. It says nothing about whether either number survives the
trip.

Every threshold this package compares against is something an operator typed.
`--threshold` and `--warn-band` are `type=float` with no width constraint, and a
per-snapshot `tolerance` comes from YAML. Measured at `2379e31`:

============================================  =========  ====================
site                                          places     published threshold
============================================  =========  ====================
`cli.py` cosine line, `--threshold 0.85004`   4          ``0.8500``
HTML meta line, threshold ``0.85004``         3          ``0.850``
`cli.py`, `--threshold 0.8512345`             4          ``0.8512``
============================================  =========  ====================

The run was gated at `0.85004`. A reader who copies `0.8500` back into the flag
gets a different gate. It is invisible while the threshold is round, which
`DEFAULT_THRESHOLD` is, and that is how five call sites carried it.

**This is not the collision #175/#177 fixed.** That one is two *equal* renderings
of two different numbers — "cosine 0.850 below threshold 0.850". This is two
*unequal* renderings, each of a number nobody configured. The ordering reads
correctly and the policy is misstated.

**`diff.py`'s tolerance note has two configured operands, and that is the
finding.** `llm-eval-harness`' D-029 shipped `exact_other` alone and its docstring
states there is "deliberately no `exact_value`" because "`value` is the measured
side at all six call sites". True there. Here,
`render_comparison(snapshot.tolerance, threshold, ...)` compares YAML against a
run parameter, and at `0.8500001` / `0.9000001` it published "per-snapshot
tolerance 0.850 overrides run threshold 0.900" — *both* numbers wrong, in the one
sentence that tells an operator which of their two values won. The asymmetry over
there is a fact about that repo's call sites, not about the class.
"""

from __future__ import annotations

import ast
import math
import re
from pathlib import Path

import pytest

from prompt_regression.diff import (
    COMPARISON_MAX_PLACES,
    COMPARISON_PLACES,
    diff_response,
    render_comparison,
)
from prompt_regression.html_report import ReportEntry, render_report
from prompt_regression.schema import (
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
)

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _ROOT / "prompt_regression"

# Configured values that do not survive a three- or four-place rendering. Each is
# a legal `--threshold`: the CLI validates finiteness and range, never a width.
_FINE_THRESHOLDS = [
    0.85004,
    0.8512345,
    0.750001,
    0.9000001,
    0.123456789,
    0.1 + 0.2,  # 0.30000000000000004, the shape arithmetic hands an operator
]
_IDS = [repr(t) for t in _FINE_THRESHOLDS]


class _FixedEmbedder:
    """Two-component deterministic embedder, so a cosine can be dialled exactly."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    @property
    def model_name(self) -> str:
        return "fixed-comparison-embedder"

    def embed(self, text: str) -> list[float]:
        return self._vectors[text]


def _diff_at(
    cosine_target: float,
    threshold: float,
    *,
    warn_band: float = 0.0,
    tolerance: float | None = None,
):
    """Run the real `diff_response` with `cosine_score` dialled to `cosine_target`."""
    theta = math.acos(cosine_target)
    canonical_vec = [1.0, 0.0]
    candidate_vec = [math.cos(theta), math.sin(theta)]
    kwargs = {} if tolerance is None else {"tolerance": tolerance}
    snapshot = Snapshot(
        id="configured-threshold",
        prompt=Prompt(model="claude-haiku-4-5", user="Describe the refund policy"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text="CANON",
            embedding=canonical_vec,
            embedding_model="fixed-comparison-embedder",
        ),
        **kwargs,
    )
    return diff_response(
        snapshot,
        "CAND",
        embedder=_FixedEmbedder({"CANON": canonical_vec, "CAND": candidate_vec}),
        threshold=threshold,
        warn_band=warn_band,
    )


def _places(rendered: str) -> int | None:
    """Decimal places in a fixed-point rendering; None for the `repr` fallback."""
    if "e" in rendered or "E" in rendered:
        return None
    _, _, frac = rendered.partition(".")
    return len(frac)


# --------------------------------------------------------------------------
# The helper
# --------------------------------------------------------------------------


@pytest.mark.parametrize("configured", _FINE_THRESHOLDS, ids=_IDS)
@pytest.mark.parametrize("places", [COMPARISON_PLACES, 4])
def test_a_marked_operand_reads_back_as_itself(configured: float, places: int) -> None:
    """The contract, stated as the contract rather than as a width.

    Run at both widths this package publishes, because a rule that happens to
    hold at one of them is not the rule it claims to be.
    """
    _, rendered_other = render_comparison(0.5, configured, places=places, exact_other=True)
    assert float(rendered_other) == configured


@pytest.mark.parametrize("configured", _FINE_THRESHOLDS, ids=_IDS)
def test_marking_keeps_both_operands_at_one_precision(configured: float) -> None:
    """D-012's invariant survives D-015, and this is the arm that says so.

    The obvious wrong way to make a threshold exact is to widen it alone. That is
    the pre-#175 shape: `render_comparison`'s own docstring records that "a caller
    that widened only its own side would print two numbers at different
    precisions and invite the reader to compare them as written".
    """
    value, other = render_comparison(0.5, configured, places=COMPARISON_PLACES, exact_other=True)
    assert _places(value) == _places(other)


def test_both_operands_can_be_marked_and_both_stay_exact() -> None:
    """The site `llm-eval-harness`' one-flag signature could not express.

    `diff.py`'s tolerance note compares two configured numbers, so marking one
    and not the other can leave the unmarked one misreported in the same
    sentence.

    **"Can", not "does", and picking the pair is the whole arm.** At
    `0.8500001` / `0.9000001` marking only `other` widens to seven places, which
    happens to make `value` exact too — the same exact-by-accident trap that made
    `llm-eval-harness`' first arms green against a call-site revert. The
    separating pair is one where the two need *different* widths: `0.123456789`
    needs nine and `0.9000001` needs seven, so widening for `other` alone stops
    four digits short of the tolerance.
    """
    tolerance, threshold = 0.123456789, 0.9000001
    rendered_tol, rendered_thr = render_comparison(
        tolerance, threshold, places=COMPARISON_PLACES, exact_value=True, exact_other=True
    )
    assert float(rendered_tol) == tolerance
    assert float(rendered_thr) == threshold
    assert _places(rendered_tol) == _places(rendered_thr)
    # Marking only `other` — the sibling repo's signature — leaves `value` wrong.
    only_other = render_comparison(tolerance, threshold, places=COMPARISON_PLACES, exact_other=True)
    assert float(only_other[0]) != tolerance


def test_one_flag_is_sometimes_enough_by_accident_and_that_is_not_a_result() -> None:
    """Stated as an arm because it is the trap, not a footnote.

    When the two configured values need the same width, marking either one
    widens far enough for both — and an arm built on that pair proves nothing
    about the second flag. This is the shape that made a sibling repo's first
    end-to-end arms green against a revert, so it is pinned here rather than
    rediscovered.
    """
    same_width = render_comparison(0.8500001, 0.9000001, places=COMPARISON_PLACES, exact_other=True)
    assert float(same_width[0]) == 0.8500001  # exact without being asked


def test_marking_is_off_by_default_so_d_012s_callers_are_unchanged() -> None:
    """An unmarked pair behaves exactly as it did, which is what keeps this additive."""
    assert render_comparison(0.92, 0.85004, places=4) == ("0.9200", "0.8500")
    assert render_comparison(0.92, 0.85004, places=4, exact_other=True) == ("0.92000", "0.85004")


def test_an_equal_pair_still_widens_for_a_marked_operand() -> None:
    """The one documented D-012 behaviour marking overrides.

    "Equal inputs return the narrow rendering unwidened: there is nothing to
    distinguish." True of the ordering, false of the policy — publishing a
    configured `0.85004` as `0.850` is a wrong claim about the configuration
    whether or not the measurement happens to equal it. No caller relies on the
    equal case (all four notes are reached under a strict inequality or a `!=`
    guard), but the function is total and says what it does.
    """
    assert render_comparison(0.85004, 0.85004, places=COMPARISON_PLACES) == ("0.850", "0.850")
    assert render_comparison(0.85004, 0.85004, places=COMPARISON_PLACES, exact_other=True) == (
        "0.85004",
        "0.85004",
    )


def test_a_round_threshold_is_unchanged_which_is_why_this_was_invisible() -> None:
    """`DEFAULT_THRESHOLD` and every threshold in the test suite round-trip already.

    The defect needs an operator who configured something finer than the
    published width, and the suite never did. Stated as an arm because it is the
    reason five call sites carried this.
    """
    for configured in (0.75, 0.8, 0.85, 0.9):
        for places in (COMPARISON_PLACES, 4):
            assert render_comparison(0.5, configured, places=places) == render_comparison(
                0.5, configured, places=places, exact_other=True
            )


def test_values_too_small_for_any_fixed_width_still_fall_back_to_repr() -> None:
    """`repr` round-trips a double by definition, so it satisfies marking exactly."""
    assert f"{1e-300:.{COMPARISON_MAX_PLACES}f}" == "0." + "0" * COMPARISON_MAX_PLACES
    value, other = render_comparison(
        1e-300, 2e-300, places=COMPARISON_PLACES, exact_value=True, exact_other=True
    )
    assert (float(value), float(other)) == (1e-300, 2e-300)


# --------------------------------------------------------------------------
# The five call sites, driven end to end
# --------------------------------------------------------------------------


@pytest.mark.parametrize("configured", _FINE_THRESHOLDS, ids=_IDS)
def test_the_fail_note_states_the_threshold_the_run_was_gated_at(configured: float) -> None:
    """Through `diff_response`, not through the helper.

    An arm that calls `render_comparison` directly stays green against a
    call-site revert. Every arm in this section goes through the real producer.
    """
    result = _diff_at(max(0.0, configured - 0.05), configured)
    (note,) = [n for n in result.notes if n.startswith("cosine") and "warn band" not in n]
    match = re.search(r"cosine (\S+) below threshold (\S+)", note)
    assert match is not None, note
    assert float(match.group(2)) == configured


def test_the_warn_note_states_it_too() -> None:
    """The second of `diff_response`'s two notes, on the same rendering path."""
    result = _diff_at(0.8, 0.85004, warn_band=0.1)
    (note,) = [n for n in result.notes if "warn band" in n]
    match = re.search(r"cosine (\S+) below threshold (\S+)", note)
    assert match is not None, note
    assert float(match.group(2)) == 0.85004


# Two pairs, because **one pair cannot separate both directions**. A single
# fixture leaves whichever flag it does not need satisfied by accident, which is
# how the first version of the arm below stayed green against the one-flag
# neighbour.
#
#   A: tolerance needs 9 places, threshold needs 7
#      -> `exact_other` alone stops at 7 and the TOLERANCE is wrong
#      -> `exact_value` alone widens to 9 and the threshold is right by accident
#   B: tolerance needs 2 places, threshold needs 7
#      -> `exact_value` alone returns at 3 and the THRESHOLD is wrong
#      -> `exact_other` alone widens to 7 and the tolerance is right by accident
#
# Together they reject both one-flag neighbours. Separately, each rejects one.
_TOLERANCE_PAIRS = [
    pytest.param(0.123456789, 0.9000001, id="tolerance-needs-more-places"),
    pytest.param(0.85, 0.9000001, id="threshold-needs-more-places"),
]


@pytest.mark.parametrize(("tolerance", "threshold"), _TOLERANCE_PAIRS)
def test_the_tolerance_note_states_both_of_the_numbers_it_compares(
    tolerance: float, threshold: float
) -> None:
    """The site with two configured operands, out of the real producer.

    "per-snapshot tolerance X overrides run threshold Y" is the sentence that
    tells an operator which of their two configured values won. At `2379e31`
    neither X nor Y was necessarily one they had set.

    Not the collision #175/#177 fixed: the guard above this note already
    established `tolerance != threshold`, so the two never render *identically*
    here. They render as two different numbers, neither of which is the one in
    force, which no assertion about their being distinct can see.
    """
    result = _diff_at(0.05, threshold, tolerance=tolerance)
    (note,) = [n for n in result.notes if "overrides run threshold" in n]
    match = re.search(r"tolerance (\S+) overrides run threshold (\S+)", note)
    assert match is not None, note
    assert float(match.group(1)) == tolerance
    assert float(match.group(2)) == threshold
    assert _places(match.group(1)) == _places(match.group(2))


def test_the_html_meta_line_states_the_configured_threshold() -> None:
    """The document an operator opens, rendered by `render_report`."""
    result = _diff_at(0.4, 0.85004)
    html_out = render_report([ReportEntry(snapshot_id="s1", diff=result, candidate_text="CAND")])
    match = re.search(r"threshold <code>([^<]+)</code>", html_out)
    assert match is not None, html_out
    assert float(match.group(1)) == 0.85004


def test_the_cli_cosine_line_states_the_configured_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The `cosine:  X (threshold Y)` line, out of `cli.main`.

    This is the surface a reader copies a number *back out of* into the flag,
    which is what makes it the worst place to publish a value nobody set.
    """
    from prompt_regression.cli import main as cli_main
    from prompt_regression.diff import HashEmbedder
    from prompt_regression.io import save_snapshot

    embedder = HashEmbedder()
    canonical = "Our refund policy gives Pro plan customers 14 days to request a return."
    snapshot = Snapshot(
        id="refund-policy",
        prompt=Prompt(model="claude-haiku-4-5", user="Describe the refund policy"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text=canonical,
            embedding=embedder.embed(canonical),
            embedding_model=embedder.model_name,
        ),
    )
    snap_path = tmp_path / "refund-policy.snapshot.yaml"
    save_snapshot(snapshot, snap_path)
    candidate = tmp_path / "candidate.txt"
    candidate.write_text("an entirely unrelated sentence about shipping", encoding="utf-8")

    cli_main(
        [
            "diff",
            "--snapshot",
            str(snap_path),
            "--candidate",
            str(candidate),
            "--threshold",
            repr(0.85004),
        ]
    )
    out = capsys.readouterr().out
    match = re.search(r"cosine:\s+(\S+) \(threshold (\S+)\)", out)
    assert match is not None, out
    assert float(match.group(2)) == 0.85004
    assert _places(match.group(1)) == _places(match.group(2))


def test_an_ordinary_run_at_a_round_threshold_is_byte_identical() -> None:
    """Nothing published moves at the shipped defaults.

    `DEFAULT_THRESHOLD` round-trips at three and at four places, so the notes,
    the HTML meta line and the README-pinned CLI tour are unaffected. Stated
    locally as well as pinned by `test_readme_cli_tour_examples`, because "the
    defaults do not move" is the claim a reviewer wants checked, not asserted.
    """
    result = _diff_at(0.8058, 0.75)
    assert any("below threshold 0.750" in n for n in result.notes) or result.verdict == "pass"
    assert render_comparison(0.8058, 0.75, places=4, exact_other=True) == ("0.8058", "0.7500")
    assert render_comparison(0.8058, 0.75, places=4) == ("0.8058", "0.7500")


# --------------------------------------------------------------------------
# The population
# --------------------------------------------------------------------------

# A configured parameter, structurally: the final segment of a name or dotted
# access, against a closed set. A substring rule would flag any caption
# containing the word; an enumerated set can go stale, which
# `test_the_closed_set_covers_every_float_the_cli_accepts` is for.
_CONFIGURED_NAMES = frozenset(
    {"threshold", "effective_threshold", "warn_band", "tolerance", "threshold_kappa"}
)


def _final_segment(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_configured(node: ast.expr) -> bool:
    return _final_segment(node) in _CONFIGURED_NAMES


def _render_comparison_calls() -> list[tuple[str, ast.Call]]:
    """Every `render_comparison(...)` call in the package except its definition's module docs."""
    out: list[tuple[str, ast.Call]] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _final_segment(node.func) == "render_comparison":
                out.append((f"{path.name}:{node.lineno}", node))
    return out


def test_every_render_comparison_call_marks_its_configured_operands() -> None:
    """Discover the population; do not trust the five sites the issue listed.

    Keyed on *which argument is a configured parameter*, per position, so the
    two-configured-operand site is not a special case anyone has to remember.
    A sixth call site inherits the rule with no list to update.

    Partitions cleanly against the two arms already in this repo: D-012's asks
    whether a comparison is rendered readably, and D-014's whether a verdict
    agrees with the value beside it. Neither asks whether an operand is the
    number the operator set.
    """
    missing: list[str] = []
    for where, call in _render_comparison_calls():
        kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg}
        for index, flag in ((0, "exact_value"), (1, "exact_other")):
            if len(call.args) <= index or not _is_configured(call.args[index]):
                continue
            marked = kwargs.get(flag)
            if not (isinstance(marked, ast.Constant) and marked.value is True):
                missing.append(f"{where} arg{index}={ast.unparse(call.args[index])} needs {flag}")
    assert not missing, (
        f"these `render_comparison` calls compare against a configured parameter "
        f"without marking it, so the number they publish is not necessarily the "
        f"one in force: {missing} (#181, D-015)."
    )


def test_the_population_arm_is_not_vacuous_and_names_what_it_found() -> None:
    """A pass over an empty set is not a pass, and the counts are the report.

    Pins the number of call sites and the number of *marked operands* — nine
    across eight sites, because the tolerance note contributes two. #203 added
    three, each marking the configured operand it prints: the fail note's warn
    floor and threshold, and the HTML report's warn floor. A walk that silently
    stopped matching `ast.Call` would make the arm above trivially true.
    """
    calls = _render_comparison_calls()
    assert len(calls) == 8, (
        f"found {len(calls)} render_comparison call sites: {[w for w, _ in calls]}"
    )
    marked = sum(
        1
        for _, call in calls
        for kw in call.keywords
        if kw.arg in {"exact_value", "exact_other"}
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is True
    )
    assert marked == 9, (
        f"{marked} marked operands across {len(calls)} call sites; seven sites each "
        f"mark their threshold or warn floor and `diff.py`'s tolerance note marks "
        f"both of its operands (#181, #203)."
    )


def test_the_closed_set_covers_every_float_the_cli_accepts() -> None:
    """An enumerated set is only as good as the thing that notices it went stale.

    Walk `cli.py` for every `add_argument(..., type=float, ...)`, derive the
    `dest` argparse would, and require the population arms to recognise it. A
    future `--min-cosine 0.0001` lands here as a red test naming itself rather
    than as a silent hole. `type=float` is the operator surface: an `int` flag
    cannot be misreported by a float rendering.
    """
    tree = ast.parse((_PACKAGE / "cli.py").read_text(encoding="utf-8"))
    dests: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _final_segment(node.func) != "add_argument":
            continue
        if not any(
            kw.arg == "type" and _final_segment(kw.value) == "float" for kw in node.keywords
        ):
            continue
        explicit = [kw.value for kw in node.keywords if kw.arg == "dest"]
        if explicit and isinstance(explicit[0], ast.Constant):
            dests.add(str(explicit[0].value))
            continue
        flags = [
            a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
        ]
        dests.add(max(flags, key=len, default="").lstrip("-").replace("-", "_"))
    assert dests, "no `type=float` arguments found in cli.py; the walk has stopped walking"
    unrecognised = sorted(dests - _CONFIGURED_NAMES)
    assert not unrecognised, (
        f"cli.py accepts these configured floats and the population arm does not "
        f"recognise them: {unrecognised}. Add them to `_CONFIGURED_NAMES` and check "
        f"how each is published (#181, D-015)."
    )


def test_the_standalone_readout_population_is_empty_here_and_that_is_measured() -> None:
    """`llm-eval-harness`' `render_configured` has no counterpart to build here.

    Its other half — a configured parameter published *alone*, with no second
    number — needs a population, and this package has none: #175/#177/#179 routed
    every threshold rendering through `render_comparison`. One fixed-width
    interpolation survives in `prompt_regression/`, and it is a bare measured
    cosine with no threshold and no status beside it, which is the same shape leh's
    D-028 decided out by name.

    Asserted rather than left as prose, so a new inline `:.Nf` on a configured
    value fails here instead of being found by the next cross-repo sweep.
    """
    fixed_width = re.compile(r"\.\d+[feg]")
    offenders: list[str] = []
    survivors: list[str] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.JoinedStr):
                continue
            for part in node.values:
                if not isinstance(part, ast.FormattedValue) or part.format_spec is None:
                    continue
                spec = "".join(
                    c.value for c in part.format_spec.values if isinstance(c, ast.Constant)
                )
                if not fixed_width.fullmatch(spec):
                    continue
                where = f"{path.name} {ast.unparse(part.value)}:{spec}"
                (offenders if _is_configured(part.value) else survivors).append(where)
    assert not offenders, (
        f"a configured parameter is published at a fixed width: {offenders}. "
        f"There is no standalone-readout helper here because there was no "
        f"population for one — decide this site rather than adding one by reflex."
    )
    assert survivors == ["html_report.py cat.cosine_to_response:.3f"], (
        f"the surviving fixed-width interpolations are now {survivors}. Each one "
        f"needs checking against #179/D-014 (a value beside its own verdict) as "
        f"well as this issue."
    )
