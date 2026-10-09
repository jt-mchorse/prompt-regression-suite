"""A string slot's sentence ends where a sentence ends, not at every '.' (#225).

`_sentence_around` used `text.rfind(".")` / `text.find(".")` plus newlines, so
a decimal point was a boundary and `?`, `!` and `。` were not. Measured on main
through `extract_slots`:

    'Our refund policy allows 3.5 days. Contact ...'  -> 'Our refund policy allows 3.'
    'Version 2.0 of the refund policy applies.'       -> '0 of the refund policy applies.'
    'Is that allowed? The refund policy is strict. …' -> 'Is that allowed? The refund policy is strict.'
"""

from __future__ import annotations

import pytest

from prompt_regression import extract_slots
from prompt_regression.diff import diff_slots

SPEC = {"policy": {"type": "string", "description": "refund policy"}}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Our refund policy allows 3.5 days. Contact support for more.",
            "Our refund policy allows 3.5 days.",
        ),
        ("Version 2.0 of the refund policy applies.", "Version 2.0 of the refund policy applies."),
        ("Is that allowed? The refund policy is strict. Thanks.", "The refund policy is strict."),
        ("Great news! The refund policy covers 30 days.", "The refund policy covers 30 days."),
        ("Wait… The refund policy changed.", "The refund policy changed."),
        ("退款很快。The refund policy covers 30 days.", "The refund policy covers 30 days."),
        ("Refund policy: 30 days！其他。", "Refund policy: 30 days！"),
        ("अच्छा है। The refund policy is new।", "The refund policy is new।"),
        ("The refund policy\nis new.", "The refund policy"),
        ("First line.\nThe refund policy is new", "The refund policy is new"),
    ],
)
def test_the_slot_is_the_sentence_holding_the_keyword(text: str, expected: str) -> None:
    assert extract_slots(text, SPEC)["policy"] == expected


def test_a_decimal_in_the_slot_is_reported_whole() -> None:
    (delta,) = diff_slots(SPEC, "Under the refund policy you get 3.5 days. Other text.")
    assert delta.status == "ok"
    assert delta.actual_value == "Under the refund policy you get 3.5 days."


def test_a_quoted_value_still_wins() -> None:
    assert extract_slots('The refund policy is "30 days". Done.', SPEC)["policy"] == "30 days"
