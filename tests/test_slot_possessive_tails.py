"""A possessive after punctuation and an uncatalogued elision are not quotes (#301).

#297 refused an opener before a digit or a whole word from a hand list. Two
apostrophe shapes still opened a span that a plural possessive closed:
`Acme Corp.'s policy covers our customers' purchases` extracted
`s policy covers our customers` for `plan_name` because `(?<!\\w)` admits an
apostrophe after `.` or `)`, and `'bout the customers' tickets` extracted
`bout the customers` because `bout` was not on the list. A slot the answer
never stated passed the diff.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import diff_response, extract_slots
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

# The shipped refund_window_v1 spec, as in the issue.
_SPEC = {
    "plan_name": {
        "type": "string",
        "description": "Human-readable plan name the answer applies to.",
    }
}


@pytest.mark.parametrize(
    "text",
    [
        # Glued to a closing character: refused with no list.
        "Acme Corp.'s policy covers our customers' purchases",
        "The U.S.'s rules protect customers' refunds.",
        "Talk to support (Jane)'s team about customers' tickets.",
        "Acme Inc.'ll review customers' tickets.",
        "Ask the team [Ops]'d check customers' tickets.",
        # Neither a tail nor a catalogued elision: only the glue refuses it.
        "Okay.'Nuff said about the customers' tickets.",
        "Ask (Jane)'nother look at the customers' tickets.",
        # Glued to a character that also opens: refused by the tail rule.
        "Ask **Acme**'s team about customers' tickets.",
        "Ask _Acme_'s team about customers' tickets.",
        # After a space: the elision catalogue.
        "We'll talk 'bout the customers' tickets tomorrow.",
        "Ask 'round the customers' desks.",
        "It's 'cos the customers' tickets closed.",
        "It's 'cuz the customers' tickets closed.",
        "'Neath the customers' desks.",
        "'Kay, the customers' tickets closed.",
        "Nothing 'gainst the customers' wishes.",
        "Split 'tween the customers' accounts.",
        "All 'cept the customers' tickets.",
        "Come 'ere and read the customers' tickets.",
    ],
)
def test_a_possessive_tail_or_elision_is_not_a_quoted_value(text: str) -> None:
    assert extract_slots(text, _SPEC) == {}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("It's the 'Pro' plan.", "Pro"),
        ("The 'Teams' plan.", "Teams"),
        # An opening bracket, a colon and markdown emphasis still open.
        ("Pick ('Pro') now.", "Pro"),
        ("The plan is: 'Pro'.", "Pro"),
        ("The **'Pro'** plan.", "Pro"),
        # A quoted single letter is a value, not a contraction tail.
        ("Sizes 'S' and 'M' only.", "S"),
        ("Size 'M' only.", "M"),
        # A word that starts with a tail or an elision is still a value.
        ("The 'Ready' plan.", "Ready"),
        ("The 'Standard' plan.", "Standard"),
        ("The 'Roundup' plan.", "Roundup"),
        # The double-quoted value before a possessive is the value.
        ('Ask "Acme"\'s team.', "Acme"),
        # A real value after a refused opener is still found.
        ("Acme Corp.'s 'Pro' plan.", "Pro"),
        ("We'll talk 'bout the 'Pro' plan.", "Pro"),
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
        "Refunds on Acme Inc.'s tier are open for 14 days from purchase for customers' orders.",
        "Refunds on Acme Incs tier are open for 14 days from purchase for customers orders.",
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
