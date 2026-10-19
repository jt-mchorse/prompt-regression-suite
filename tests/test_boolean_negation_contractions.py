"""Every `n't` contraction negates, whichever apostrophe it is spelled with (#263).

#142 derived negation from cue + positive term instead of enumerating negated
pairs, but the cues themselves were a hand list of eleven contractions with a
straight apostrophe. Measured on main, `refund_allowed` extracted True from:

    "Refunds aren’t allowed."        (U+2019)
    "Refunds can’t be enabled."      (U+2019)
    "Refunds shouldn't be allowed."
    "Refunds haven't been enabled."
"""

from __future__ import annotations

import itertools

import pytest

from prompt_regression.diff import diff_slots

SPEC = {"refund_allowed": {"type": "boolean", "description": "whether a refund is allowed"}}
APOSTROPHES = {"straight": "'", "typographic": "’", "modifier": "ʼ"}
CONTRACTIONS = [
    "isn{a}t", "aren{a}t", "wasn{a}t", "weren{a}t", "can{a}t", "won{a}t",
    "don{a}t", "doesn{a}t", "didn{a}t", "shouldn{a}t", "couldn{a}t",
    "wouldn{a}t", "hasn{a}t", "haven{a}t", "mustn{a}t", "needn{a}t",
]  # fmt: skip
TERMS = ["allowed", "permitted", "enabled"]


def _value(text: str) -> object:
    return diff_slots(SPEC, text)[0].actual_value


@pytest.mark.parametrize(
    ("contraction", "apostrophe"),
    list(itertools.product(CONTRACTIONS, APOSTROPHES.values())),
    ids=[f"{c.format(a='_')}-{k}" for c, k in itertools.product(CONTRACTIONS, APOSTROPHES)],
)
def test_a_contraction_before_a_positive_term_is_false(contraction: str, apostrophe: str) -> None:
    cue = contraction.format(a=apostrophe)
    for term in TERMS:
        assert _value(f"Refunds {cue} {term}.") is False, f"{cue} {term}"
        assert _value(f"Refunds {cue} be {term}.") is False, f"{cue} be {term}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Refunds are allowed.", True),
        ("Yes, refunds are enabled.", True),
        ("Refunds are not allowed.", False),
        ("Refunds cannot be enabled.", False),
        ("Refunds are never permitted.", False),
        ("Refunds are denied.", False),
        ("We will look into it.", None),
    ],
)
def test_existing_phrasings_are_unchanged(text: str, expected: object) -> None:
    assert _value(text) is expected
