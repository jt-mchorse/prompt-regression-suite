"""Snapshot diff layer.

`diff_response(snapshot, candidate, *, embedder, threshold)` compares a new
response against a stored snapshot along two channels:

- **Cosine similarity** between the candidate's embedding and the snapshot's
  stored canonical embedding.
- **Structured-slot extraction**: every slot the snapshot's
  `response_shape.structured_slots` declares must be present and type-correct
  in the candidate.

The verdict is the AND of both channels. Cosine alone (which "passed" but the
slot extraction failed) is not enough; the snapshot's structural assertions
are hard requirements.

The embedder is a pluggable Protocol with the same single-method shape used
across the portfolio (rag-production-kit, llm-eval-harness, llm-cost-optimizer).
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from prompt_regression.schema import Snapshot

DEFAULT_THRESHOLD = 0.85
DEFAULT_WARN_BAND = 0.05  # warn if cosine in [threshold, threshold + warn_band)


# ----------------------------------------------------------------------
# Embedder Protocol + dep-free reference
# ----------------------------------------------------------------------


class Embedder(Protocol):
    """Single-method seam for swapping embedder backends."""

    @property
    def model_name(self) -> str: ...
    def embed(self, text: str) -> list[float]: ...


HASH_EMBEDDING_DIM = 128


class HashEmbedder:
    """Deterministic hash-based embedder. Dep-free, hermetic.

    Matches the snapshot's stored embedding-model name `hash-embedder-128d-v1`
    so test fixtures don't trip the embedder-model-mismatch refusal (D-006).

    Bag-of-token-n-grams projected into 128 dims via SHA-256 hashing of each
    n-gram; L2-normalized. Production callers BYO via the Protocol — Cohere /
    Voyage / OpenAI / sentence-transformers all conform with a one-line wrapper.
    """

    def __init__(self, *, ngram: int = 2) -> None:
        if ngram < 1:
            raise ValueError("ngram must be >= 1")
        self.ngram = ngram

    @property
    def model_name(self) -> str:
        return f"hash-embedder-128d-ngram{self.ngram}"

    def embed(self, text: str) -> list[float]:
        if not isinstance(text, str):
            raise TypeError("text must be a str")
        tokens = [t for t in text.lower().split() if t]
        ngrams: list[str]
        if self.ngram == 1:
            ngrams = list(tokens)
        else:
            ngrams = [
                " ".join(tokens[i : i + self.ngram]) for i in range(len(tokens) - self.ngram + 1)
            ]
        vec = [0.0] * HASH_EMBEDDING_DIM
        if not ngrams:
            vec[0] = 1.0
            return vec
        for ng in ngrams:
            h = hashlib.sha256(ng.encode("utf-8")).digest()
            slot = int.from_bytes(h[:4], "big") % HASH_EMBEDDING_DIM
            vec[slot] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Returns 0.0 if either vector is zero."""
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ----------------------------------------------------------------------
# Slot extraction (structural channel)
# ----------------------------------------------------------------------


SLOT_TYPE_PYTHON = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


@dataclass(frozen=True)
class SlotDelta:
    """One slot's verdict in the structural channel."""

    name: str
    expected_type: str
    actual_value: Any
    status: str  # "ok" | "missing" | "type_mismatch" | "type_unknown"

    @property
    def is_failure(self) -> bool:
        return self.status != "ok"


_INTEGER_RE = re.compile(r"-?\b\d+\b")
_NUMBER_RE = re.compile(r"-?\b\d+\.?\d*\b")
_QUOTED_RE = re.compile(r"\"([^\"]+)\"|'([^']+)'")


def extract_slots(text: str, slot_specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Pull structured slot values out of `text`.

    Heuristic-based, intentionally simple. The diff layer's job is to *catch
    regressions* — silently passing because the extractor missed a slot is
    much worse than failing because the heuristic was strict. Extraction
    rules per slot type:

    - `integer` / `number`: scan the text for the first numeric token. The
      slot's `description` field is consulted as a hint ("days", "minutes",
      "dollars") to disambiguate when multiple numbers are present, by
      preferring numbers near the hint word.
    - `string`: prefer a quoted string; fall back to the slot's `description`
      keyword being mentioned in the text.
    - `boolean`: look for "yes"/"no"/"true"/"false" keywords.
    - other types: not extracted; reported as `type_unknown` so callers can
      see we didn't try.
    """
    out: dict[str, Any] = {}
    if not slot_specs:
        return out
    lowered = text.lower()
    for name, spec in slot_specs.items():
        slot_type = spec.get("type")
        hint = (spec.get("description") or "").lower()
        if slot_type in ("integer", "number"):
            value = _extract_number(text, lowered, hint, want_int=(slot_type == "integer"))
            if value is not None:
                out[name] = value
        elif slot_type == "string":
            value = _extract_string(text, hint, name)
            if value is not None:
                out[name] = value
        elif slot_type == "boolean":
            value = _extract_boolean(lowered)
            if value is not None:
                out[name] = value
    return out


def _extract_number(text: str, lowered: str, hint: str, *, want_int: bool) -> int | float | None:
    pattern = _INTEGER_RE if want_int else _NUMBER_RE
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    if hint:
        # Prefer the number closest to the hint word.
        hint_words = [w for w in hint.split() if len(w) > 3]
        for hw in hint_words:
            idx = lowered.find(hw)
            if idx != -1:
                # Pick the match nearest to `idx`.
                best = min(matches, key=lambda m: abs(m.start() - idx))
                raw = best.group(0)
                return int(raw) if want_int else float(raw)
    raw = matches[0].group(0)
    return int(raw) if want_int else float(raw)


def _extract_string(text: str, hint: str, name: str) -> str | None:
    quoted = _QUOTED_RE.search(text)
    if quoted:
        return quoted.group(1) or quoted.group(2)
    # Fallback: if any meaningful word from the hint or the slot name appears,
    # report the surrounding sentence as the slot value.
    keywords = [w for w in (hint + " " + name).split() if len(w) > 3]
    for kw in keywords:
        idx = text.lower().find(kw.lower())
        if idx != -1:
            # Trim to the surrounding sentence.
            sentence = _sentence_around(text, idx)
            return sentence
    return None


def _sentence_around(text: str, idx: int) -> str:
    # Find sentence boundaries around `idx`. Cheap enough.
    start = max(text.rfind(".", 0, idx), text.rfind("\n", 0, idx)) + 1
    end_period = text.find(".", idx)
    end_newline = text.find("\n", idx)
    candidates = [e for e in (end_period, end_newline) if e != -1]
    end = min(candidates) if candidates else len(text)
    return text[start : end + 1].strip()


_BOOL_TRUE_RE = re.compile(r"\b(yes|true|allowed|permitted|enabled)\b", re.IGNORECASE)
_BOOL_FALSE_RE = re.compile(r"\b(no|false|not\s+allowed|refused|disabled|denied)\b", re.IGNORECASE)


def _extract_boolean(lowered: str) -> bool | None:
    # Check the negative pattern first so "not allowed" wins over the lone "allowed".
    if _BOOL_FALSE_RE.search(lowered):
        return False
    if _BOOL_TRUE_RE.search(lowered):
        return True
    return None


def diff_slots(slot_specs: dict[str, dict[str, Any]], candidate_text: str) -> list[SlotDelta]:
    """Compare extracted slot values from `candidate_text` against `slot_specs`."""
    if not slot_specs:
        return []
    extracted = extract_slots(candidate_text, slot_specs)
    deltas: list[SlotDelta] = []
    for name, spec in slot_specs.items():
        slot_type = spec.get("type", "string")
        if slot_type not in SLOT_TYPE_PYTHON:
            deltas.append(
                SlotDelta(
                    name=name, expected_type=slot_type, actual_value=None, status="type_unknown"
                )
            )
            continue
        if name not in extracted:
            deltas.append(
                SlotDelta(name=name, expected_type=slot_type, actual_value=None, status="missing")
            )
            continue
        actual = extracted[name]
        expected_python = SLOT_TYPE_PYTHON[slot_type]
        # bool is a subclass of int; reject it if the slot's declared type is integer/number.
        if isinstance(actual, bool) and slot_type in ("integer", "number"):
            deltas.append(
                SlotDelta(
                    name=name,
                    expected_type=slot_type,
                    actual_value=actual,
                    status="type_mismatch",
                )
            )
            continue
        if not isinstance(actual, expected_python):
            deltas.append(
                SlotDelta(
                    name=name,
                    expected_type=slot_type,
                    actual_value=actual,
                    status="type_mismatch",
                )
            )
            continue
        deltas.append(
            SlotDelta(name=name, expected_type=slot_type, actual_value=actual, status="ok")
        )
    return deltas


# ----------------------------------------------------------------------
# Semantic-category channel
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticCategoryScore:
    name: str
    cosine_to_response: float


def score_semantic_categories(
    candidate_text: str,
    categories: list[str],
    *,
    embedder: Embedder,
) -> list[SemanticCategoryScore]:
    """Cosine similarity between the candidate response and each category label."""
    if not categories:
        return []
    response_vec = embedder.embed(candidate_text)
    out: list[SemanticCategoryScore] = []
    for cat in categories:
        cat_vec = embedder.embed(cat)
        out.append(
            SemanticCategoryScore(name=cat, cosine_to_response=cosine(response_vec, cat_vec))
        )
    return out


# ----------------------------------------------------------------------
# Public diff entry point
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class DiffResult:
    cosine_score: float  # cosine vs canonical embedding
    semantic_category_scores: list[SemanticCategoryScore]
    slot_deltas: list[SlotDelta]
    verdict: str  # "pass" | "warn" | "fail"
    threshold: float
    embedder_model: str
    snapshot_embedding_model: str
    notes: list[str] = field(default_factory=list)


class EmbedderModelMismatchError(ValueError):
    """Raised when the diff embedder's model_name doesn't match the snapshot's
    `embedding_model`. Pass `force=True` to override; this is a deliberate
    footgun-prevention guard (D-006)."""


def diff_response(
    snapshot: Snapshot,
    candidate_text: str,
    *,
    embedder: Embedder,
    threshold: float = DEFAULT_THRESHOLD,
    warn_band: float = DEFAULT_WARN_BAND,
    force: bool = False,
) -> DiffResult:
    """Compare `candidate_text` against `snapshot`. Returns a structured DiffResult.

    The effective cosine threshold is the snapshot's own ``tolerance`` when
    set (issue #10), falling back to the ``threshold`` kwarg / CLI flag
    otherwise. ``DiffResult.threshold`` carries the *effective* value so
    downstream surfaces (HTML report, PR comments) show the number that
    was actually applied to this row.
    """
    effective_threshold = snapshot.tolerance if snapshot.tolerance is not None else threshold
    if not 0.0 < effective_threshold <= 1.0:
        raise ValueError(f"threshold must be in (0, 1]; got {effective_threshold}")
    if warn_band < 0:
        raise ValueError(f"warn_band must be non-negative; got {warn_band}")

    if not force and embedder.model_name != snapshot.canonical.embedding_model:
        raise EmbedderModelMismatchError(
            f"snapshot was embedded with {snapshot.canonical.embedding_model!r} but "
            f"the diff embedder reports {embedder.model_name!r}. Re-embed the snapshot "
            "or pass force=True to override."
        )

    notes: list[str] = []
    if snapshot.tolerance is not None and snapshot.tolerance != threshold:
        notes.append(
            f"per-snapshot tolerance {snapshot.tolerance:.3f} overrides run threshold "
            f"{threshold:.3f}"
        )
    candidate_vec = embedder.embed(candidate_text)
    cosine_score = cosine(candidate_vec, snapshot.canonical.embedding)

    category_scores = score_semantic_categories(
        candidate_text, snapshot.response_shape.semantic_categories, embedder=embedder
    )
    slot_deltas = diff_slots(snapshot.response_shape.structured_slots, candidate_text)

    cosine_pass = cosine_score >= effective_threshold
    cosine_warn = (not cosine_pass) and cosine_score >= max(0.0, effective_threshold - warn_band)
    slots_ok = all(not d.is_failure for d in slot_deltas)

    if not slots_ok:
        verdict = "fail"
        for d in slot_deltas:
            if d.is_failure:
                notes.append(f"slot {d.name!r}: {d.status}")
    elif cosine_pass:
        verdict = "pass"
    elif cosine_warn:
        verdict = "warn"
        notes.append(
            f"cosine {cosine_score:.3f} below threshold {effective_threshold:.3f} "
            "but inside warn band"
        )
    else:
        verdict = "fail"
        notes.append(f"cosine {cosine_score:.3f} below threshold {effective_threshold:.3f}")

    return DiffResult(
        cosine_score=cosine_score,
        semantic_category_scores=category_scores,
        slot_deltas=slot_deltas,
        verdict=verdict,
        threshold=effective_threshold,
        embedder_model=embedder.model_name,
        snapshot_embedding_model=snapshot.canonical.embedding_model,
        notes=notes,
    )
