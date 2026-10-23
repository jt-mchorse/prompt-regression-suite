"""Inch marks are not quotes in a string slot (#290).

#235 guarded the single-quote arm of `_QUOTED_RE` and left the double-quote arm
alone, so two inch marks made a pair: `Our 12" and 16" pizzas ship today.`
extracted ` and 16` for `plan_name`, and a slot the answer never stated passed
the diff. The same text written `12-inch and 16-inch` was `missing`.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import diff_response, diff_slots, extract_slots
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

_SPEC = {"plan_name": {"type": "string", "description": "the plan tier"}}


@pytest.mark.parametrize(
    "text",
    [
        'Our 12" and 16" pizzas ship today.',
        '12" and 16"',
        'The screen is 27" wide and the stand is 8" deep.',
    ],
)
def test_inch_marks_are_not_a_quoted_value(text: str) -> None:
    (delta,) = diff_slots(_SPEC, text)
    assert (delta.status, delta.actual_value) == ("missing", None)


def test_inch_marks_match_the_spelled_out_wording() -> None:
    spelled = diff_slots(_SPEC, "Our 12-inch and 16-inch pizzas ship today.")
    marked = diff_slots(_SPEC, 'Our 12" and 16" pizzas ship today.')
    assert [d.status for d in marked] == [d.status for d in spelled] == ["missing"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A real quoted value beside the inch marks, before and after them.
        ('Our 12" and 16" pizzas ship on the "Pro" plan.', "Pro"),
        ('The "Pro" plan ships 12" and 16" pizzas.', "Pro"),
        # Controls: unchanged by #290.
        ('The "Pro plan" applies.', "Pro plan"),
        ('the "Pro" tier', "Pro"),
        # A closing quote after a digit is still a close (see `_QUOTED_RE`).
        ('the "Plan 2" tier', "Plan 2"),
        # #235's single-quote arm is untouched.
        ("It's the 'Pro' plan.", "Pro"),
    ],
)
def test_a_real_quoted_value_is_still_read(text: str, expected: str) -> None:
    assert extract_slots(text, _SPEC)["plan_name"] == expected


class _Same:
    """Every text embeds to one vector, so only the slots decide the verdict."""

    model_name = "same-vector"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


def test_a_missing_slot_fails_the_diff_despite_inch_marks() -> None:
    snapshot = Snapshot(
        id="pizza",
        prompt=Prompt(model="claude-haiku-4-5", user="Which plan tier ships pizzas free?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots=_SPEC),
        canonical=CanonicalResponse(
            text='Your plan tier is Pro. The 12" and 16" pizzas ship free with it.',
            embedding=[1.0, 0.0],
            embedding_model="same-vector",
        ),
        created_at="2026-01-01T00:00:00Z",
    )
    result = diff_response(snapshot, 'The 12" and 16" pizzas ship free with it.', embedder=_Same())
    (delta,) = result.slot_deltas
    assert delta.status == "missing"
    assert result.verdict == "fail"
