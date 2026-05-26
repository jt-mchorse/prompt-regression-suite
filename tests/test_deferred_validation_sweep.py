"""Validation-sweep coverage for two un-swept construction sites (issue #37).

Mirrors the portfolio-wide positive-int / finiteness contract sweep landed
across `rag-production-kit#43`, `embedding-model-shootout#36`, and
`llm-eval-harness#47` today. Two sites:

- `HashEmbedder.__init__(ngram)` — positive-int contract (`<= 0` extended to
  reject `bool`, non-int, and clarify the error shape).
- `CanonicalResponse.embedding` element loop — extends existing bool /
  non-numeric rejection with `NaN` / `Inf` finiteness rejection per element,
  with an index-bearing error so the diagnostic points at the malformed slot.
"""

from __future__ import annotations

import math

import pytest

from prompt_regression import CanonicalResponse, HashEmbedder, SnapshotValidationError

# ----------------------------------------------------------------------
# HashEmbedder.__init__(ngram) — positive-int contract
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_ngram",
    [
        True,  # bool: silently bound; model_name became "hash-embedder-128d-ngramTrue".
        False,  # bool: would silently bypass sign-only as 0 == False; ngram < 1 caught it
        # before, but the shape is non-uniform with the rest of the portfolio.
        0,  # original `ngram < 1` caught 0 too, but new shape is uniform.
        -1,
        -2,
        0.5,
        1.5,  # whole-ish float: silently bound, then range() raised TypeError later.
        2.0,  # whole float: silently bound, then range() raised later.
        math.nan,  # `nan < 1` is False; silently bound; range() raised later.
        math.inf,
        -math.inf,
        None,
        "2",
        [2],
        (2,),
    ],
)
def test_hash_embedder_rejects_non_positive_int_ngram(bad_ngram):
    with pytest.raises(ValueError, match="ngram must be a positive integer"):
        HashEmbedder(ngram=bad_ngram)


@pytest.mark.parametrize("good_ngram", [1, 2, 3, 5, 100])
def test_hash_embedder_accepts_positive_int_ngram(good_ngram):
    e = HashEmbedder(ngram=good_ngram)
    assert e.ngram == good_ngram
    assert e.model_name == f"hash-embedder-128d-ngram{good_ngram}"


def test_hash_embedder_default_ngram_unchanged():
    # Default constructor path stays bound to 2; no behaviour change for the
    # 99% case.
    e = HashEmbedder()
    assert e.ngram == 2


# ----------------------------------------------------------------------
# CanonicalResponse.embedding element finiteness
# ----------------------------------------------------------------------


_VALID_EMBEDDING_PREFIX = [0.1, 0.2, 0.3, 0.4]
_VALID_EMBEDDING_TAIL = [0.5, 0.6, 0.7, 0.8]


def _embedding_with(bad: float, position: str) -> list[float]:
    """Inject `bad` at head / middle / tail of an otherwise-valid vector.

    Three positions catch any short-circuiting in the element loop and also
    pin the index-bearing error to the right slot.
    """
    if position == "head":
        return [bad] + _VALID_EMBEDDING_PREFIX + _VALID_EMBEDDING_TAIL
    if position == "middle":
        return _VALID_EMBEDDING_PREFIX + [bad] + _VALID_EMBEDDING_TAIL
    if position == "tail":
        return _VALID_EMBEDDING_PREFIX + _VALID_EMBEDDING_TAIL + [bad]
    raise AssertionError(f"unknown position: {position}")


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("position", ["head", "middle", "tail"])
def test_canonical_response_rejects_non_finite_embedding_element(bad, position):
    vec = _embedding_with(bad, position)
    with pytest.raises(SnapshotValidationError, match="must be a finite number"):
        CanonicalResponse(text="t", embedding=vec, embedding_model="hash-embedder-128d-ngram2")


def test_canonical_response_finite_error_carries_index():
    # Pin the diagnostic shape so future callers can grep on the index.
    vec = _embedding_with(math.nan, "middle")
    bad_index = len(_VALID_EMBEDDING_PREFIX)  # injected after the prefix
    with pytest.raises(
        SnapshotValidationError, match=rf"CanonicalResponse\.embedding\[{bad_index}\]"
    ):
        CanonicalResponse(text="t", embedding=vec, embedding_model="hash-embedder-128d-ngram2")


def test_canonical_response_accepts_finite_zero_and_negatives():
    # Finiteness is the contract, NOT non-negativity. Cosine math works on
    # signed unit vectors, so an embedding with negative components is valid.
    vec = [0.0, -0.5, 0.5, 1.0, -1.0]
    r = CanonicalResponse(text="t", embedding=vec, embedding_model="hash-embedder-128d-ngram2")
    assert r.embedding == vec


def test_canonical_response_bool_rejected_before_finiteness():
    # The existing bool reject is upstream of the new finiteness check; pin
    # the error message shape so contract precedence is unambiguous.
    vec = [0.1, True, 0.3]  # type: ignore[list-item]
    with pytest.raises(SnapshotValidationError, match="must be a number, got bool"):
        CanonicalResponse(text="t", embedding=vec, embedding_model="hash-embedder-128d-ngram2")
