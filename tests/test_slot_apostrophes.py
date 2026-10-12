"""Apostrophes are not quotes in a string slot (#235).

`_QUOTED_RE` paired any two apostrophes, so contractions and possessives read
as a quoted value: `I don't know the policy and I can't say.` extracted
`t know the policy and I can` for `plan_name`, and a slot the answer never
stated passed the diff (fail/exit 1 became pass/exit 0). `It's the 'Pro' plan.`
read `s the ` instead of `Pro`.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import diff_response, extract_slots
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

_SPEC = {
    "plan_name": {
        "type": "string",
        "description": "Human-readable plan name the answer applies to.",
    }
}


@pytest.mark.parametrize(
    "text",
    [
        "I don't know the policy and I can't say.",
        "We're sorry, it's unclear and we can't confirm.",
        "The team's answer: the customer's request isn't covered.",
    ],
)
def test_contractions_and_possessives_are_not_a_quoted_value(text: str) -> None:
    value = extract_slots(text, _SPEC).get("plan_name")
    # No quoted span. The only remaining route is the documented keyword
    # fallback, which returns the whole sentence around a hint word, never a
    # fragment cut at an apostrophe.
    assert value is None or value == text, value


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("It's the 'Pro' plan.", "Pro"),
        ("Say 'yes'.", "yes"),
        ("'Pro' it is.", "Pro"),
        ('The "Pro" plan.', "Pro"),
        ("The plan is 'Team Plus'", "Team Plus"),
    ],
)
def test_a_real_quoted_value_is_still_read(text: str, expected: str) -> None:
    assert extract_slots(text, _SPEC)["plan_name"] == expected


class _Same:
    """Every text embeds to one vector, so only the slots decide the verdict."""

    model_name = "same-vector"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


def test_a_missing_slot_fails_the_diff_whatever_the_wording() -> None:
    snapshot = Snapshot(
        id="refund",
        prompt=Prompt(model="claude-haiku-4-5", user="What's the refund window for the Pro plan?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots=_SPEC),
        canonical=CanonicalResponse(
            text='The "Pro" plan has a 14-day refund window.',
            embedding=[1.0, 0.0],
            embedding_model="same-vector",
        ),
        created_at="2026-01-01T00:00:00Z",
    )
    plain = diff_response(snapshot, "I do not know the policy and I can not say.", embedder=_Same())
    contracted = diff_response(
        snapshot, "I don't know the policy and I can't say.", embedder=_Same()
    )
    assert plain.verdict == "fail"
    assert contracted.verdict == plain.verdict
