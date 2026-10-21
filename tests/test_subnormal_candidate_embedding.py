"""A subnormal-norm candidate vector must not fail open (#277).

#272 refuses a stored embedding whose sum of squares is subnormal, because the
norm keeps only a few significant bits. The candidate vector comes from a BYO
embedder at diff time and never passes that check. Its imprecise norm inflated
the score, and the clamp in `cosine()` capped it at 1.0. A candidate drifted
from 14-day to 30-day (true cosine 0.8182), embedded at scale 9.0157e-162,
scored 1.0 and PASSED. `cosine()` now rescales such a vector by its max-abs
component, so the score is the scale-free one.
"""

from __future__ import annotations

import math

import pytest

from prompt_regression.diff import HashEmbedder, cosine, diff_response, score_semantic_categories
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

CANON = "Pro plan customers get a 14-day refund window from the purchase date."
DRIFT = "Pro plan customers get a 30-day refund window from the purchase date."

# Found by a scale sweep on origin/main 376609b: the drifted candidate scored
# exactly 1.0 here. Its sum of squares (~8e-323) is subnormal.
FAIL_OPEN_K = 9.015711376059829e-162

_BASE = HashEmbedder()
TRUE_DRIFT = cosine(_BASE.embed(DRIFT), _BASE.embed(CANON))


class _ScaledEmbedder:
    """HashEmbedder output times `k`, under the same model name (no D-006 refusal)."""

    def __init__(self, k: float) -> None:
        self.k = k

    @property
    def model_name(self) -> str:
        return _BASE.model_name

    def embed(self, text: str) -> list[float]:
        return [x * self.k for x in _BASE.embed(text)]


def _snapshot() -> Snapshot:
    return Snapshot(
        id="refund",
        prompt=Prompt(model="m", user="u"),
        response_shape=ResponseShape(),
        canonical=CanonicalResponse(
            text=CANON, embedding=_BASE.embed(CANON), embedding_model=_BASE.model_name
        ),
    )


def test_the_drift_is_real_drift() -> None:
    # Control: the pair sits below the default 0.85 threshold at scale 1.
    assert 0.8 < TRUE_DRIFT < 0.85


@pytest.mark.parametrize(
    "k",
    [1.0, 1e-150, FAIL_OPEN_K, 1e-170],
    ids=["unit", "tiny-normal", "subnormal-sum", "sum-underflows-to-zero"],
)
def test_a_drifted_candidate_fails_at_every_scale(k: float) -> None:
    result = diff_response(_snapshot(), DRIFT, embedder=_ScaledEmbedder(k), warn_band=0.0)
    assert result.verdict == "fail"
    assert result.cosine_score == pytest.approx(TRUE_DRIFT, abs=1e-12)


def test_the_default_warn_band_still_warns_not_passes() -> None:
    # On main this went from `warn` to `pass` at the same scale.
    result = diff_response(_snapshot(), DRIFT, embedder=_ScaledEmbedder(FAIL_OPEN_K))
    assert result.verdict == "warn"


def test_cosine_is_scale_free_across_the_subnormal_range() -> None:
    a, b = _BASE.embed(DRIFT), _BASE.embed(CANON)
    # Every sum of squares in this sweep is subnormal or underflows to 0.0.
    for exp in range(155, 170):
        k = 1.0 * 10.0**-exp
        assert cosine([x * k for x in a], b) == pytest.approx(TRUE_DRIFT, abs=1e-12), k


def test_the_semantic_category_channel_is_scale_free_too() -> None:
    # Both vectors there come from the embedder, so both are subnormal. At this
    # scale the dot product underflowed too, and main scored the pair 0.0.
    plain = score_semantic_categories(DRIFT, [CANON], embedder=_BASE)
    tiny = score_semantic_categories(
        DRIFT, [CANON], embedder=_ScaledEmbedder(5.20595008801544e-162)
    )
    assert tiny[0].cosine_to_response == pytest.approx(plain[0].cosine_to_response, abs=1e-12)


def test_a_zero_candidate_still_fails_closed() -> None:
    # Control: nothing to rescale, so cosine stays 0.0 and the verdict `fail`.
    result = diff_response(_snapshot(), CANON, embedder=_ScaledEmbedder(0.0))
    assert result.cosine_score == 0.0
    assert result.verdict == "fail"


def test_the_identical_text_at_a_subnormal_scale_passes() -> None:
    # Control: the fix must not turn a correct pass into a fail.
    result = diff_response(_snapshot(), CANON, embedder=_ScaledEmbedder(FAIL_OPEN_K))
    assert result.verdict == "pass"
    assert result.cosine_score == pytest.approx(1.0, abs=1e-12)


def test_the_overflow_end_still_raises() -> None:
    # Control: #267's overflow behaviour is untouched (NaN for the caller to raise on).
    assert math.isnan(cosine([1e200] * 4, [1.0] * 4))
