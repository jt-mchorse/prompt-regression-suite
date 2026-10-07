"""Number and integer slots read whole numeric tokens (#211).

`_INTEGER_RE` was `-?\\d+\\b`, which matches each HALF of a decimal, and neither
pattern knew a thousands group. Measured on `main` with the spec
`{"n": {"type": "integer", "description": "days"}}` (a hunt agent, re-run here):

    "Refunds take 3.5 days."   -> {'n': 5}  status ok
    "2.5 business days"        -> {'n': 5}
    "1,000 days"               -> {'n': 0}  (integer AND number slots)

#100 fixed the leading-decimal case for numbers and noted "`_INTEGER_RE` is
unchanged (integers have no leading decimal)" -- integers have no decimal at
all, which is why a decimal in an integer slot must be reported, not mined.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import diff_slots, extract_slots

INT = {"n": {"type": "integer", "description": "days"}}
NUM = {"n": {"type": "number", "description": "days"}}


@pytest.mark.parametrize("text", ["Refunds take 3.5 days.", "2.5 business days"])
def test_a_decimal_in_an_integer_slot_is_a_type_mismatch_not_its_last_digits(text: str) -> None:
    (delta,) = diff_slots(INT, text)
    assert delta.status == "type_mismatch"
    assert delta.actual_value in (3.5, 2.5)


@pytest.mark.parametrize(
    ("text", "int_value", "num_value"),
    [
        ("1,000 days", 1000, 1000.0),
        ("12,345,678 days", 12345678, 12345678.0),
        ("1,000.5 days", 1000.5, 1000.5),
    ],
)
def test_a_thousands_group_is_one_number(text: str, int_value: object, num_value: float) -> None:
    assert extract_slots(text, INT)["n"] == int_value
    assert extract_slots(text, NUM)["n"] == num_value


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Refunds take 3 days.", 3),
        ("3.0 days", 3),  # an integral decimal is the integer
        ("Order 4812 placed. Refunds take 3 days.", 3),  # nearest the hint, as before
        ("W-2 form, 14-day window", 14),  # #79's hyphen guards hold
        ("-30 days", -30),
    ],
)
def test_integer_slots_that_must_not_change(text: str, expected: int) -> None:
    value = extract_slots(text, INT)["n"]
    assert value == expected
    assert isinstance(value, int)
    (delta,) = diff_slots(INT, text)
    assert delta.status == "ok"


@pytest.mark.parametrize(
    ("text", "expected"), [(".05 days", 0.05), ("-.5 days", -0.5), ("2.5 days", 2.5)]
)
def test_number_slots_that_must_not_change(text: str, expected: float) -> None:
    assert extract_slots(text, NUM)["n"] == expected
