"""A string slot's keyword fallback matches whole words only (#298).

The fallback searched for each description keyword as a bare substring, so the
`name` of "plan name" was found inside `username` and `renamed`, and the slot
read as present with the whole sentence as its value. A slot the answer never
stated passed the diff, while a control without the substring failed. The
keywords were also split with their punctuation attached, so the shipped
`eligibility_caveat` description gave `caveat,` and `fees").`, which no
response contains as written.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import diff_response, extract_slots
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

# The shipped descriptions (examples/snapshots/refund_window_v1.yml).
_PLAN = {
    "plan_name": {
        "type": "string",
        "description": "Human-readable plan name the answer applies to.",
    }
}
_CAVEAT = {
    "eligibility_caveat": {
        "type": "string",
        "description": 'Free-text caveat, if any (e.g., "minus usage fees").',
    }
}


@pytest.mark.parametrize(
    "text",
    [
        "I'd need your username before I can look that up.",
        "That was renamed last year; please contact support.",
        "The planet is not covered.",
        "Sorry, I can't look that up right now.",
    ],
)
def test_a_keyword_inside_another_word_is_not_the_slot(text: str) -> None:
    assert extract_slots(text, _PLAN) == {}


@pytest.mark.parametrize(
    "text",
    [
        "Your plan renews monthly.",
        "Both plans renew monthly.",
        "Plan name: Pro.",
        "Your PLAN renews monthly.",
        "The plan_name field is Pro.",
    ],
)
def test_a_whole_keyword_still_matches(text: str) -> None:
    assert extract_slots(text, _PLAN) == {"plan_name": text}


@pytest.mark.parametrize(
    "text",
    [
        "One caveat applies to annual plans.",
        "Refunds exclude processing fees.",
    ],
)
def test_a_keyword_written_with_punctuation_in_the_description_matches(text: str) -> None:
    assert extract_slots(text, _CAVEAT) == {"eligibility_caveat": text}


class _Same:
    """Every text embeds to one vector, so only the slots decide the verdict."""

    model_name = "same-vector"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


@pytest.mark.parametrize(
    "candidate",
    [
        "Refunds on that username are open for 14 days.",
        "Refunds are open for 14 days.",
    ],
)
def test_a_missing_slot_fails_the_diff_with_or_without_the_substring(candidate: str) -> None:
    snapshot = Snapshot(
        id="refund",
        prompt=Prompt(model="claude-haiku-4-5", user="What's the refund window?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots=_PLAN),
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
