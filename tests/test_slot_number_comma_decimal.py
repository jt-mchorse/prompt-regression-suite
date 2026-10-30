"""A comma decimal is never re-read as the digits after the comma (#315).

#211 made an integer slot read `3.5 days` as the whole token, and #217 made
the end of a token refuse to stop inside it. Both knew only a `,ddd` group as
a comma. A comma decimal (de/fr/es/pt/ru/it) stopped the match after `14`,
and nothing refused a start straight after `digit,`, so the digits after the
comma were matched on their own. Measured on `main` 5191cbf:

    'You have 14,5 days'     integer 5    number 5.0    status ok
    '14,50 days'             integer 50   number 50.0
    '1,0000 days'            integer 0    number 0.0

A digit-comma-digit run that is not a valid `,ddd` grouping now reads as
`missing`, the same as a glued number (#217). Reading `14,5` as 14.5 would be
a locale decision; this does not make it.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import diff_response, diff_slots, extract_slots
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

COMMA_RUNS = [
    "You have 14,5 days.",
    "You have 1,5 days.",
    "Refunds take 14,50 days.",
    "Sie haben 14,5 Tage.",
    "Up to 1,0000 days.",
    "Up to 1,000,5 days.",
    "It is -14,5 degrees.",
]

# Inputs whose extraction must not change: (text, number value, integer value).
CONTROLS = [
    ("You have 14 days.", 14.0, 14),
    ("Up to 1,000 days.", 1000.0, 1000),
    ("Up to 12,345,678 days.", 12345678.0, 12345678),
    ("Total $1,234.56 due.", 1234.56, 1234.56),
    ("Refunds take 3.5 days.", 3.5, 3.5),
    ("Pick 3, 5 or 7.", 3.0, 3),
    ("In 2026, 14 days.", 2026.0, 2026),
    ("Days: 14,", 14.0, 14),
]


@pytest.mark.parametrize("slot_type", ["integer", "number"])
@pytest.mark.parametrize("text", COMMA_RUNS)
def test_a_comma_decimal_is_missing_not_its_tail(text: str, slot_type: str) -> None:
    spec = {"d": {"type": slot_type, "description": "days"}}
    assert extract_slots(text, spec) == {}
    [delta] = diff_slots(spec, text)
    assert delta.status == "missing"
    assert delta.is_failure


@pytest.mark.parametrize(("text", "as_number", "as_integer"), CONTROLS)
def test_a_comma_that_is_not_a_decimal_still_reads(
    text: str, as_number: float, as_integer: int | float
) -> None:  # control
    assert extract_slots(text, {"n": {"type": "number"}}) == {"n": as_number}
    got = extract_slots(text, {"i": {"type": "integer"}})["i"]
    assert got == as_integer
    assert type(got) is type(as_integer)


def test_a_later_standalone_number_is_still_found_after_a_comma_decimal() -> None:
    text = "Rated 4,5 stars, with a 30 day window."
    assert extract_slots(text, {"d": {"type": "integer"}}) == {"d": 30}


class _Same:
    """Every text embeds to one vector, so only the slots decide the verdict."""

    model_name = "same-vector"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


@pytest.mark.parametrize(
    ("number", "verdict"), [("14,5", "fail"), ("14.5", "fail"), ("14", "pass")]
)
def test_a_comma_decimal_window_fails_the_diff(number: str, verdict: str) -> None:
    slots = {"refund_days": {"type": "integer", "description": "days in the refund window"}}
    snapshot = Snapshot(
        id="refund",
        prompt=Prompt(model="claude-haiku-4-5", user="What's the refund window?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots=slots),
        canonical=CanonicalResponse(
            text="The Pro plan has a 14 day refund window.",
            embedding=[1.0, 0.0],
            embedding_model="same-vector",
        ),
        created_at="2026-01-01T00:00:00Z",
    )
    result = diff_response(
        snapshot, f"The Pro plan has a {number} day refund window.", embedder=_Same()
    )
    assert result.verdict == verdict
