"""Lock tests for #131: a long digit run in the candidate response.

`_extract_number` converted a regex match with a bare `int(raw)` / `float(raw)`.
Both are total for every number a model plausibly writes and fail on exactly one
shape — a very long digit run, which is what a degenerate repetition loop
produces. So the extractor broke on the pathology the tool exists to catch.

The two failures are different and neither was handled:

* `int` raises `ValueError` past CPython's int↔str digit cap (4300 by default).
  Nothing in `diff_slots`/`diff_response` catches it, so it escaped as a raw
  traceback at exit 1 — the contract #99/#111/#113/#115/#117/#119/#126 close
  everywhere else.
* `float` does **not** raise. `float("9" * 400)` is `inf`, which passed the
  `isinstance(actual, float)` check as `status: "ok"` and egressed into
  `--format json` as a bare `Infinity` token. That is not valid JSON, so a
  strict parser rejects the whole document.

The JSON assertions here parse with a `parse_constant` that raises, because
Python's own `json.loads` accepts `Infinity`/`NaN` by default — asserting only
that the output round-trips through `json.loads` would pass on exactly the
broken output this fixes.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

from prompt_regression import (
    CanonicalResponse,
    HashEmbedder,
    Prompt,
    ResponseShape,
    Snapshot,
    diff_slots,
    extract_slots,
)
from prompt_regression.cli import main
from prompt_regression.io import save_snapshot

# Comfortably past CPython's default 4300-digit int↔str cap.
_HUGE_INT_DIGITS = sys.get_int_max_str_digits() + 700 if sys.get_int_max_str_digits() else 5000
# ~1.8e308 is the largest finite double, so 400 digits overflows to `inf`
# without `float()` raising anything.
_HUGE_FLOAT_DIGITS = 400

_INT_SPEC = {"refund_days": {"type": "integer", "description": "Number of days until refund."}}
_NUM_SPEC = {"amount": {"type": "number", "description": "dollars refunded to the customer"}}


def _strict_loads(text: str) -> object:
    """`json.loads`, but treating `Infinity`/`-Infinity`/`NaN` as invalid.

    Python accepts those bare tokens; `jq`, browser `JSON.parse`, and Go/Rust
    decoders do not. The permissive default is what let a non-finite value ship
    unnoticed.
    """

    def reject(constant: str) -> object:
        raise ValueError(f"non-JSON constant in output: {constant}")

    return json.loads(text, parse_constant=reject)


# --- the two failures, at the library boundary ------------------------------


def test_huge_integer_run_does_not_raise() -> None:
    text = f"The Pro plan has a {'9' * _HUGE_INT_DIGITS}-day refund window."
    with pytest.raises(ValueError, match="Exceeds the limit"):
        # Pinning *why* the guard is needed: this is the coercion the extractor
        # used to perform unguarded. If a future CPython lifts the cap, this
        # test says so rather than leaving the guard looking gratuitous.
        int("9" * _HUGE_INT_DIGITS)
    deltas = diff_slots(_INT_SPEC, text)
    assert [(d.name, d.actual_value, d.status) for d in deltas] == [
        ("refund_days", None, "missing")
    ]
    assert deltas[0].is_failure


def test_huge_float_run_is_not_reported_ok_as_infinity() -> None:
    text = f"You get {'9' * _HUGE_FLOAT_DIGITS} dollars back."
    # `float` does not raise here — it silently produces `inf`, which is the
    # whole reason a try/except around the coercion would not have been enough.
    assert math.isinf(float("9" * _HUGE_FLOAT_DIGITS))
    deltas = diff_slots(_NUM_SPEC, text)
    assert deltas[0].status == "missing"
    assert deltas[0].actual_value is None


@pytest.mark.parametrize(
    ("spec", "digits"),
    [(_INT_SPEC, _HUGE_INT_DIGITS), (_NUM_SPEC, _HUGE_FLOAT_DIGITS)],
)
def test_extract_slots_omits_an_unrepresentable_value(spec: dict, digits: int) -> None:
    text = f"The answer is {'9' * digits} exactly."
    assert extract_slots(text, spec) == {}


# --- skip-and-continue: a good number elsewhere is still found --------------


def test_a_representable_number_elsewhere_survives_an_unrepresentable_neighbour() -> None:
    # Pre-fix the hint path committed to the match nearest the hint word, so one
    # unrepresentable token poisoned the extraction even with a perfectly good
    # number in the same sentence.
    text = f"A 14-day window and {'9' * _HUGE_FLOAT_DIGITS} dollars back."
    assert extract_slots(text, _NUM_SPEC) == {"amount": 14.0}


def test_all_matches_unrepresentable_falls_back_to_missing() -> None:
    big = "9" * _HUGE_FLOAT_DIGITS
    text = f"{big} dollars, or {big} dollars."
    deltas = diff_slots(_NUM_SPEC, text)
    assert deltas[0].status == "missing"


# --- unchanged behaviour ----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "spec", "expected"),
    [
        # Hint proximity: "days" is nearer 30 than 14.
        ("14 dollars. The window is 30 days.", _INT_SPEC, {"refund_days": 30}),
        # No hint word present → first match wins.
        ("Values are 7 and 9.", {"n": {"type": "integer", "description": ""}}, {"n": 7}),
        # A hyphenated token's `-` is not a unary minus, and the lookbehind
        # rejects the bare digit too — `W-2` yields nothing rather than `-2`.
        ("Form W-2 must be filed.", {"n": {"type": "integer", "description": ""}}, {}),
        # A real negative still parses.
        ("The delta is -3 today.", {"n": {"type": "integer", "description": ""}}, {"n": -3}),
        # Leading-dot and trailing-dot float shapes.
        ("It grew by .5 percent.", {"n": {"type": "number", "description": ""}}, {"n": 0.5}),
        ("It grew by 3. Then stopped.", {"n": {"type": "number", "description": ""}}, {"n": 3.0}),
    ],
)
def test_representable_extraction_is_unchanged(text: str, spec: dict, expected: dict) -> None:
    assert extract_slots(text, spec) == expected


def test_a_long_but_representable_integer_still_extracts() -> None:
    # The guard must reject only what cannot be represented, not "big" numbers.
    # 4299 digits is one under the cap.
    digits = (sys.get_int_max_str_digits() or 4300) - 1
    raw = "9" * digits
    assert extract_slots(f"The count is {raw}.", {"n": {"type": "integer", "description": ""}}) == {
        "n": int(raw)
    }


# --- end to end through the shipped CLI -------------------------------------


def _snapshot_with_slots(path: Path, slots: dict) -> Path:
    embedder = HashEmbedder()
    canonical = "The Pro plan has a 14-day refund window from purchase."
    snap = Snapshot(
        id="refund-window",
        prompt=Prompt(model="claude-haiku-4-5", user="What is the refund window?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots=slots),
        canonical=CanonicalResponse(
            text=canonical,
            embedding=embedder.embed(canonical),
            embedding_model=embedder.model_name,
        ),
    )
    save_snapshot(snap, path)
    return path


@pytest.mark.parametrize(
    ("slots", "digits"),
    [(_INT_SPEC, _HUGE_INT_DIGITS), (_NUM_SPEC, _HUGE_FLOAT_DIGITS)],
)
def test_cli_diff_json_survives_and_stays_strict_json(
    tmp_path: Path, capsys, monkeypatch, slots: dict, digits: int
) -> None:
    snap = _snapshot_with_slots(tmp_path / "s.snapshot.yaml", slots)
    candidate = f"The Pro plan has a {'9' * digits}-day refund window."
    monkeypatch.setattr("sys.stdin", _Stdin(candidate))

    rc = main(["diff", "--snapshot", str(snap), "--candidate-stdin", "--format", "json"])

    out = capsys.readouterr()
    # Pre-fix the integer case died at exit 1 with a traceback; the exit code
    # here is the diff verdict, and what matters is that it is a *verdict*.
    assert rc in (0, 1)
    assert "Traceback" not in out.err
    payload = _strict_loads(out.out)
    assert isinstance(payload, dict)
    statuses = {d["name"]: d["status"] for d in payload["slot_deltas"]}
    assert statuses[next(iter(slots))] == "missing"


class _Stdin:
    """Minimal stdin stand-in — the CLI only reads `.read()`."""

    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text
