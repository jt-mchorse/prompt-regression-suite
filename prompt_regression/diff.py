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
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from prompt_regression.schema import Snapshot

DEFAULT_THRESHOLD = 0.85
DEFAULT_WARN_BAND = 0.05  # warn if cosine in [threshold - warn_band, threshold)


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
        # Extends sign-only `ngram < 1` to the portfolio positive-int contract
        # (`rag-production-kit#43`, `embedding-model-shootout#36`). Sign-only
        # accepted `True` (silently bound; `model_name` became
        # `"hash-embedder-128d-ngramTrue"` which then tripped the D-006
        # embedder-model-mismatch refusal at diff time, masking the construction
        # bug) and `1.5` / `math.nan` (silently bound; `range(len - ngram + 1)`
        # raised `TypeError` / `ValueError` deep in `embed()`).
        if not isinstance(ngram, int) or isinstance(ngram, bool) or ngram <= 0:
            raise ValueError(f"ngram must be a positive integer; got {ngram!r}")
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


def _first_non_finite(vec: list[float]) -> tuple[int, float] | None:
    """Return ``(index, value)`` of the first non-finite component, or ``None``.

    Shared by every `cosine()` caller that consumes a BYO-`Embedder` vector so
    a `NaN`/`±Inf` component is rejected before it reaches `cosine()` (which
    only guards a zero norm) and silently yields a `nan` score (#67, #69).
    """
    return next(((i, v) for i, v in enumerate(vec) if not math.isfinite(v)), None)


def _finite_or_raise(score: float, *, model_name: str, where: str) -> float:
    """Guard the *output* of `cosine()`, symmetric to `_first_non_finite`'s input guard.

    `_first_non_finite` rejects non-finite input *components*, but an all-finite
    vector of out-of-range magnitude still overflows ``sum(x * x)`` to ``+inf``,
    so `cosine()` returns ``inf / inf = nan`` (e.g. two identical ``1e200``
    vectors score ``nan`` instead of ``1.0``). That ``nan`` slips the input guard
    and leaks into ``cosine_score`` / the HTML/JSON/PR-comment output as a
    misleading ``fail`` (``nan >= threshold`` is ``False``). Raise the same
    catchable `NonFiniteEmbeddingError` the input guard raises so the `run` batch
    records the row as ``error`` and continues — completing the guard the
    `NonFiniteEmbeddingError` docstring already promises (#67/#69 covered the
    non-finite-input path; this covers the finite-input overflow path).
    """
    if math.isfinite(score):
        return score
    raise NonFiniteEmbeddingError(
        f"cosine similarity came out non-finite ({score!r}) {where}: an all-finite "
        f"but out-of-range embedding from {model_name!r} overflowed the norm "
        "(sum of squares → ±inf). The embedder returned a non-normalized/corrupt "
        "vector; fix the embedder or re-run."
    )


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

# The slot types `extract_slots` actually has an extractor for. Schema-valid
# types outside this set (`array`/`object`/`null`, per `schema._ALLOWED_SLOT_TYPES`)
# are never extracted, so `diff_slots` must report them as `type_unknown` ("the
# tool did not try") — NOT `missing` ("the model failed to produce it"), which
# would misattribute a tool limitation as a model regression on every diff (#77).
_EXTRACTABLE_SLOT_TYPES = frozenset({"integer", "number", "string", "boolean"})


@dataclass(frozen=True)
class SlotDelta:
    """One slot's verdict in the structural channel."""

    name: str
    expected_type: str
    actual_value: Any
    status: str  # "ok" | "missing" | "type_mismatch" | "type_unknown"

    @property
    def is_failure(self) -> bool:
        # `type_unknown` means "the tool has no extractor for this schema-valid
        # slot type" (array/object/null) — "the tool did not try", NOT a model
        # regression (#77, see _EXTRACTABLE_SLOT_TYPES above). Counting it here
        # would force verdict=fail on every diff for such a slot, re-introducing
        # the exact misattribution #77 set out to fix. Only `missing` and
        # `type_mismatch` are real failures.
        return self.status not in ("ok", "type_unknown")

    def to_dict(self) -> dict[str, Any]:
        # Four-field contract (#51) — replaces `asdict(d)` in cli.py's
        # `_serialize_diff` so a future internal-only field on SlotDelta
        # can't silently leak into the `prompt-snap diff --json` shape.
        return {
            "name": self.name,
            "expected_type": self.expected_type,
            "actual_value": self.actual_value,
            "status": self.status,
        }


# `-?` is only a sign when the `-` is not glued to a preceding word char or
# hyphen. The old `-?\b\d+` matched the hyphen in a hyphenated token (`W-2`,
# `ABC-7`) as a unary minus — because the boundary between `-` and a digit is
# always a `\b` — and extracted a spurious negative, which then passed the
# `isinstance(int)` check and could mask a number-loss regression as `ok`. The
# `(?<![\w-])` lookbehind keeps genuine negatives (`-30`, `-2.5`) and the
# `14-day` → `14` case working while rejecting hyphenated identifiers. See #79.
_INTEGER_RE = re.compile(r"(?<![\w-])-?\d+\b")
# The `\.\d+` alternative catches a leading-decimal number (`.5`, `.05`, `-.5`),
# common for rates/probabilities/discounts. The old `-?\d+\.?\d*` required at
# least one digit *before* the point, so on `.05` the leading `.` failed to
# start a match but `\d+` then matched `05` — extracting `5.0` and dropping the
# fraction, silently masking a number-loss regression. The bare-`.`-only case
# (no trailing digit) is excluded, and `_INTEGER_RE` is unchanged (integers have
# no leading decimal). Preserves the #79 hyphen guards (`14-day`→14, `W-2`→none).
_NUMBER_RE = re.compile(r"(?<![\w-])-?(?:\d+\.?\d*|\.\d+)\b")
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


def _coerce_match(raw: str, *, want_int: bool) -> int | float | None:
    """Convert one regex match to a finite number, or ``None`` if it isn't one.

    A bare ``int(raw)`` / ``float(raw)`` is total for every number a model
    plausibly writes and fails on exactly one shape — a very long digit run —
    which is the shape a degenerate repetition loop produces. That is the
    pathology this tool exists to catch, so the extractor has to survive it
    (#131).

    Both coercions fail differently and neither failure was handled:

    - ``int`` raises ``ValueError`` past CPython's int↔str digit cap
      (``sys.get_int_max_str_digits()``, 4300 by default). Nothing in
      ``diff_slots`` or ``diff_response`` catches it, so it escaped as a raw
      traceback at exit 1 — the contract #99/#111/#113/#115/#117/#119/#126
      have been closing everywhere else.
    - ``float`` does *not* raise. ``float("9" * 400)`` is ``inf``, which then
      passed the ``isinstance(actual, float)`` check as ``status: "ok"`` and
      egressed into ``--format json`` as a bare ``Infinity`` token. That is
      not valid JSON, so ``jq`` / ``JSON.parse`` / a Go or Rust decoder
      rejects the whole document — the same non-finite-at-egress class as
      rag-production-kit#137.

    Returning ``None`` lets the caller move on to the next match, and if none
    is representable ``diff_slots`` renders the slot as ``missing`` → a
    failing verdict, which is the right answer for a degenerate response and
    needs no new status in the ``--json`` contract.
    """
    try:
        value: int | float = int(raw) if want_int else float(raw)
    except ValueError:
        return None
    if not want_int and not math.isfinite(value):
        return None
    return value


def _first_representable(matches: Sequence[re.Match[str]], *, want_int: bool) -> int | float | None:
    for match in matches:
        value = _coerce_match(match.group(0), want_int=want_int)
        if value is not None:
            return value
    return None


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
                # Nearest to `idx` first, then outward. `sorted` is stable, so
                # the head of this list is the same match `min(...)` picked
                # before — the ordering only matters when the nearest token
                # turns out to be unrepresentable, in which case a perfectly
                # good number elsewhere in the response should still be found
                # rather than poisoning the whole extraction (#131).
                by_distance = sorted(matches, key=lambda m: abs(m.start() - idx))
                value = _first_representable(by_distance, want_int=want_int)
                if value is not None:
                    return value
                # Every match is unrepresentable; a different hint word ranks
                # the same set, so it cannot help.
                return None
    return _first_representable(matches, want_int=want_int)


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
        # Anything we don't have an extractor for — a schema-valid
        # array/object/null, or an unrecognized type — is `type_unknown`, not a
        # model regression. Gating on SLOT_TYPE_PYTHON (which lists array/object/
        # null) wrongly let those fall through to the `missing` branch below (#77).
        if slot_type not in _EXTRACTABLE_SLOT_TYPES:
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

    def to_dict(self) -> dict[str, Any]:
        # Two-field contract (#51).
        return {
            "name": self.name,
            "cosine_to_response": self.cosine_to_response,
        }


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
    # The main cosine_score path validates candidate finiteness (#67), but this
    # channel re-embeds the candidate and each category label and calls
    # cosine() too. A BYO embedder returning a NaN/±Inf component here would
    # otherwise yield a `nan` cosine_to_response that leaks into the HTML/JSON/
    # PR-comment output. Raise the same catchable per-row error so the `run`
    # batch records `error` and continues — symmetric with the main path (#69).
    bad = _first_non_finite(response_vec)
    if bad is not None:
        raise NonFiniteEmbeddingError(
            f"candidate embedding from {embedder.model_name!r} has a non-finite "
            f"component at index {bad[0]}: {bad[1]!r} (semantic-category channel). "
            "The embedder returned a corrupt vector; fix the embedder or re-run."
        )
    out: list[SemanticCategoryScore] = []
    for cat in categories:
        cat_vec = embedder.embed(cat)
        bad = _first_non_finite(cat_vec)
        if bad is not None:
            raise NonFiniteEmbeddingError(
                f"embedding for semantic category {cat!r} from {embedder.model_name!r} "
                f"has a non-finite component at index {bad[0]}: {bad[1]!r}. The embedder "
                "returned a corrupt vector; fix the embedder or re-run."
            )
        out.append(
            SemanticCategoryScore(
                name=cat,
                cosine_to_response=_finite_or_raise(
                    cosine(response_vec, cat_vec),
                    model_name=embedder.model_name,
                    where=f"for semantic category {cat!r}",
                ),
            )
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

    def to_dict(self) -> dict[str, Any]:
        # Eight-field contract (#51) — replaces cli.py `_serialize_diff`'s
        # asdict-based render. Nests `slot_deltas[*].to_dict()` and
        # `semantic_category_scores[*].to_dict()` so the nested shapes
        # are owned by the nested classes' own contracts.
        return {
            "verdict": self.verdict,
            "cosine_score": self.cosine_score,
            "threshold": self.threshold,
            "embedder_model": self.embedder_model,
            "snapshot_embedding_model": self.snapshot_embedding_model,
            "slot_deltas": [d.to_dict() for d in self.slot_deltas],
            "semantic_category_scores": [s.to_dict() for s in self.semantic_category_scores],
            "notes": list(self.notes),
        }


class EmbedderModelMismatchError(ValueError):
    """Raised when the diff embedder's model_name doesn't match the snapshot's
    `embedding_model`. Pass `force=True` to override; this is a deliberate
    footgun-prevention guard (D-006)."""


class EmbeddingDimensionMismatchError(ValueError):
    """Raised when the candidate embedding's dimension doesn't match the
    snapshot's stored canonical embedding. The D-006 model-name guard is a
    string compare and is dimension-blind, so a snapshot whose embedding_model
    matches the active embedder but whose stored vector is a different length
    (older embedder build, hand-edited YAML) would otherwise crash `cosine()`
    with a raw ValueError and abort the whole `run` batch mid-iteration."""


class NonFiniteEmbeddingError(ValueError):
    """Raised when a candidate embedding carries a non-finite component.

    The *stored* embedding's finiteness is enforced at schema load
    (`CanonicalResponse.__post_init__`), and the candidate's dimension is
    checked here (`EmbeddingDimensionMismatchError`), but a BYO embedder
    (Cohere / OpenAI / custom, per the `Embedder` Protocol) returning a
    `NaN`/`±Inf` component would otherwise slip through `cosine()` (which
    only guards a zero norm) into a `nan` `cosine_score`. That collapses the
    verdict to a misleading `fail` (`nan >= threshold` is `False`) and leaks
    `nan` into the HTML/JSON/PR-comment output. Raise a catchable error so
    the `run` batch records this row as `error` and continues — the symmetric
    guard to the stored-embedding finiteness check."""


class WarnBandThresholdError(ValueError):
    """Raised when `warn_band > effective_threshold` (the #35 guard).

    A `warn_band` wider than the effective threshold makes the cosine warn floor
    `max(0.0, effective_threshold - warn_band)` clamp to `0.0`, collapsing the
    fail/warn distinction on the cosine channel — every sub-threshold cosine
    becomes "warn". Raising at the entry site keeps the misconfig fail-loud
    (D-006 "no silent degradation").

    The guard fires against the *effective* threshold, which `snapshot.tolerance`
    can lower below the run-level `warn_band` even when the operator never set
    `--warn-band`. That makes this raise reachable per-snapshot, so — like the
    three sibling guards above — it is a typed `ValueError` subclass the `run`
    loop catches and records as a per-row `error`, rather than a bare `ValueError`
    that escapes the loop and aborts the whole batch (#85, problem 1).

    Whether a low per-snapshot `tolerance` under the *default* `warn_band` should
    raise at all (vs. clamp `warn_band` down to the tolerance) is a separate
    semantics question deferred to a human (#85, problem 2); this class only
    addresses the batch-abort robustness gap and preserves the existing raise."""


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
    # `warn_band`'s sign checks below are NaN-blind: `NaN < 0` and
    # `NaN > effective_threshold` are both False, so a non-finite warn_band slips
    # past both and reaches the cosine_warn floor `max(0.0, effective_threshold -
    # warn_band)`, where `max(0.0, NaN)` collapses to 0.0 and demotes *every*
    # failing cosine to "warn" — silently disabling the gate, the same fail/warn
    # collapse #35 guards against, reached through a value `>` can't catch. The
    # sibling `threshold` range check above already rejects NaN; close the same
    # hole here, continuing this repo's finiteness sweep (#68/#69/#70).
    if not math.isfinite(warn_band):
        raise ValueError(f"warn_band must be finite; got {warn_band}")
    if warn_band < 0:
        raise ValueError(f"warn_band must be non-negative; got {warn_band}")
    # Upper bound matches the existing `(0, 1]` contract on `effective_threshold`.
    # When `warn_band >= effective_threshold`, the warn floor `max(0.0,
    # effective_threshold - warn_band)` clamps to `0.0` — at `warn_band >
    # effective_threshold` the raw floor is negative, and at the *exact boundary*
    # `warn_band == effective_threshold` it is already `0.0`. Either way the
    # cosine_warn floor becomes `0.0`, so `cosine_score >= 0.0` holds for *every*
    # sub-threshold cosine down to maximum drift (0.0): the fail/warn distinction
    # collapses on the cosine channel and every regression is demoted to "warn",
    # which `run`/`diff` never count as a failure — the gate passes CI green
    # (#105). The floor is only safe when strictly positive, i.e. `warn_band <
    # effective_threshold`, so reject `>=` (not just `>`) at the entry site (#35)
    # so the misconfig fails loud, matching D-006's "no silent degradation"
    # posture and the contract-tightening sweep in llm-eval-harness #40 /
    # llm-cost-optimizer #34 / rag-production-kit #36 / embedding-model-shootout
    # #29 / vector-search-at-scale #27.
    if warn_band >= effective_threshold:
        raise WarnBandThresholdError(
            f"warn_band must be < effective_threshold ({effective_threshold}); got {warn_band}"
        )

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
    # The D-006 model-name guard above is a string compare and dimension-blind.
    # A snapshot whose embedding_model matches the active embedder but whose
    # stored vector is a different length (older build, hand-edited YAML) would
    # otherwise hit cosine()'s raw "length mismatch" ValueError, which escapes
    # the `run` batch loop and aborts every remaining snapshot. Raise a
    # catchable error so the loop records this one row as `error` and continues.
    if len(candidate_vec) != len(snapshot.canonical.embedding):
        raise EmbeddingDimensionMismatchError(
            f"candidate embedding has {len(candidate_vec)} dims but snapshot "
            f"{snapshot.canonical.embedding_model!r} stored "
            f"{len(snapshot.canonical.embedding)}. Re-embed the snapshot with the "
            "current embedder (prompt-snap update --force)."
        )
    # The stored embedding's finiteness is enforced at schema load; the
    # candidate comes from a BYO embedder (Protocol) and isn't, so a NaN/±Inf
    # component here would otherwise produce a `nan` cosine_score. Fail loud as
    # a catchable per-row error rather than emit a garbage score (#67).
    bad = _first_non_finite(candidate_vec)
    if bad is not None:
        raise NonFiniteEmbeddingError(
            f"candidate embedding from {embedder.model_name!r} has a non-finite "
            f"component at index {bad[0]}: {bad[1]!r}. The embedder returned a "
            "corrupt vector; fix the embedder or re-run."
        )
    cosine_score = _finite_or_raise(
        cosine(candidate_vec, snapshot.canonical.embedding),
        model_name=embedder.model_name,
        where="for the main cosine_score",
    )

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
