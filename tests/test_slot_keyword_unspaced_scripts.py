"""A keyword edge in a script written without spaces takes no word boundary (#302).

#298 made the string-slot keyword fallback a whole-word match,
`(?<!\\w)kw s?(?!\\w)`. `\\w` matches CJK, kana, Hangul and Thai, and those
scripts put no space between words, so a CJK keyword could no longer match
inside a CJK sentence: with description `回答が対象とする プラン名`,
`プラン名はProです。` read as missing, where before #298 it matched. Only a
spaced-script edge is bounded now, and only against a spaced-script word
character, so `username` and `renamed` still do not match `name`.
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
        ("回答が対象とする プラン名", "プラン名はProです。"),
        ("回答が対象とする プラン名", "ご契約のプラン名：Pro。"),
        # Chinese, Korean (particles attach to the word), Thai.
        ("您的 订阅套餐名称", "您的订阅套餐名称是Pro。"),
        ("서비스요금제", "귀하의 서비스요금제는 Pro입니다."),
        ("แผนบริการ", "แผนบริการของคุณคือ Pro"),
        # A Latin keyword inside CJK text: a script change is a word edge.
        ("the plan", "您的plan是Pro。"),
        ("the plan", "ご契約のplansはProです。"),
        # A mixed keyword: the Latin edge is bounded, the CJK edge is not.
        ("Pro套餐", "您的Pro套餐已续订。"),
        # Spaced text is unchanged.
        ("Human-readable plan name", "Your plan is Pro."),
    ],
)
def test_a_keyword_in_an_unspaced_script_matches(description: str, text: str) -> None:
    assert extract_slots(text, _spec(description)) == {"plan_name": text}


@pytest.mark.parametrize(
    ("description", "text"),
    [
        # #298's rows.
        ("Human-readable plan name", "I'd need your username before I can look that up."),
        ("Human-readable plan name", "That was renamed last year."),
        ("Human-readable plan name", "The planet is not covered."),
        # A Latin edge next to a Latin letter is still refused inside CJK text.
        ("the plan", "您的planet是Pro。"),
        ("the plan", "您的Explan是Pro。"),
        ("Pro套餐", "您的xPro套餐已续订。"),
        # A CJK keyword the text does not contain.
        ("回答が対象とする プラン名", "ユーザー名はabcです。"),
    ],
)
def test_a_spaced_edge_inside_another_word_still_does_not_match(
    description: str, text: str
) -> None:
    assert extract_slots(text, _spec(description)) == {}


class _Same:
    """Every text embeds to one vector, so only the slots decide the verdict."""

    model_name = "same-vector"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


def test_a_cjk_canonical_passes_its_own_diff() -> None:
    spec = _spec("回答が対象とする プラン名")
    text = "ご契約のプラン名：Pro。"
    snapshot = Snapshot(
        id="plan",
        prompt=Prompt(model="claude-haiku-4-5", user="プラン名は？"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots=spec),
        canonical=CanonicalResponse(text=text, embedding=[1.0, 0.0], embedding_model="same-vector"),
        created_at="2026-01-01T00:00:00Z",
    )
    result = diff_response(snapshot, text, embedder=_Same())
    (delta,) = result.slot_deltas
    assert delta.status == "ok"
    assert result.verdict == "pass"
