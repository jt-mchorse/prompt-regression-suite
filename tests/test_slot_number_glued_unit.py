"""A number glued to a unit is never read as a truncated prefix (#217).

`_NUMBER_RE` ended in `\\b`. A decimal or thousands-grouped number glued to a
unit fails `\\b` at its real end, so the regex backtracked to a shorter match
that passes it. Measured on `main`:

    'The dose is 2.5mg daily.'   number 2.0 / integer 2   status ok
    'Ship 1,000kg max.'          number 1.0 / integer 1   status ok
    'Take 30mg.'                 missing (the integer neighbour, already loud)

A glued token now reads as `missing`, like `30mg`, instead of a prefix.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import diff_slots, extract_slots

GLUED = [
    "The dose is 2.5mg daily.",
    "Storage: 3.5GB.",
    "It is 1.5x faster.",
    "Ship 1,000kg max.",
    "Pay 12.99USD now.",
    "Version 2.1.3 shipped.",
]

# Inputs whose extraction must not change: (text, number value, integer value).
CONTROLS = [
    ("Refunds take 3.5 days.", 3.5, 3.5),
    ("Up to 1,000 days.", 1000.0, 1000),
    ("It costs 5.", 5.0, 5),
    ("A 14-day window.", 14.0, 14),
    ("About 30% off.", 30.0, 30),
    ("Total $1,234.56 due.", 1234.56, 1234.56),
    ("Rate .5 today.", 0.5, 0.5),
    ("Take 30mg, then 4 more.", 4.0, 4),
]


@pytest.mark.parametrize("slot_type", ["integer", "number"])
@pytest.mark.parametrize("text", GLUED)
def test_a_glued_number_is_missing_not_a_prefix(text: str, slot_type: str) -> None:
    spec = {"n": {"type": slot_type}}
    assert extract_slots(text, spec) == {}
    [delta] = diff_slots(spec, text)
    assert delta.status == "missing"


@pytest.mark.parametrize(("text", "as_number", "as_integer"), CONTROLS)
def test_a_standalone_number_still_reads_whole(
    text: str, as_number: float, as_integer: int | float
) -> None:  # control
    assert extract_slots(text, {"n": {"type": "number"}}) == {"n": as_number}
    got = extract_slots(text, {"i": {"type": "integer"}})["i"]
    assert got == as_integer
    assert type(got) is type(as_integer)


def test_a_long_integer_ending_a_sentence_keeps_every_digit() -> None:  # control
    raw = "9" * 40
    assert extract_slots(f"The count is {raw}.", {"n": {"type": "integer"}}) == {"n": int(raw)}


def test_a_later_standalone_number_is_still_found_after_a_glued_one() -> None:
    assert extract_slots("Take 2.5mg twice, for 7 days.", {"n": {"type": "integer"}}) == {"n": 7}
