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
from fractions import Fraction
from typing import Any, Protocol

from prompt_regression.schema import Snapshot

DEFAULT_THRESHOLD = 0.85
DEFAULT_WARN_BAND = 0.05  # warn if cosine in [threshold - warn_band, threshold)

#: Decimal places the comparison surfaces have always used, and still use
#: whenever three is enough to tell the two numbers apart.
COMPARISON_PLACES = 3
#: Ceiling on widening. A double needs at most 17 significant digits to
#: round-trip, so 17 decimal places separates any two distinct doubles whose
#: magnitudes are near 1 -- which `threshold`'s ``(0, 1]`` contract and
#: `cosine`'s ``[-1, 1]`` range make the operating region. It is a ceiling and
#: not a guarantee: two subnormal-scale values (``1e-300`` vs ``2e-300``) render
#: identically at *any* fixed number of places, which is what the `repr`
#: fallback below is for.
COMPARISON_MAX_PLACES = 17


def render_comparison(
    value: float,
    other: float,
    *,
    places: int,
    exact_value: bool = False,
    exact_other: bool = False,
) -> tuple[str, str]:
    """Render two numbers so an ordering stated between them stays visible.

    `diff_response` decides pass/fail at full float precision and then explains
    the decision in prose. Rendering both sides of that explanation at a fixed
    three places made the explanation contradict itself at a near miss (#175)::

        cosine=0.8499996  threshold=0.85  verdict=fail
        -> "cosine 0.850 below threshold 0.850"

    A *near-threshold* failure is the ordinary shape of a marginal regression,
    and it is exactly when an operator reads the note most carefully. So the
    width is chosen by asking whether the two values actually render
    differently, and widening while they do not.

    **A wider fixed width is not the same fix.** Moving to ``.6f`` makes the
    collision need a tighter margin (``0.8499999995``) without removing it, and
    a rule expressed as a hand-picked width has no way to say what it is for.
    Deciding on the rendered strings cannot drift from what the reader sees,
    because it *is* what the reader sees. Same shape as the wall-clock cell in
    `chunking-strategies-lab` D-016, where a magnitude threshold missed the one
    value half-to-even rounding sends the other way.

    Equal inputs return the narrow rendering unwidened: there is nothing to
    distinguish, and widening would imply a difference that is not there. The
    callers never rely on that -- the fail and warn notes are reached only when
    ``cosine_score < effective_threshold`` strictly, and the tolerance note is
    guarded by ``!=`` -- but the function is total, so it says what it does.

    Returns both renderings rather than one, because a caller that widened only
    its own side would print two numbers at different precisions and invite the
    reader to compare them as written.

    **`places` is required, and #177 is the evidence for it.** It was a
    hardcoded `COMPARISON_PLACES` until the first caller with a different width
    arrived: `cli.py`'s `cosine:` line publishes four places, and routing it
    through a three-place helper silently republished the README CLI tour's
    pinned `cosine:  0.8058 (threshold 0.75)` as `0.806 (threshold 0.750)` —
    narrowing a documented number to fix an unrelated defect. That is the
    regression `llm-eval-harness#252` shipped, caught here only because
    `test_readme_cli_tour_examples` pins the line byte-for-byte. The four
    original callers pass `COMPARISON_PLACES` explicitly; nothing about this
    helper should have an opinion on which width a surface publishes.

    **`exact_value` / `exact_other` mark an operand as a *configured parameter*
    (#181, D-015).** The loop above stops the instant the two strings differ,
    which makes the ordering readable and says nothing about whether either
    number survives the trip. Every threshold this package compares against is
    something an operator typed -- ``--threshold`` and ``--warn-band`` are
    ``type=float`` with no width constraint, and a per-snapshot ``tolerance``
    comes from YAML -- so at four places a run gated at ``0.85004`` published
    ``threshold 0.8500`` on every surface. A reader who copies that number back
    into ``--threshold`` gets a different gate. Marking an operand widens the
    pair until that operand reads back as itself, **still at one shared width**:
    widening only the configured side is the pre-#175 shape, which renders the
    ordering backwards.

    **Both flags exist because `diff.py`'s tolerance note has two configured
    operands**, and that is what separates this helper from its sibling.
    ``llm-eval-harness``' D-029 ships ``exact_other`` alone and its docstring
    says there is "deliberately no ``exact_value``" because "``value`` is the
    measured side at all six call sites". True there; false here. The
    per-snapshot tolerance note compares ``snapshot.tolerance`` against
    ``threshold`` -- neither measured -- and at
    ``tolerance=0.8500001, threshold=0.9000001`` it published "per-snapshot
    tolerance 0.850 overrides run threshold 0.900", in which *both* numbers are
    ones nobody set. The asymmetry over there is a property of that repo's call
    sites, not of the class; neither helper should be harmonised to the other
    without reading this paragraph.

    Not the collision #175/#177 fixed. That one is two *equal* renderings of two
    different numbers; this is two *unequal* renderings, each of a number nobody
    configured. Invisible while a threshold is round, which
    :data:`DEFAULT_THRESHOLD` is -- which is how five call sites carried it.
    """
    for width in range(places, max(places, COMPARISON_MAX_PLACES) + 1):
        rendered = (f"{value:.{width}f}", f"{other:.{width}f}")
        # Round-tripping is monotone in width: a wider rendering is at least as
        # close to the value, and the intervals that round to a given double
        # nest. So skipping a width cannot skip past a narrower acceptable one.
        if exact_value and float(rendered[0]) != value:
            continue
        if exact_other and float(rendered[1]) != other:
            continue
        if value == other or rendered[0] != rendered[1]:
            return rendered
    # Two distinct doubles too small for any fixed-point rendering to separate.
    # `repr` round-trips a float by definition, so it always distinguishes them
    # and reproduces a configured value exactly. This is the one exit that does
    # not guarantee a shared precision, which was already true before #181.
    return (repr(value), repr(other))


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
        elif 0 < len(tokens) < self.ngram:
            # Too short for one full n-gram: the whole token sequence is its one
            # gram (#195, D-016). It used to produce NO grams and fall through to
            # the `e0` sentinel below, so every one-word text embedded to the same
            # vector -- `"negative"` passed against a `"positive"` snapshot at
            # cosine 1.0000, and every single-token category label scored the
            # same. A text with >= `ngram` tokens is untouched, so every stored
            # snapshot embedding of such a text is still reproduced bit for bit.
            ngrams = [" ".join(tokens)]
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
    # Identical vectors are exactly 1.0, and nothing leaves [-1, 1] (#197). In
    # floats `dot / (sqrt(dot) * sqrt(dot))` is 0.9999999999999999 or
    # 1.0000000000000002 for about half of un-normalized vectors, so an identical
    # response FAILED `tolerance: 1.0` -- documented as passing only an
    # identical response -- with a note that read like real drift.
    #
    # Non-finite arithmetic (an overflowing embedder) is returned untouched so the
    # callers' finiteness guards still raise: `min(1.0, nan)` is 1.0 in Python,
    # so a clamp applied first would launder NaN into a perfect score.
    value = dot / (na * nb)
    if not math.isfinite(value) or not math.isfinite(na):
        return value
    if list(a) == list(b):
        return 1.0
    return max(-1.0, min(1.0, value))


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


#: Slot type -> the Python type(s) `isinstance` should accept for it.
#:
#: Annotated rather than inferred. The values mix a bare `type` with a
#: `tuple[type, type]`, so mypy widened the value type to `object` and
#: `isinstance(actual, expected_python)` below became uncheckable (#146).
#: `_ClassInfo` is what `isinstance` accepts, and this spells it out.
SLOT_TYPE_PYTHON: dict[str, type | tuple[type, ...]] = {
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
# The `\.\d+` alternative catches a leading-decimal number (`.5`, `.05`, `-.5`),
# common for rates/probabilities/discounts. The old `-?\d+\.?\d*` required at
# least one digit *before* the point, so on `.05` the leading `.` failed to
# start a match but `\d+` then matched `05` — extracting `5.0` and dropping the
# fraction, silently masking a number-loss regression. The bare-`.`-only case
# (no trailing digit) is excluded, and `_INTEGER_RE` is unchanged (integers have
# no leading decimal). Preserves the #79 hyphen guards (`14-day`→14, `W-2`→none).
#
# One token pattern for BOTH slot types since #211, with thousands groups first.
# `_INTEGER_RE` was `-?\d+\b`, and `\d+\b` matches each HALF of an ordinary
# decimal: `Refunds take 3.5 days.` extracted 5 (the half nearest "days") with
# status `ok` -- the hard slot check passed on a value the response never
# stated. And neither pattern knew `1,000`: both extracted 0 from `,000`. An
# integer slot now sees the whole token; `_coerce_match` keeps an integral one
# as an int and a fractional one as the float it is, which `diff_slots` reports
# as `type_mismatch` -- a loud failure instead of a wrong `ok`. A `.` before a
# digit run is excluded by the lookbehind so `5` is never re-read out of `3.5`.
_NUMBER_RE = re.compile(r"(?<![\w.-])-?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.?\d*|\.\d+)\b")
_INTEGER_RE = _NUMBER_RE
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
    # One binding across three branches, so its type is the union of the three
    # extractors' returns. Left to inference it took the *first* branch's type
    # and every later branch read as an error (#146). Each branch writes into
    # `out[name]` immediately and none reads another branch's binding, so the
    # union is real and there is nothing to restructure — only to state.
    value: int | float | str | bool | None
    for name, spec in slot_specs.items():
        slot_type = spec.get("type")
        hint = (spec.get("description") or "").lower()
        if slot_type in ("integer", "number"):
            value = _extract_number(text, hint, want_int=(slot_type == "integer"))
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

    The finiteness rule was written as ``if not want_int and not
    math.isfinite(value)``, i.e. scoped to one branch of this function, and the
    paragraph above framed the hazard as a ``float`` problem. Both were wrong,
    and in the same direction: the *integer* branch had no magnitude bound at
    all, so the docstring's own example split (#147)::

        digits            want_int=True        want_int=False
             3           int(3 digits)                 999.0
            20          int(20 digits)                 1e+20
           309         int(309 digits)                  None
           400         int(400 digits)                  None   <- the example above
          4299        int(4299 digits)                  None
          4301                    None                  None   <- CPython digit cap

    The integer route reaches the *same destination by a quieter road*. It
    produces **valid** JSON, so there is no decoder rejection to notice —
    ``JSON.parse`` of a 400-digit integer literal returns ``Infinity``, and
    ``jq`` and most Go/Rust ``float64`` decoders do the same, with no error.
    The float route at least stopped the pipeline.

    Reachability is this docstring's own argument: a very long digit run "is
    the shape a degenerate repetition loop produces", and such a loop hits
    ``_INTEGER_RE`` exactly as readily as ``_NUMBER_RE``.

    So the rule is now stated once, for both branches: the value must be
    representable as a finite IEEE-754 double, which is what the float branch
    always enforced. Note ``float()`` fails *differently* on the two inputs —
    ``float("9" * 309)`` is ``inf`` while ``float(int("9" * 309))`` raises
    ``OverflowError`` — so both arms are needed. The boundary is exact::

        308 digits -> float -> 1e+308          finite; both branches accept
        309 digits -> inf / OverflowError      both branches reject

    Precision loss *below* that threshold (a 20-digit integer does not survive
    a ``float64`` round trip intact) is deliberately left alone: it is a
    different concern with a different threshold (``2**53``), and it needs an
    argument about what a slot value is for. A value that becomes ``Infinity``
    needs no such argument.

    Returning ``None`` lets the caller move on to the next match, and if none
    is representable ``diff_slots`` renders the slot as ``missing`` → a
    failing verdict, which is the right answer for a degenerate response and
    needs no new status in the ``--json`` contract.
    """
    raw = raw.replace(",", "")  # a thousands group (#211); the regex admits only `d{1,3}(,ddd)+`
    try:
        value: int | float
        if not want_int:
            value = float(raw)
        elif "." in raw:
            # A decimal in an integer slot (#211): integral (`3.0`) is the int,
            # fractional (`3.5`) stays a float so the slot reads `type_mismatch`.
            as_float = float(raw)
            value = int(as_float) if as_float.is_integer() else as_float
        else:
            value = int(raw)
    except (ValueError, OverflowError):
        return None
    if not _is_finite_double(value):
        return None
    return value


def _is_finite_double(value: int | float) -> bool:
    """True when ``value`` survives as a finite IEEE-754 double.

    One rule for both branches of ``_coerce_match`` (#147). ``math.isfinite``
    alone is not it: for a Python ``int`` it is *always* ``True``, however many
    digits the int has, which is precisely why conditioning the old guard on
    ``not want_int`` looked harmless and was not.

    ``float()`` is the conversion every downstream ``float64`` JSON decoder
    performs, so asking it directly is asking the question that matters — and
    it fails in two different ways depending on the input's Python type, hence
    both arms.
    """
    try:
        return math.isfinite(float(value))
    except OverflowError:
        # `float(huge_int)` raises where `float(huge_str)` returns `inf`.
        return False


def _first_representable(matches: Sequence[re.Match[str]], *, want_int: bool) -> int | float | None:
    for match in matches:
        value = _coerce_match(match.group(0), want_int=want_int)
        if value is not None:
            return value
    return None


def _find_ci(text: str, word: str) -> int:
    """Index of ``word`` in ``text``, ignoring case, as a position IN ``text`` (#213).

    Both callers used ``text.lower().find(...)`` and then indexed the ORIGINAL
    ``text`` with the result. ``str.lower()`` can change length -- ``"İ".lower()``
    is two characters -- so every ``İ`` before the hint word moved the position
    one character right: with thirty ``İ``s in a response, the integer slot for
    "delivery days" read the ``90`` of a trailing "Ref 90." instead of the
    ``3`` beside "Delivery", and the string slot returned the wrong sentence.
    Any Turkish response (İstanbul, İade) could do it. A case-insensitive search
    on ``text`` itself has no second string to disagree with.
    """
    m = re.search(re.escape(word), text, re.IGNORECASE)
    return m.start() if m else -1


def _extract_number(text: str, hint: str, *, want_int: bool) -> int | float | None:
    pattern = _INTEGER_RE if want_int else _NUMBER_RE
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    if hint:
        # Prefer the number closest to the hint word.
        hint_words = [w for w in hint.split() if len(w) > 3]
        for hw in hint_words:
            idx = _find_ci(text, hw)
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
        idx = _find_ci(text, kw)
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

# A negation cue immediately before a positive term. `_BOOL_FALSE_RE` spelled
# out `not\s+allowed` — the negated form of exactly one of the five terms in
# `_BOOL_TRUE_RE` — so `not permitted`, `not enabled`, `not true` and `not yes`
# fell straight through to the positive branch and extracted as `True`, the
# precise inversion the negative-first ordering exists to prevent (#142). The
# bare word `not` was also the only cue recognised, so `isn't allowed`,
# `cannot be enabled` and `never allowed` inverted too.
#
# Deriving the negation instead of enumerating negated pairs is what keeps this
# from being whack-a-mole: adding a sixth positive term to `_BOOL_TRUE_RE` now
# gets its negated form for free, which is exactly the maintenance trap that
# produced this bug.
_NEGATION_CUES = r"(?:not|never|cannot|can't|won't|isn't|aren't|wasn't|weren't|doesn't|don't|no)"

# The window between cue and term: up to two short filler words, so
# `cannot be enabled` and `is not currently permitted` are caught while an
# unrelated `not` far earlier in the sentence is not. This is a heuristic
# extractor by design — unbounded negation scope would be worse than the bug,
# because it would start inverting sentences that merely contain a `not`.
_NEGATED_TRUE_RE = re.compile(
    rf"\b{_NEGATION_CUES}\b(?:\s+\w+){{0,2}}\s+\b(yes|true|allowed|permitted|enabled)\b",
    re.IGNORECASE,
)


def _extract_boolean(lowered: str) -> bool | None:
    # Negatives are checked before positives so "not allowed" wins over the
    # lone "allowed" — and `_NEGATED_TRUE_RE` is what makes that ordering
    # actually cover the class, rather than the single phrasing that was
    # spelled out by hand.
    #
    # Not changed here: a negated *negative* (`not refused`, `not denied`)
    # still resolves to `False`. Flipping those is a genuine semantic
    # judgement for a heuristic extractor — "not denied" is not the same claim
    # as "allowed" — the phrasings are much rarer, and changing them would
    # alter existing behaviour rather than repair a stated invariant. Filed as
    # a question on #142 rather than decided silently here.
    if _NEGATED_TRUE_RE.search(lowered) or _BOOL_FALSE_RE.search(lowered):
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
    # First, ahead of the emptiness check and any embedder call (#192).
    # `ResponseShape` refuses this shape for the snapshot path; this exported
    # function is the other road in, and `"refund"` was scored as r, e, f, u, n, d
    # -- six categories, six embedder calls.
    if isinstance(categories, (str, bytes, bytearray)):
        fix = f"pass [{categories!r}]" if isinstance(categories, str) else "decode it first"
        raise ValueError(
            f"categories must be a list of labels, not a bare {type(categories).__name__}: "
            f"{categories!r} would be scored one character at a time -- {fix}"
        )
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
    # The bottom of the warn band the verdict was decided against (#203);
    # `None` when the run has no warn band.
    warn_floor: float | None = None

    def to_dict(self) -> dict[str, Any]:
        # Eight-field contract (#51) — replaces cli.py `_serialize_diff`'s
        # asdict-based render. Nests `slot_deltas[*].to_dict()` and
        # `semantic_category_scores[*].to_dict()` so the nested shapes
        # are owned by the nested classes' own contracts.
        return {
            "verdict": self.verdict,
            "cosine_score": self.cosine_score,
            "threshold": self.threshold,
            "warn_floor": self.warn_floor,
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


def warn_floor(threshold: float, warn_band: float) -> float:
    """The bottom of the warn band, ``[threshold - warn_band, threshold)``, exactly.

    Both operands are decimals an operator wrote (`--threshold 0.75`,
    `--warn-band 0.18`), and the float subtraction did not compute their
    difference: ``0.75 - 0.18`` is ``0.5700000000000001``, so a cosine of
    exactly 0.57 was `fail`, and the default ``0.85 - 0.05`` is
    ``0.7999999999999999``, one ULP lenient. 48 two-decimal pairs at a
    threshold of 0.70 or more land above the documented floor (#203). The
    difference of the decimals each float stands for, rounded once, is the
    floor the docs describe. Clamped at 0, as the band always was.
    """
    exact = Fraction(repr(threshold)) - Fraction(repr(warn_band))
    return max(0.0, float(exact))


def resolve_effective_threshold(snapshot: Snapshot, threshold: float) -> float:
    """The threshold in force for ``snapshot``: its own ``tolerance``, else the run's.

    One definition (#187). ``diff_response`` applied this, and ``run``'s
    hand-built ``skipped`` / ``error`` rows published ``args.threshold``
    instead -- the run's number beside a note naming the effective one.
    """
    return snapshot.tolerance if snapshot.tolerance is not None else threshold


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
    effective_threshold = resolve_effective_threshold(snapshot, threshold)
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
        # The cleanest case of #175's class: the `!=` on the line above has
        # *already established* the two values differ, and rendering both at a
        # fixed three places could then publish "tolerance 0.850 overrides run
        # threshold 0.850" -- an override the sentence describes as doing
        # nothing. The guard proved the difference; the rendering hid it.
        # **Both** operands are configured here, and this is the site that
        # proves the sibling helper's `exact_other`-only signature is a fact
        # about that repo rather than about the class (#181, D-015).
        # `snapshot.tolerance` is YAML and `threshold` is the run parameter;
        # at 0.8500001 / 0.9000001 this note published "tolerance 0.850
        # overrides run threshold 0.900", two numbers nobody set, in the one
        # sentence that tells an operator which of their values won.
        tol_str, thr_str = render_comparison(
            snapshot.tolerance,
            threshold,
            places=COMPARISON_PLACES,
            exact_value=True,
            exact_other=True,
        )
        notes.append(f"per-snapshot tolerance {tol_str} overrides run threshold {thr_str}")
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
    floor = warn_floor(effective_threshold, warn_band)
    cosine_warn = (not cosine_pass) and cosine_score >= floor
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
        # Both notes say "below", which is a claim about an ordering, so both
        # render through `render_comparison` (#175). Reached only when
        # `cosine_score < effective_threshold` strictly, so the two values are
        # never equal here.
        score_str, thr_str = render_comparison(
            cosine_score, effective_threshold, places=COMPARISON_PLACES, exact_other=True
        )
        notes.append(f"cosine {score_str} below threshold {thr_str} but inside warn band")
    elif warn_band > 0:
        verdict = "fail"
        # Name the boundary the verdict was decided at (#203). The note said
        # only "below threshold", exactly what a `warn` row's note also says,
        # and the floor that separates them appeared nowhere in the output.
        # The score renders against the floor, the boundary it fell below; the
        # floor is below the threshold, so the first ordering holds as printed.
        score_str, floor_str = render_comparison(
            cosine_score, floor, places=COMPARISON_PLACES, exact_other=True
        )
        _, thr_str = render_comparison(
            cosine_score, effective_threshold, places=COMPARISON_PLACES, exact_other=True
        )
        notes.append(
            f"cosine {score_str} below threshold {thr_str} and below warn floor {floor_str}"
        )
    else:
        verdict = "fail"
        score_str, thr_str = render_comparison(
            cosine_score, effective_threshold, places=COMPARISON_PLACES, exact_other=True
        )
        notes.append(f"cosine {score_str} below threshold {thr_str}")

    return DiffResult(
        cosine_score=cosine_score,
        semantic_category_scores=category_scores,
        slot_deltas=slot_deltas,
        verdict=verdict,
        threshold=effective_threshold,
        warn_floor=floor if warn_band > 0 else None,
        embedder_model=embedder.model_name,
        snapshot_embedding_model=snapshot.canonical.embedding_model,
        notes=notes,
    )


def _band(value: float, boundary: float) -> int:
    """Which side of *boundary* *value* falls on: ``-1`` below, ``0`` at, ``1`` above."""
    if value < boundary:
        return -1
    if value > boundary:
        return 1
    return 0


def render_classified(
    value: float, boundary: float, *, places: int, others: Sequence[float] = ()
) -> str:
    """Render one number so a verdict printed beside it cannot contradict it.

    The neighbouring population to :func:`render_comparison`, and the one its
    own arms provably cannot reach: they require a **threshold** to be in the
    string, and `cli._format_text_table` publishes a cosine beside its
    ``verdict`` with no threshold in the table at all (#179).

    At three places against the shipped ``DEFAULT_THRESHOLD = 0.85``, three rows
    of one table read::

        verdict   cosine  snapshot
        -------- -------  ------------------------
        fail      0.850   snapshots/just-below.yml
        pass      0.850   snapshots/exactly-at.yml
        pass      0.850   snapshots/just-above.yml

    One published number, two verdicts, **in a single table** rather than across
    two runs. And the gate is ``>=``, so ``0.850`` beside ``fail`` claims both
    "at or above the threshold" and "did not reach it".

    **The property is on the band, not on two numbers differing.** There is no
    second number in the table to widen against, so the rule is stated one level
    up: *the rendered value, read back as a float, falls on the same side of the
    boundary as the true value does* -- below, at, or above, the boundary being
    its own degenerate band. Three levels rather than two, because a "would the
    verdict flip" check is satisfied by a below-threshold value rendering **at**
    the threshold, which is exactly the string a passing row produces.

    **Per row, against that row's own threshold.** Per-snapshot tolerances mean
    two rows legitimately showing the same cosine with different verdicts is
    *correct*, so a run-level number in the header would be the wrong unit.

    Its own loop rather than ``render_comparison(value, boundary, places=...)[0]``:
    that delegation is wrong on signed zero (``-0.000`` and ``0.000`` are
    different strings for one value, so the pairwise loop stops while
    ``float("-0.000")`` is not below ``0.0``) and on a boundary that does not
    survive a round trip at *places*. Neither is reachable through
    ``_format_text_table`` today -- a cosine lives in ``[-1, 1]`` and the shipped
    threshold is round -- which is the point: a rule stated over the current call
    sites is not the rule it claims to be. Duplicated from
    ``llm-eval-harness``' D-028 rather than shared, for the reason D-012 already
    records for ``render_comparison`` itself.

    ``repr`` is the terminal fallback, as in :func:`render_comparison`: it
    round-trips a double by definition, so it classifies exactly.
    """
    # `others`: further boundaries the same verdict depends on. A `run` row's
    # verdict is decided at the threshold AND, under a warn band, at the warn
    # floor -- widening against the threshold alone printed `warn 0.800` and
    # `fail 0.800` in one table (#203). The rule is unchanged, stated over
    # every boundary: the rendering reads back on the same side of each.
    boundaries = (boundary, *others)
    targets = [_band(value, b) for b in boundaries]
    for width in range(places, max(places, COMPARISON_MAX_PLACES) + 1):
        rendered = f"{value:.{width}f}"
        if [_band(float(rendered), b) for b in boundaries] == targets:
            return rendered
    return repr(value)
