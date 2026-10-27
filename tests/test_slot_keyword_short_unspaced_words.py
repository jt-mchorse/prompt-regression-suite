"""A two- or three-character word in an unspaced script is a keyword (#307).

Both keyword loops kept only words with `len(w) > 3`. In spaced text that
drops `of`, `the`, `if`; in CJK, kana and Hangul it drops ordinary whole words
(`套餐`, `プラン`, `요금제`), so a slot whose description used them never
matched, and a snapshot's canonical failed its own slots. A word with an
unspaced-script edge now needs two characters; every other word keeps the
old floor.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import diff_response, extract_slots
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot


def _spec(description: str) -> dict[str, dict[str, str]]:
    return {"plan_name": {"type": "string", "description": description}}


@pytest.mark.parametrize(
    ("description", "text"),
    [
        # The issue's rows.
        ("套餐", "您的套餐是专业版。"),
        ("套餐 名称", "您的套餐是专业版。"),
        ("プラン", "プランはProです。"),
        ("요금제", "요금제는 Pro입니다."),
        # A mixed keyword: one unspaced edge is enough.
        ("V2版", "您的V2版已续订。"),
    ],
)
def test_a_short_unspaced_script_word_is_a_keyword(description: str, text: str) -> None:
    assert extract_slots(text, _spec(description)) == {"plan_name": text}


@pytest.mark.parametrize(
    ("description", "text"),
    [
        ("天", "今天是好天气。"),  # one ideograph is not a word on its own
        ("pro", "Your plan is Pro."),  # spaced words keep the `> 3` floor
        ("pro", "您的pro套餐。"),  # a short Latin word beside CJK is still spaced
    ],
)
def test_the_floor_still_drops_what_it_should(  # control
    description: str, text: str
) -> None:
    assert extract_slots(text, _spec(description)) == {}


@pytest.mark.parametrize(
    ("description", "text"),
    [
        ("plan", "Your plan is Pro."),
        ("套餐名称", "您的套餐名称是专业版。"),
    ],
)
def test_a_word_past_the_old_floor_still_matches(  # control
    description: str, text: str
) -> None:
    assert extract_slots(text, _spec(description)) == {"plan_name": text}


def test_a_short_unspaced_script_number_hint_ranks_the_numbers() -> None:
    text = "Ref 90 is on file. 退款期限为 14 天。"
    assert extract_slots(text, {"d": {"type": "integer", "description": "期限"}}) == {"d": 14}


class _Same:
    """Every text embeds to one vector, so only the slots decide the verdict."""

    model_name = "same-vector"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


@pytest.mark.parametrize(
    ("candidate", "verdict"),
    [
        ("您的套餐是专业版。", "pass"),
        ("您好，请稍后再试。", "fail"),  # control: the slot is missing
    ],
)
def test_a_cjk_canonical_satisfies_its_own_short_word_slot(candidate: str, verdict: str) -> None:
    snapshot = Snapshot(
        id="plan",
        prompt=Prompt(model="claude-haiku-4-5", user="我的套餐是什么？"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots=_spec("套餐")),
        canonical=CanonicalResponse(
            text="您的套餐是专业版。",
            embedding=[1.0, 0.0],
            embedding_model="same-vector",
        ),
        created_at="2026-01-01T00:00:00Z",
    )
    result = diff_response(snapshot, candidate, embedder=_Same())
    assert result.verdict == verdict
