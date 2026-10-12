"""A terminator followed by closing punctuation ends a slot's sentence (#239).

#225's boundary was a terminator run before whitespace, so `.)`, `.”`, `.]`,
`.»` and `。」` were not boundaries and the previous sentence came along with
the slot value. The closer set is rag-production-kit's (#262 / rag#320).
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import _CLOSERS, _sentence_around, extract_slots

_SPEC = {"contact": {"type": "string", "description": "support email"}}
_SECOND = "Contact support at help@x.com."


@pytest.mark.parametrize("closers", list(_CLOSERS) + [")]", "”)", "**"])
def test_terminator_then_closers_ends_the_sentence(closers: str) -> None:
    text = f"Refunds are final.{closers} {_SECOND}"
    assert extract_slots(text, _SPEC)["contact"] == _SECOND


def test_a_cjk_full_stop_keeps_its_closer() -> None:
    text = "退款不可撤销。」 " + _SECOND
    assert extract_slots(text, _SPEC)["contact"] == _SECOND
    assert _sentence_around(text, 2) == "退款不可撤销。」"


@pytest.mark.parametrize(
    ("text", "idx_word", "expected"),
    [
        ("The window is 3.5 days long. Contact support.", "window", "The window is 3.5 days long."),
        ("Is it allowed? Contact support.", "Contact", "Contact support."),
        ("退款。联系支持。", "联系", "联系支持。"),
        ("(see policy) Contact support.", "Contact", "(see policy) Contact support."),
    ],
)
def test_225s_cases_are_unchanged(text: str, idx_word: str, expected: str) -> None:
    assert _sentence_around(text, text.index(idx_word)) == expected
