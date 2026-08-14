"""`_extract_boolean` must not invert a negated positive (#142).

The extractor checks negatives before positives so "not allowed" wins over the
lone "allowed". But `_BOOL_FALSE_RE` spelled out `not\\s+allowed` — the negated
form of exactly one of the five terms in `_BOOL_TRUE_RE` — and recognised only
the bare word `not` as a cue. Seven common phrasings therefore fell through to
the positive branch and extracted as `True`, the precise inversion that
ordering exists to prevent.

In a repo whose job is deciding whether model output regressed, an inverted
boolean slot is not a noisy diff: it is a confidently wrong verdict, in either
direction. Coverage before this was one test on `"Yes, refunds are allowed."`.
"""

from __future__ import annotations

import pytest

from prompt_regression.diff import _extract_boolean, extract_slots


def _b(text: str) -> bool | None:
    """`_extract_boolean` takes already-lowercased text, as its callers pass."""
    return _extract_boolean(text.lower())


# ---------------------------------------------------------------------------
# The seven confirmed inversions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "not permitted",
        "not enabled",
        "it is not true",
        "the answer is not yes",
        "that is never allowed",
        "isn't allowed",
        "cannot be enabled",
    ],
)
def test_negated_positives_are_false(text):
    assert _b(text) is False


def test_negation_reaches_across_short_filler():
    """`cannot be enabled` and `is not currently permitted` are both in window."""
    assert _b("the feature is not currently permitted") is False
    assert _b("this cannot be enabled") is False


def test_negation_window_is_bounded():
    """An unrelated `not` far from the term must not invert the sentence.

    Unbounded negation scope would be worse than the bug it fixes — it would
    start inverting any sentence that happens to contain a `not`.
    """
    text = "refunds are not the subject of this policy, however processing is allowed"
    assert _b(text) is True


# ---------------------------------------------------------------------------
# Locks on everything that was already correct
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("yes", True),
        ("true", True),
        ("allowed", True),
        ("permitted", True),
        ("enabled", True),
        ("no", False),
        ("false", False),
        ("not allowed", False),
        ("refused", False),
        ("denied", False),
        ("disabled", False),
    ],
)
def test_bare_polarity_words_are_unchanged(text, expected):
    assert _b(text) is expected


def test_no_longer_permitted_stays_false():
    """Right today only because `\\bno\\b` matches inside `no longer`.

    Pinned because the fix must not accidentally depend on, or break, that
    incidental path.
    """
    assert _b("no longer permitted") is False


def test_text_without_a_polarity_word_is_none():
    assert _b("the request was approved") is None
    assert _b("") is None


@pytest.mark.parametrize("text", ["not refused", "not denied", "not disabled"])
def test_negated_negatives_are_deliberately_unchanged(text):
    """Still `False`, and that is a decision rather than an oversight.

    Flipping a negated negative is a genuine semantic judgement for a heuristic
    extractor — "not denied" is not the same claim as "allowed" — the phrasings
    are much rarer, and changing it would alter existing behaviour rather than
    repair a stated invariant. Raised as a question on #142 instead.
    """
    assert _b(text) is False


# ---------------------------------------------------------------------------
# Through the public surface
# ---------------------------------------------------------------------------


def test_extract_slots_reports_false_for_a_negated_answer():
    slots = {"allowed": {"type": "boolean", "description": "is allowed"}}

    assert extract_slots("No, refunds are not permitted.", slots) == {"allowed": False}


def test_extract_slots_still_reports_true_for_the_positive_case():
    """The one pre-existing boolean test, re-pinned here."""
    slots = {"allowed": {"type": "boolean", "description": "is allowed"}}

    assert extract_slots("Yes, refunds are allowed.", slots) == {"allowed": True}
