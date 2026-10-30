"""Every mark that makes ONE number between digits is refused, not just `,` (#319).

#317 (#315) made a digit-comma-digit run that is not a `,ddd` group read as
`missing`. `_NUMBER_RE` knew only `,`, so every other decimal or group mark
still split a number and the part nearest the hint read with status `ok`.
Measured on `main` 206da34, integer slot, description "days":

    '14<U+066B>5 days'          5    (Arabic decimal separator)
    "14'5 days"                 5    (apostrophe)
    '14<U+00B7>5 days'          5    (middle dot)
    "Fr. 1'250.50 total"        1    (Swiss grouping)
    '1<U+202F>000 days'         0    (narrow no-break space, SI grouping)
    Arabic-Indic 14<U+066B>5    14

A brute force of every Pd, Po, Zs, Pi and Pf codepoint `c` in `14{c}5 days`
gave `ok` for 691 of 693 (all but `,` and `.`). The marks that read as two
numbers (ranges, lists, times, fractions) are meant to stay that way; the test
at the bottom pins the exact set that no longer does.

Text is built from code points, so no invisible separator lives in this file.
"""

from __future__ import annotations

import sys
import unicodedata

import pytest

from prompt_regression.diff import diff_response, diff_slots, extract_slots
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

ARABIC_DECIMAL = chr(0x066B)
ARABIC_THOUSANDS = chr(0x066C)
MIDDLE_DOT = chr(0x00B7)
RIGHT_QUOTE = chr(0x2019)
NBSP = chr(0x00A0)
NARROW_NBSP = chr(0x202F)
THIN_SPACE = chr(0x2009)
FIGURE_SPACE = chr(0x2007)
FULLWIDTH_STOP = chr(0xFF0E)
FULLWIDTH_COMMA = chr(0xFF0C)
EN_DASH = chr(0x2013)
PRIME = chr(0x2032)
# The marks that make ONE number between digits, as code points: `_NUM_SEP` in
# diff.py, which documents why each is there. Written out here rather than
# imported, so a member dropped from the source fails the scan below.
ONE_NUMBER_MARKS = {
    chr(cp)
    for cp in (
        0x002C, 0xFF0C, 0xFE50, 0xFE10,  # comma and its compatibility forms
        0xFF0E, 0xFE52, 0x2024,  # compatibility forms of `.`
        0x0027, 0xFF07, 0x2019,  # apostrophe, fullwidth apostrophe, U+2019
        0x066B, 0x066C,  # Arabic decimal and thousands separators
        0x00B7,  # middle dot
        0x00A0, 0x202F, 0x2009, 0x2007,  # no-break, narrow no-break, thin, figure
    )
}  # fmt: skip
ARABIC_14_5 = chr(0x0661) + chr(0x0664) + ARABIC_DECIMAL + chr(0x0665)
ARABIC_DAY = chr(0x064A) + chr(0x0648) + chr(0x0645)

# Each reads as one number the grammar cannot parse: `missing`, never a part.
SPLIT_RUNS = [
    f"You have 14{ARABIC_DECIMAL}5 days.",
    "You have 14'5 days.",
    f"You have 14{MIDDLE_DOT}5 days.",
    f"You have 14{RIGHT_QUOTE}5 days.",
    "Fr. 1'250.50 total, 14'5 days.",
    f"Up to 1{NARROW_NBSP}000 days.",
    f"Up to 1{NBSP}000 days.",
    f"Up to 1{THIN_SPACE}000 days.",
    f"Up to 1{FIGURE_SPACE}000 days.",
    f"Up to 1{ARABIC_THOUSANDS}000 days.",
    f"You have 14{FULLWIDTH_STOP}5 days.",
    f"You have 14{FULLWIDTH_COMMA}5 days.",
    f"{ARABIC_14_5} {ARABIC_DAY}",
    f"Up to 1{NARROW_NBSP}000{NARROW_NBSP}000 days.",
    f"It is -14{MIDDLE_DOT}5 degrees.",
]

# Unchanged, slot description "days": (text, number value, integer value).
CONTROLS = [
    ("You have 14 days.", 14.0, 14),
    ("Up to 1,000 days.", 1000.0, 1000),
    ("Total $1,234.56 due.", 1234.56, 1234.56),
    ("Refunds take 3.5 days.", 3.5, 3.5),
    ("Pick 3 5 or 7.", 3.0, 3),  # an ASCII space can separate a list
    (f"Allow 14{EN_DASH}21 days.", 21.0, 21),  # a range is two numbers
    ("Ship 10/30 in 2 days.", 2.0, 2),
    ("Open 9:30 to 5 days.", 5.0, 5),
    (f"He is 5{PRIME}10 tall.", 5.0, 5),  # feet and inches, two quantities
    ("It's 14 days.", 14.0, 14),  # an apostrophe with no digit before it
    ("From '24 the days are long.", 24.0, 24),
    (f"Pay 30{NBSP}days later.", 30.0, 30),  # a no-break space before a word
    ("Days: 14'", 14.0, 14),  # a separator with no digit after it
]


@pytest.mark.parametrize("slot_type", ["integer", "number"])
@pytest.mark.parametrize("text", SPLIT_RUNS)
def test_a_split_number_is_missing_not_a_fragment(text: str, slot_type: str) -> None:
    spec = {"d": {"type": slot_type, "description": "days"}}
    assert extract_slots(text, spec) == {}
    [delta] = diff_slots(spec, text)
    assert delta.status == "missing"
    assert delta.is_failure


@pytest.mark.parametrize(("text", "as_number", "as_integer"), CONTROLS)
def test_a_mark_that_separates_two_numbers_still_reads(
    text: str, as_number: float, as_integer: int | float
) -> None:  # control
    assert extract_slots(text, {"n": {"type": "number", "description": "days"}}) == {"n": as_number}
    got = extract_slots(text, {"i": {"type": "integer", "description": "days"}})["i"]
    assert got == as_integer
    assert type(got) is type(as_integer)


def test_a_later_standalone_number_is_still_found_after_a_split_one() -> None:
    text = f"Rated 4{MIDDLE_DOT}5 stars, with a 30 day window."
    assert extract_slots(text, {"d": {"type": "integer"}}) == {"d": 30}


class _Same:
    """Every text embeds to one vector, so only the slots decide the verdict."""

    model_name = "same-vector"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


@pytest.mark.parametrize(
    ("number", "verdict"),
    [
        (f"14{ARABIC_DECIMAL}5", "fail"),
        ("14'5", "fail"),
        (f"14{MIDDLE_DOT}5", "fail"),
        (f"1{NARROW_NBSP}4", "fail"),
        ("14.5", "fail"),  # control
        ("14", "pass"),  # control
    ],
)
def test_a_split_window_fails_the_diff(number: str, verdict: str) -> None:
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


def _not_ok_between_digits() -> set[str]:
    spec = {"d": {"type": "integer", "description": "days"}}
    found = set()
    for cp in range(sys.maxunicode + 1):
        c = chr(cp)
        if unicodedata.category(c) not in {"Pd", "Po", "Zs", "Pi", "Pf"}:
            continue
        [delta] = diff_slots(spec, f"14{c}5 days")
        if delta.status != "ok":
            found.add(c)
    return found


def test_the_separator_set_is_exactly_the_documented_one() -> None:
    # Search the space rather than trust a hand list. Of every punctuation and
    # space codepoint between two digits, exactly `.` (read by the grammar,
    # 14.5 -> type_mismatch) and `ONE_NUMBER_MARKS` (missing) stop the slot reading
    # `ok`. Everything else reads as two numbers by decision; see the comment
    # on `_NUM_SEP`. A member dropped from the class, or a mark added without
    # a reason, fails here. Every member predates Unicode 6, so the set does
    # not move with the interpreter's Unicode version.
    assert _not_ok_between_digits() == {".", *ONE_NUMBER_MARKS}
