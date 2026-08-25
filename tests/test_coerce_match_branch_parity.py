"""`_coerce_match`'s finiteness rule covers both branches (#147).

The guard read ``if not want_int and not math.isfinite(value)``, so the integer
branch had no magnitude bound at all. Measured on `main`, using the docstring's
own example input:

    digits            want_int=True        want_int=False
         3           int(3 digits)                 999.0
        20          int(20 digits)                 1e+20
       309         int(309 digits)                  None
       400         int(400 digits)                  None   <- the docstring's example
      4299        int(4299 digits)                  None
      4301                    None                  None   <- CPython digit cap

The docstring already stated the harm for the float branch: a non-finite value
"egressed into ``--format json`` as a bare ``Infinity`` token ... so ``jq`` /
``JSON.parse`` / a Go or Rust decoder rejects the whole document".

The integer route reaches the same destination by a **quieter** road. It emits
*valid* JSON, so there is no decoder rejection to notice — `JSON.parse` of a
400-digit integer literal returns `Infinity`, as do `jq` and most Go/Rust
`float64` decoders, with no error at all. The float route at least stopped the
pipeline.

Reachability is the docstring's own argument: a very long digit run "is the
shape a degenerate repetition loop produces", and such a loop hits
`_INTEGER_RE` exactly as readily as `_NUMBER_RE`.
"""

from __future__ import annotations

import json
import math

import pytest

from prompt_regression.diff import _coerce_match

# `float("9" * 308)` is 1e+308 (finite); 309 digits overflows. That boundary is
# a property of IEEE-754 doubles, not of this host — every conforming platform
# agrees, and the assertions below derive it rather than assuming it.
LARGEST_FINITE_DIGITS = 308
FIRST_OVERFLOWING_DIGITS = 309


def test_the_boundary_is_where_doubles_stop() -> None:
    """Anchor the two magic numbers in the property they encode, so a reader
    doesn't have to take 308/309 on faith."""
    assert math.isfinite(float("9" * LARGEST_FINITE_DIGITS))
    assert not math.isfinite(float("9" * FIRST_OVERFLOWING_DIGITS))


@pytest.mark.parametrize(
    "digits",
    [1, 2, 3, 20, 40, 100, 307, LARGEST_FINITE_DIGITS, FIRST_OVERFLOWING_DIGITS, 310, 400, 4299],
)
def test_both_branches_agree_on_representability(digits: int) -> None:
    """The parity property, stated directly: for any input, the two branches
    either both extract a value or both decline. That is the invariant the
    one-branch guard broke."""
    raw = "9" * digits
    as_int = _coerce_match(raw, want_int=True)
    as_float = _coerce_match(raw, want_int=False)
    assert (as_int is None) == (as_float is None), (
        f"{digits} digits: want_int=True gave {as_int!r}, want_int=False gave {as_float!r}"
    )


@pytest.mark.parametrize("digits", [FIRST_OVERFLOWING_DIGITS, 310, 400, 1000, 4299])
def test_an_unrepresentable_integer_is_declined(digits: int) -> None:
    """400 is the docstring's own example; on `main` it came back as a
    400-digit int with `status: "ok"`."""
    assert _coerce_match("9" * digits, want_int=True) is None


@pytest.mark.parametrize("digits", [1, 3, 20, 40, 307, LARGEST_FINITE_DIGITS])
def test_a_representable_integer_is_still_extracted(digits: int) -> None:
    """A value-domain fix that over-rejects is a different bug, not a stricter
    one — and this function exists because "a bare int(raw) / float(raw) is
    total for every number a model plausibly writes"."""
    value = _coerce_match("9" * digits, want_int=True)
    assert value is not None
    assert value == int("9" * digits)


def test_ordinary_values_are_untouched() -> None:
    assert _coerce_match("42", want_int=True) == 42
    assert _coerce_match("42", want_int=False) == 42.0
    assert _coerce_match("-17", want_int=True) == -17
    assert _coerce_match("3.5", want_int=False) == 3.5
    assert _coerce_match("0", want_int=True) == 0


def test_the_negative_side_of_the_boundary_too() -> None:
    """The bound is on magnitude, not on sign — a guard that closed only the
    positive half would be the same defect one operand over."""
    assert _coerce_match("-" + "9" * LARGEST_FINITE_DIGITS, want_int=True) is not None
    assert _coerce_match("-" + "9" * FIRST_OVERFLOWING_DIGITS, want_int=True) is None
    assert _coerce_match("-" + "9" * FIRST_OVERFLOWING_DIGITS, want_int=False) is None


def test_the_digit_cap_arm_still_works() -> None:
    """`int(raw)` raises ValueError past CPython's int<->str digit cap. That arm
    predates this change and must survive it."""
    import sys

    beyond_cap = "9" * (sys.get_int_max_str_digits() + 1)
    assert _coerce_match(beyond_cap, want_int=True) is None
    assert _coerce_match("not a number", want_int=True) is None
    assert _coerce_match("", want_int=False) is None


# ----------------------------------------------------------------------
# Egress: what a downstream decoder actually sees
# ----------------------------------------------------------------------


@pytest.mark.parametrize("digits", [FIRST_OVERFLOWING_DIGITS, 400, 4299])
def test_no_extracted_value_can_json_decode_to_infinity(digits: int) -> None:
    """The unit rule is "finite double"; the *harm* is what a consumer sees.

    Those are different assertions, so this one is made separately. A
    400-digit integer literal is valid JSON — Python round-trips it exactly —
    which is why nothing caught it. Any `float64`-based decoder (JavaScript,
    `jq`, most Go/Rust) turns it into `Infinity` instead, silently. Simulated
    here by the conversion those decoders perform.
    """
    value = _coerce_match("9" * digits, want_int=True)
    assert value is None  # nothing to egress in the first place

    # And the property that made it dangerous, demonstrated on the raw value so
    # the test documents *why* the rule above is the right rule.
    with pytest.raises(OverflowError):
        float(int("9" * digits))


def test_a_value_that_does_pass_survives_a_float64_decoder() -> None:
    """The positive half of the same claim: everything still accepted decodes
    to a finite number in a double-based consumer."""
    for digits in (1, 3, 20, 40, LARGEST_FINITE_DIGITS):
        value = _coerce_match("9" * digits, want_int=True)
        assert value is not None
        document = json.dumps({"actual_value": value})
        # `float(...)` is the conversion a float64 decoder performs on the
        # literal; `json.loads` alone would keep Python's arbitrary precision
        # and prove nothing about a JS or Go consumer.
        decoded = json.loads(document)["actual_value"]
        assert math.isfinite(float(decoded))
