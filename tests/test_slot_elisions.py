"""Elisions and vulgar-fraction inch marks are not quotes in a string slot (#297).

#235 guarded an apostrophe inside a word, and #290 an inch mark after a digit.
Neither saw a word-initial elision opening a span and a plural possessive
closing it: `back in the '90s our customers' records` extracted
`90s our customers` for `plan_name`, `'til the customers' tickets` extracted
`til the customers`, and `3½" and 5¼"` extracted ` and 5¼` because a vulgar
fraction is not `\\d`. A slot the answer never stated passed the diff.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import diff_response, extract_slots
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

_SPEC = {"plan_name": {"type": "string", "description": "the tier"}}


@pytest.mark.parametrize(
    "text",
    [
        "back in the '90s our customers' records were kept on paper.",
        "Sorry, we can't say 'til the customers' tickets close.",
        'Our 3½" and 5¼" disks ship today.',
        "Since '24 our customers' records are digital.",
        "Tell 'em the customers' records are safe.",
        "It's rock 'n' roll for the customers' records.",
        "'Cause the customers' records are safe.",
        'The ⅞" and ⅜" bolts ship today.',
    ],
)
def test_an_elision_or_fraction_mark_is_not_a_quoted_value(text: str) -> None:
    assert extract_slots(text, _SPEC) == {}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("It's the 'Pro' plan.", "Pro"),
        ('The "Pro Plus" plan.', "Pro Plus"),
        # A real value may end in `s`: the possessive closer is not refused.
        ("The 'Teams' plan.", "Teams"),
        ('The "Teams" plan.', "Teams"),
        # Only a WHOLE elided word is refused, not a word that starts with one.
        ("The 'Tilde' plan.", "Tilde"),
        ("The 'Enterprise' plan.", "Enterprise"),
        # A real value after a refused elision is still found.
        ("Back in the '90s the 'Pro' plan was new.", "Pro"),
        ("Wait 'til the 'Pro' plan renews.", "Pro"),
        ('Our 3½" disks ship on the "Pro" plan.', "Pro"),
        # #290's controls are unchanged.
        ('the "Plan 2" tier', "Plan 2"),
    ],
)
def test_a_real_quoted_value_is_still_read(text: str, expected: str) -> None:
    assert extract_slots(text, _SPEC)["plan_name"] == expected


class _Same:
    """Every text embeds to one vector, so only the slots decide the verdict."""

    model_name = "same-vector"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


@pytest.mark.parametrize(
    "candidate",
    [
        "Refunds in the '90s on our customers' accounts are open for 14 days.",
        "Refunds in the 90s on our customers accounts are open for 14 days.",
    ],
)
def test_a_missing_slot_fails_the_diff_with_or_without_apostrophes(candidate: str) -> None:
    snapshot = Snapshot(
        id="refund",
        prompt=Prompt(model="claude-haiku-4-5", user="What's the refund window?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots=_SPEC),
        canonical=CanonicalResponse(
            text="Refunds on the 'Pro' plan are open for 14 days.",
            embedding=[1.0, 0.0],
            embedding_model="same-vector",
        ),
        created_at="2026-01-01T00:00:00Z",
    )
    result = diff_response(snapshot, candidate, embedder=_Same())
    (delta,) = result.slot_deltas
    assert delta.status == "missing"
    assert result.verdict == "fail"
