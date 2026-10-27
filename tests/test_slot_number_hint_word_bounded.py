"""A number slot's hint words match whole words only (#306).

`_extract_number` prefers the number nearest a description word, and found
that word with a substring search. The shipped `refund_days` description
gives the hint `days`, which sits inside `Sundays`, `Holidays`, `weekdays`
and `birthdays`; the number beside the false hit won. With #211, a fractional
value in an integer slot is a `type_mismatch`, so a candidate saying
"open Sundays 9 to 5 ... a 14.5 day refund window" read `9` and passed, while
the same candidate with `weekends` failed. #298 already made the string-slot
keywords whole words; this applies the same `_keyword_pattern` here.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import diff_response, extract_slots
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

# The shipped description (examples/snapshots/refund_window_v1.yml).
_REFUND = {
    "refund_days": {
        "type": "integer",
        "description": "Number of days from purchase during which a refund can be requested.",
    }
}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The issue's two rows.
        ("Holidays: 14 per year. Pro-plan purchases can be refunded within 30 days.", 30),
        (
            "Phone support is open Sundays 9 to 5. The Pro plan has a 14.5 day refund window.",
            14.5,
        ),
        ("Support answers on weekdays 9 to 5. Refunds are open for 30 days.", 30),
        ("Birthdays: 2 free credits. Refunds are open for 30 days.", 30),
    ],
)
def test_a_hint_inside_another_word_does_not_rank_the_numbers(
    text: str, expected: int | float
) -> None:
    assert extract_slots(text, _REFUND) == {"refund_days": expected}


@pytest.mark.parametrize(
    ("text", "hint", "expected"),
    [
        ("Ref 9. Refunds are open for 30 days.", "days", 30),
        ("Ref 9. Refunds are open for 30 DAYS.", "days", 30),
        ("Ref 9. Refunds are open for 30 Days.", "Days", 30),
        ("Numbers: 30. Ref 9 is on file.", "Number", 30),  # plural `s`, as #298
        ("Ref 90 is on file. 退款天数为 14 天。", "退款天数", 14),  # unspaced script, #302
    ],
)
def test_a_whole_hint_word_still_ranks_the_numbers(  # control
    text: str, hint: str, expected: int
) -> None:
    assert extract_slots(text, {"d": {"type": "integer", "description": hint}}) == {"d": expected}


def test_a_hint_written_with_punctuation_in_the_description_matches() -> None:
    # The shipped description ends `requested.`; no response contains that as a
    # word with the stop attached mid-sentence, so it never ranked anything.
    text = "Ref 5 is on file. A refund can be requested up to 30 days later."
    spec = {"d": {"type": "integer", "description": "requested."}}
    assert extract_slots(text, spec) == {"d": 30}


class _Same:
    """Every text embeds to one vector, so only the slots decide the verdict."""

    model_name = "same-vector"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


@pytest.mark.parametrize("day_word", ["Sundays", "weekends"])
def test_a_fractional_window_fails_the_diff_whatever_the_opening_hours_say(day_word: str) -> None:
    snapshot = Snapshot(
        id="refund",
        prompt=Prompt(model="claude-haiku-4-5", user="What's the refund window?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots=_REFUND),
        canonical=CanonicalResponse(
            text="Phone support is open weekends 9 to 5. The Pro plan has a 14 day refund window.",
            embedding=[1.0, 0.0],
            embedding_model="same-vector",
        ),
        created_at="2026-01-01T00:00:00Z",
    )
    candidate = (
        f"Phone support is open {day_word} 9 to 5. The Pro plan has a 14.5 day refund window."
    )
    result = diff_response(snapshot, candidate, embedder=_Same())
    (delta,) = result.slot_deltas
    assert delta.actual_value == 14.5
    assert delta.status == "type_mismatch"
    assert result.verdict == "fail"
