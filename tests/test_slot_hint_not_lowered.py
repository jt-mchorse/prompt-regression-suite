"""The slot description hint is matched as written, not after lower() (#215).

`extract_slots` lower-cased the description before `_find_ci` searched for it
case-insensitively. `"İ".lower()` is `i` + U+0307, which `re.IGNORECASE` does
not match against `İ`, so a hint word containing `İ` was never found -- even
when the response contained exactly that word. Measured on `main`:

    "Ref 90 for your records, thank you. İade süresi 14 gün."
                                   integer slot, description "İade" -> 90
    "Kargo hazır. İstanbul deposundan gönderilir."
                                   string slot, description "İstanbul" -> missing

The same word as the slot NAME (not lowered) was already found.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import diff_slots, extract_slots

REFUND = "Ref 90 for your records, thank you. İade süresi 14 gün."
CARGO = "Kargo hazır. İstanbul deposundan gönderilir."


def test_an_integer_hint_containing_dotted_capital_i_is_found() -> None:
    assert extract_slots(REFUND, {"d": {"type": "integer", "description": "İade"}}) == {"d": 14}


def test_a_number_hint_containing_dotted_capital_i_is_found() -> None:
    assert extract_slots(REFUND, {"d": {"type": "number", "description": "İade"}}) == {"d": 14.0}


def test_a_string_hint_containing_dotted_capital_i_is_found() -> None:
    spec = {"x": {"type": "string", "description": "İstanbul"}}
    assert extract_slots(CARGO, spec) == {"x": "İstanbul deposundan gönderilir."}
    [delta] = diff_slots(spec, CARGO)
    assert delta.status == "ok"


def test_the_description_matches_like_the_slot_name_already_did() -> None:  # control
    by_name = extract_slots(CARGO, {"İstanbul": {"type": "string"}})
    by_hint = extract_slots(CARGO, {"x": {"type": "string", "description": "İstanbul"}})
    assert by_name == {"İstanbul": "İstanbul deposundan gönderilir."}
    assert by_hint == {"x": by_name["İstanbul"]}


@pytest.mark.parametrize("hint", ["ref", "REF", "Ref"])
def test_an_ascii_hint_still_matches_case_insensitively(hint: str) -> None:  # control
    text = "Delivery takes 3 days in total, as stated above. Reference 90."
    assert extract_slots(text, {"d": {"type": "integer", "description": f"{hint}erence"}}) == {
        "d": 90
    }
