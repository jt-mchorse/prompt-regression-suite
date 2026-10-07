"""Slot extraction positions survive text whose lower() changes length (#213).

Both the number and the string extractors found the hint word in
`text.lower()` and then indexed the ORIGINAL `text` with that position.
`"İ".lower()` is two characters, so every `İ` before the hint shifted it right.
Measured on `main` (a hunt agent, re-run here):

    "Order 4812 placed. {30 x İ} Delivery takes 3 days. Ref 90."
        integer slot "delivery days" -> 90   (30 x "x" in its place -> 3)
    "İİİİİİİİİİ. Reason ok. Next sentence here."
        string slot "reason"         -> 'Next sentence here.'  ('I' x 10 -> 'Reason ok.')
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import extract_slots

ETA = {"eta": {"type": "integer", "description": "delivery days"}}
REASON = {"r": {"type": "string", "description": "reason"}}


@pytest.mark.parametrize("pad", ["x" * 30, "İ" * 30, "İstanbul İade " * 5, "ẞ" * 30])
def test_the_number_nearest_the_hint_is_found_whatever_precedes_it(pad: str) -> None:
    text = f"Order 4812 placed. {pad} Delivery takes 3 days. Ref 90."
    assert extract_slots(text, ETA) == {"eta": 3}


@pytest.mark.parametrize("pad", ["IIIIIIIIII", "İİİİİİİİİİ"])
def test_the_string_slot_returns_the_hint_sentence(pad: str) -> None:
    assert extract_slots(f"{pad}. Reason ok. Next sentence here.", REASON) == {"r": "Reason ok."}


def test_the_hint_is_still_matched_case_insensitively(  # control
) -> None:
    assert extract_slots("DELIVERY takes 4 days, ref 99.", ETA) == {"eta": 4}
