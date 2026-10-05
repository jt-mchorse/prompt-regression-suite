"""An identical response passes `tolerance: 1.0` with any embedder; cosine stays in [-1, 1] (#197).

`cosine(v, v)` computed `dot / (sqrt(dot) * sqrt(dot))`, which for an
un-normalized vector (sentence-transformers without `normalize_embeddings`, the
documented BYO path) is 0.9999999999999999 or 1.0000000000000002 about half the
time. README.md says `1.0` "passes only an identical response"; an identical one
failed it ~24% of the time. The built-in `HashEmbedder` never hit it.
"""

from __future__ import annotations

import hashlib
import math
import random

import pytest

from prompt_regression.diff import cosine, diff_response
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot


class _UnnormalizedEmbedder:
    """Deterministic, un-normalized 384-dim vectors, like a raw encoder output."""

    model_name = "byo-unnormalized-384"

    def embed(self, text: str) -> list[float]:
        rng = random.Random(hashlib.sha256(text.encode()).digest())
        return [rng.uniform(-3, 3) for _ in range(384)]


def _snapshot(text: str, tolerance: float) -> Snapshot:
    e = _UnnormalizedEmbedder()
    return Snapshot(
        id="strict",
        prompt=Prompt(model="m", user="?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text=text, embedding=e.embed(text), embedding_model=e.model_name
        ),
        tolerance=tolerance,
    )


def test_every_identical_response_passes_tolerance_one() -> None:
    texts = [f"Refunds take {i} days." for i in range(300)]
    off = [
        t
        for t in texts
        if cosine(_UnnormalizedEmbedder().embed(t), _UnnormalizedEmbedder().embed(t)) != 1.0
    ]
    assert off == []
    verdicts = {
        diff_response(_snapshot(t, 1.0), t, embedder=_UnnormalizedEmbedder()).verdict for t in texts
    }
    assert verdicts == {"pass"}


def test_a_different_response_still_fails_tolerance_one() -> None:
    r = diff_response(
        _snapshot("Refunds take 14 days.", 1.0),
        "Refunds take 15 days.",
        embedder=_UnnormalizedEmbedder(),
    )
    assert r.verdict != "pass"


def test_cosine_never_leaves_minus_one_to_one() -> None:
    rng = random.Random(7)
    for _ in range(2000):
        v = [rng.uniform(-3, 3) for _ in range(64)]
        assert -1.0 <= cosine(v, [2.5 * x for x in v]) <= 1.0  # parallel, not identical
        assert -1.0 <= cosine(v, [-x for x in v]) <= 1.0


@pytest.mark.parametrize("bad", [math.inf, math.nan])
def test_non_finite_arithmetic_is_not_laundered_into_a_score(bad: float) -> None:
    # The callers' finiteness guards depend on NaN/inf surviving `cosine`.
    v = [bad, 1.0]
    assert not math.isfinite(cosine(v, v))
