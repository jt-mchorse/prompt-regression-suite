"""A stated ordering between two numbers stays visible when they are rendered (#175).

`diff_response` decides pass/fail at full float precision::

    cosine_pass = cosine_score >= effective_threshold

and then explained the decision at a fixed three places, so a near-threshold
failure published a note that contradicted itself::

    cosine=0.8499996  threshold=0.85  verdict=fail
    -> "cosine 0.850 below threshold 0.850"

A near-threshold failure is the ordinary shape of a marginal regression and
exactly when an operator reads the note most carefully. The guard was never
wrong; only its explanation was, which is why no existing test caught it — the
verdict is correct in every one of these cases.

Four surfaces rendered the pair and all four are covered here: the fail note,
the warn note, the per-snapshot tolerance note, and the HTML report's meta line
beside the verdict badge. `cli.py`'s `cosine: … (threshold …)` line is
*deliberately* excluded; see `test_the_cli_line_cannot_read_as_a_contradiction`
for why that one is a different shape rather than an oversight.

The central arm is a **margin search**, not a hand-picked value. A single value
can pass by luck on a margin that happens to render distinctly, which is exactly
how `.3f` looked fine for as long as it did.
"""

from __future__ import annotations

import math
import re

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
    """Run the real `diff_response` with `cosine_score` dialled to `cosine_target`.

    Unit vectors at a chosen angle rather than a stub `DiffResult`, so the notes
    under test are the ones `diff_response` actually builds.
    """
    theta = math.acos(cosine_target)
    canonical_vec = [1.0, 0.0]
    candidate_vec = [math.cos(theta), math.sin(theta)]
    kwargs = {} if tolerance is None else {"tolerance": tolerance}
    snapshot = Snapshot(
        id="near-threshold",
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


_NOTE_PAIR = re.compile(r"cosine (\S+) below threshold (\S+)")


# Margins spanning the region where a fixed `.3f` collides and the region where
# it does not, so the search covers both sides of the old boundary.
_MARGINS = [
    5e-1,
    1e-1,
    1e-2,
    1e-3,
    5e-4,
    1e-4,
    1e-5,
    1e-6,
    1e-8,
    1e-10,
    1e-12,
    1e-14,
    1e-15,
]


@pytest.mark.parametrize("margin", _MARGINS, ids=[f"{m:g}" for m in _MARGINS])
def test_a_failing_margin_is_always_visibly_ordered(margin: float) -> None:
    """The verdict and the note can never disagree, across the whole margin range.

    This is the arm that matters. For every margin at which the guard fails, the
    note's two numbers must differ as *strings* — otherwise the sentence asserts
    an ordering the reader cannot see. Swept rather than sampled: the old `.3f`
    is correct for the four widest margins here and wrong for the rest, so any
    single hand-picked value is a coin flip.
    """
    threshold = 0.85
    result = _diff_at(threshold - margin, threshold)
    assert result.verdict == "fail", (
        f"margin {margin:g} did not produce a failing verdict; the arm is not "
        f"testing what it claims to."
    )
    assert result.cosine_score < result.threshold, "precondition: the guard failed"

    (note,) = [n for n in result.notes if "below threshold" in n]
    match = _NOTE_PAIR.search(note)
    assert match is not None, f"could not parse the comparison out of {note!r}"
    rendered_score, rendered_threshold = match.groups()
    assert rendered_score != rendered_threshold, (
        f"at margin {margin:g} the note reads {note!r} — it asserts one number "
        f"is below another and renders them identically, so the operator cannot "
        f"see why the run failed."
    )
    assert float(rendered_score) < float(rendered_threshold), (
        f"at margin {margin:g} the note renders {rendered_score} and "
        f"{rendered_threshold}, which do not reproduce the ordering the verdict "
        f"was decided on."
    )


@pytest.mark.parametrize("margin", _MARGINS, ids=[f"{m:g}" for m in _MARGINS])
def test_the_threshold_may_be_the_side_carrying_the_extra_digits(margin: float) -> None:
    """The other orientation, and it is the one that produces a *backwards* read.

    Every margin in the sweep above sits below a round ``0.85``, so the **cosine**
    is always the side with the long decimal expansion. That is one half of the
    population. Here the threshold is the long one (``0.3 + margin``) and the
    cosine is round, which is what an operator gets from a tolerance computed
    rather than typed — ``threshold - warn_band``, a value read from YAML, or any
    arithmetic on a configured number.

    This orientation is why the two sides must be rendered at the *same*
    precision. Widening only the value produces::

        "cosine 0.8500000000 below threshold 0.850"

    where `float(rendered_score) < float(rendered_threshold)` is **False** — the
    note does not merely hide the ordering, it states the reverse of it. Found by
    running that neighbour, which the one-orientation sweep passed.
    """
    # 0.3 rather than 0.8 so the widest margin (0.5) still leaves the threshold
    # inside `diff_response`'s documented `(0, 1]` contract.
    cosine_target = 0.3
    threshold = cosine_target + margin
    result = _diff_at(cosine_target, threshold)
    assert result.verdict == "fail", f"margin {margin:g} did not fail"

    (note,) = [n for n in result.notes if "below threshold" in n]
    match = _NOTE_PAIR.search(note)
    assert match is not None, note
    rendered_score, rendered_threshold = match.groups()
    assert rendered_score != rendered_threshold, (
        f"at margin {margin:g} the note reads {note!r}, rendering both sides identically."
    )
    assert float(rendered_score) < float(rendered_threshold), (
        f"at margin {margin:g} the note reads {note!r} — read as written, the "
        f"cosine is NOT below the threshold, so the note states the reverse of "
        f"the verdict."
    )


def _decimal_places(rendered: str) -> int | None:
    """Places in a fixed-point rendering; None for the `repr` fallback form."""
    if "e" in rendered or "E" in rendered:
        return None
    _, _, frac = rendered.partition(".")
    return len(frac)


@pytest.mark.parametrize(
    ("value", "other"),
    [
        (0.85 - 1e-8, 0.85),
        (0.3, 0.3 + 1e-8),
        (0.85 - 1e-15, 0.85),
        (0.3, 0.3 + 1e-15),
        (0.0508, 0.75),
        (0.218, 0.85),
    ],
    ids=[
        "value-long",
        "threshold-long",
        "value-very-long",
        "threshold-very-long",
        "readme-pinned",
        "demo-pinned",
    ],
)
def test_both_sides_are_rendered_at_the_same_precision(value: float, other: float) -> None:
    """The structural property, stated directly rather than inferred from outcomes.

    The two numbers appear in one sentence asserting an ordering between them, so
    a reader compares them *as written*. Rendering them at different precisions
    invites that comparison to come out wrong, and in the threshold-long
    orientation it does.

    This is the arm that rejects the widen-one-side neighbour in every
    orientation, rather than only where the outcome happens to be visible.
    """
    rendered_value, rendered_other = render_comparison(value, other, places=COMPARISON_PLACES)
    assert _decimal_places(rendered_value) == _decimal_places(rendered_other), (
        f"render_comparison({value!r}, {other!r}) returned "
        f"{(rendered_value, rendered_other)} — the two sides are at different "
        f"precisions, so comparing them as written is unreliable."
    )


def test_the_old_fixed_width_really_did_collide() -> None:
    """Anti-vacuity on the margin list: it contains margins `.3f` cannot render.

    Without this, the sweep above could be a list of comfortable margins that
    the pre-#175 code also passed, and the suite would prove nothing. Green on
    both trees on purpose — it is a statement about arithmetic, and it is what
    says the other arm's corpus is the right one.
    """
    threshold = 0.85
    colliding = [
        margin
        for margin in _MARGINS
        if f"{threshold - margin:.{COMPARISON_PLACES}f}" == f"{threshold:.{COMPARISON_PLACES}f}"
    ]
    assert len(colliding) >= 8, (
        f"only {len(colliding)} of {len(_MARGINS)} margins collide at "
        f"{COMPARISON_PLACES} places, so the sweep mostly exercises margins the "
        f"old renderer already handled."
    )


def test_ordinary_values_keep_the_narrow_rendering() -> None:
    """The control: nothing that already rendered correctly moved.

    This is what separates the fix from the neighbour that simply widens the
    fixed width. `README.md`'s CLI tour pins `cosine 0.051 below threshold
    0.750` and `docs/regression_demo.html` is tracked with `0.218` / `0.850`; a
    wider fixed width churns both.
    """
    assert render_comparison(0.0508, 0.75, places=COMPARISON_PLACES) == ("0.051", "0.750")
    assert render_comparison(0.218, 0.85, places=COMPARISON_PLACES) == ("0.218", "0.850")
    result = _diff_at(0.0508, 0.75)
    assert "cosine 0.051 below threshold 0.750" in result.notes, (
        f"the README-pinned note text moved: {result.notes}"
    )


def test_equal_values_are_not_widened() -> None:
    """Equal inputs render narrow — widening would imply a difference.

    Reachable on a *passing* row, where `cosine_score == threshold` satisfies
    `>=`. The notes never see it (they are reached only on a strict `<`), but the
    HTML meta line renders the pair for every verdict.
    """
    assert render_comparison(0.85, 0.85, places=COMPARISON_PLACES) == ("0.850", "0.850")


def test_values_too_small_for_any_fixed_width_fall_back_to_repr() -> None:
    """The ceiling is a ceiling, and the fallback is what makes the helper total.

    Two distinct subnormal-scale doubles render identically at *any* fixed
    number of places, so a loop bounded at `COMPARISON_MAX_PLACES` cannot
    separate them. `repr` round-trips a float by definition.
    """
    assert f"{1e-300:.{COMPARISON_MAX_PLACES}f}" == f"{2e-300:.{COMPARISON_MAX_PLACES}f}"
    assert render_comparison(1e-300, 2e-300, places=COMPARISON_PLACES) == ("1e-300", "2e-300")


def test_a_negative_cosine_still_renders() -> None:
    """An orthogonal-or-opposed candidate is a legitimate score, not an edge case."""
    assert render_comparison(-0.5, 0.85, places=COMPARISON_PLACES) == ("-0.500", "0.850")


def test_the_warn_note_is_covered_too() -> None:
    """The warn note says "below" as well, so it is the same claim.

    A fix applied only to the fail note leaves the warn path contradicting
    itself, and warn is the *more* likely verdict at a near-threshold margin
    once a warn band is configured.
    """
    result = _diff_at(0.8499996, 0.85, warn_band=0.05)
    assert result.verdict == "warn", result.verdict
    (note,) = result.notes
    match = _NOTE_PAIR.search(note)
    assert match is not None, note
    assert match.group(1) != match.group(2), (
        f"the warn note renders both sides identically: {note!r}"
    )
    assert "but inside warn band" in note


def test_the_tolerance_note_is_covered_too() -> None:
    """The cleanest case: the guard has already proved the two values differ.

    `diff_response` emits this note under
    ``snapshot.tolerance is not None and snapshot.tolerance != threshold``, so an
    inequality is established one line before the rendering. At a fixed three
    places it could publish "tolerance 0.850 overrides run threshold 0.850" — an
    override described as changing nothing.
    """
    result = _diff_at(0.5, 0.85, tolerance=0.8499996)
    (note,) = [n for n in result.notes if "overrides run threshold" in n]
    match = re.search(r"tolerance (\S+) overrides run threshold (\S+)", note)
    assert match is not None, note
    assert match.group(1) != match.group(2), (
        f"the tolerance note describes an override between two numbers it "
        f"renders identically: {note!r}"
    )


def test_the_html_meta_line_cannot_contradict_its_own_badge() -> None:
    """The document the operator opens, not the helper behind it.

    `render_report` rather than `_render_entry`, so this arm also pins that the
    call site is wired up — a formatter-level check stays green against a
    call-site revert, which is the trap `vector-search-at-scale#148` fell into.
    """
    result = _diff_at(0.8499996, 0.85)
    assert result.verdict == "fail"
    html_text = render_report(
        [ReportEntry(snapshot_id="near-threshold", diff=result, candidate_text="CAND")]
    )

    match = re.search(r"cosine <code>([^<]+)</code> · threshold <code>([^<]+)</code>", html_text)
    assert match is not None, "the meta line is not in the rendered report"
    rendered_score, rendered_threshold = match.groups()
    assert "FAIL" in html_text
    assert rendered_score != rendered_threshold, (
        f"the report shows cosine {rendered_score} and threshold "
        f"{rendered_threshold} beside a FAIL badge, so the document reads as "
        f"though the badge were wrong."
    )
    assert float(rendered_score) < float(rendered_threshold)


def test_the_html_report_and_its_notes_agree_on_precision() -> None:
    """One helper, so the meta line and the note inside it cannot disagree.

    Two independent widening rules in one document would show the same number
    two ways on the same screen. This is the reason `html_report` imports the
    helper instead of growing its own.
    """
    result = _diff_at(0.8499996, 0.85)
    html_text = render_report(
        [ReportEntry(snapshot_id="near-threshold", diff=result, candidate_text="CAND")]
    )
    meta = re.search(r"cosine <code>([^<]+)</code> · threshold <code>([^<]+)</code>", html_text)
    assert meta is not None
    (note,) = [n for n in result.notes if "below threshold" in n]
    note_match = _NOTE_PAIR.search(note)
    assert note_match is not None
    assert meta.groups() == note_match.groups(), (
        f"the meta line renders {meta.groups()} while the note in the same "
        f"document renders {note_match.groups()}."
    )


# Thresholds, chosen to make the population visible rather than to pass.
# #177's finding is that the #175 exclusion for the CLI line rested on the
# threshold's `repr` being SHORTER than the cosine's fixed width — true of every
# round default, false as soon as the operator passes one with four decimals.
# `--threshold` is `type=float` on both `check` and `diff`, so both halves of
# this table are one flag away.
_CLI_THRESHOLDS = (
    pytest.param(0.85, id="round-default"),
    pytest.param(0.5, id="round-half"),
    pytest.param(0.6, id="round-0.6"),
    pytest.param(0.8501, id="four-decimal-repr"),
    pytest.param(0.1234, id="four-decimal-low"),
    pytest.param(0.9999, id="four-decimal-high"),
    pytest.param(0.1 + 0.2 - 0.25, id="arithmetic-derived"),
)


@pytest.mark.parametrize("threshold", _CLI_THRESHOLDS)
def test_the_cli_verdict_and_cosine_lines_cannot_contradict_each_other(
    threshold: float,
) -> None:
    """The `verdict:` / `cosine:` pair, read as a reader reads it (#177).

    #175 excluded this surface on two claims and both were false.

    *"Trailing zeros keep them from ever reading as the same number"* holds only
    while the threshold's `repr` is shorter than four decimals. At `0.8501` a
    near-miss rendered ``cosine:  0.8501 (threshold 0.8501)`` — the exact #175
    collision, in the one surface #175 decided it could not reach.

    *"The sentence asserts no ordering"* is true of the sentence and false of
    the output, because `_format_diff_text` puts `verdict:` on the line directly
    above. The gate is ``cosine_score >= effective_threshold``, so a cosine
    equal to the threshold **passes** — and the old rendering let a `fail`
    verdict sit above two numbers that read as equal.

    So this arm asserts the *relationship*, not the strings: read both lines
    back and require them to agree. Same lens as
    `agent-orchestration-platform#147`, where a headline and its own body were
    each correct alone.

    The old arm was a single call at `0.85` behind a docstring that claimed a
    universal, and it asserted only that the two *strings* differed. Measured
    against the pre-#177 line, this arm goes red on **6 of these 7** ids — and
    `round-default` is one of them. So the surface was already broken at the
    shipped default, by a mechanism neither #175 nor #177's own issue named:
    `f"{0.85 - 1e-9:.4f}"` is `'0.8500'` against `str(0.85)` = `'0.85'`, which
    are different strings that read as the *same value*, so the pair states
    "0.85 is below 0.85" under a `fail` verdict. Asserting inequality of the
    rendered strings was the wrong unit; asserting the pair agrees with the
    verdict is the right one.

    The one id this arm does *not* catch is `arithmetic-derived`, and
    `test_the_cli_renders_both_sides_at_the_same_precision` catches exactly
    that one plus the three round ones. The two arms are complementary on this
    table and neither covers it alone — which is the argument for keeping both.
    """
    from prompt_regression.cli import _format_diff_text

    text = _format_diff_text(_diff_at(threshold - 1e-9, threshold))
    verdict = re.search(r"verdict: (\S+)", text)
    match = re.search(r"cosine:\s+(\S+) \(threshold (\S+)\)", text)
    assert verdict is not None, text
    assert match is not None, text
    rendered_cosine, rendered_threshold = match.groups()

    assert rendered_cosine != rendered_threshold, (
        f"the CLI renders cosine and threshold identically at threshold="
        f"{threshold!r}, above a {verdict.group(1)!r} verdict:\n{text}"
    )
    # A `fail` means the cosine was strictly below; the rendering must say so.
    assert float(rendered_cosine) < float(rendered_threshold), (
        f"the rendered pair states the reverse of the {verdict.group(1)!r} "
        f"verdict at threshold={threshold!r}:\n{text}"
    )


@pytest.mark.parametrize("threshold", _CLI_THRESHOLDS)
def test_the_cli_renders_both_sides_at_the_same_precision(threshold: float) -> None:
    """The structural half, and the one that rejects the wrong neighbour.

    Before #177 this line rendered its two sides at *different* precisions by
    design — `.4f` against an unformatted threshold. That is precisely the
    "widen only one side" shape #175 measured as reading backwards, so the
    ordering arm above is not enough on its own.

    Measured against the pre-#177 line: this arm goes red on `round-default`,
    `round-half`, `round-0.6` and `arithmetic-derived` — and stays green on all
    three four-decimal ids, where the two sides happen to land on the same
    width. That is the exact complement of the ordering arm above, which goes
    red on the four-decimal ids and green on `arithmetic-derived`. Together
    they cover all seven; separately neither does.
    """
    from prompt_regression.cli import _format_diff_text

    text = _format_diff_text(_diff_at(threshold - 1e-9, threshold))
    match = re.search(r"cosine:\s+(\S+) \(threshold (\S+)\)", text)
    assert match is not None, text
    left, right = match.groups()
    assert "." in left, text
    assert "." in right, text
    assert len(left.split(".")[1]) == len(right.split(".")[1]), (
        f"the CLI renders its two sides at different precisions ({left!r} vs "
        f"{right!r}) at threshold={threshold!r}:\n{text}"
    )


def test_the_cli_line_still_publishes_four_places_for_an_ordinary_result() -> None:
    """The width this surface publishes is its own, not the notes' (#177).

    Routing the line through a helper that hardcoded `COMPARISON_PLACES` (3)
    republished the README CLI tour's `cosine:  0.8058` as `0.806` — narrowing
    a documented number while fixing an unrelated defect, which is the
    regression `llm-eval-harness#252` shipped. `places` is a required argument
    for that reason, and this arm is what proves the CLI passes its own.

    The cosine here renders differently from the threshold at three places
    already, so nothing widens: four places is the caller's width showing
    through, not a collision being resolved.
    """
    from prompt_regression.cli import _CLI_COSINE_PLACES, _format_diff_text

    assert _CLI_COSINE_PLACES == 4
    text = _format_diff_text(_diff_at(0.8058, 0.75))
    assert "cosine:  0.8058 (threshold 0.7500)" in text, text


def test_the_notes_and_the_cli_line_keep_their_own_widths() -> None:
    """Anti-vacuity for the arm above: prove the two widths really differ.

    If both surfaces published the same number of places, `places` being a
    required parameter would be untested ceremony and a future default could
    creep back in unnoticed. They do not: the note renders three, the CLI four,
    from the same `DiffResult`.
    """
    from prompt_regression.cli import _format_diff_text

    result = _diff_at(0.0508, 0.75)
    text = _format_diff_text(result)
    assert "cosine:  0.0508 (threshold 0.7500)" in text, text
    assert "cosine 0.051 below threshold 0.750" in text, text
