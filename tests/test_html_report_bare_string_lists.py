"""`render_report` refuses a bare string for `skipped` / `unmatched` (#265).

Measured on main: `render_report([], skipped="refund-v1", unmatched="old.yml")`
headed the page "9 skipped 7 unmatched" and listed one character per row.
"""

from __future__ import annotations

import pytest

from prompt_regression import render_report


@pytest.mark.parametrize("name", ["skipped", "unmatched"])
@pytest.mark.parametrize(
    "value", ["refund-v1", b"refund-v1", bytearray(b"refund-v1")], ids=["str", "bytes", "bytearray"]
)
def test_a_bare_string_is_refused_naming_the_argument(name: str, value: object) -> None:
    with pytest.raises(ValueError, match=rf"^{name} must be a list of names, not a bare "):
        render_report([], **{name: value})  # type: ignore[arg-type]


def test_the_refusal_names_the_fix_for_a_str() -> None:
    with pytest.raises(ValueError, match=r"pass \['refund-v1'\]"):
        render_report([], skipped="refund-v1")


@pytest.mark.parametrize("seq", [list, tuple], ids=["list", "tuple"])
def test_a_list_still_renders_one_entry_per_name(seq: type) -> None:
    page = render_report([], skipped=seq(["refund-v1"]), unmatched=seq(["old.yml"]))
    assert ">1</" in page or "1 skipped" in page.replace("<", " ").replace(">", " ")
    assert "refund-v1" in page
    assert "old.yml" in page
    assert ">r<" not in page


def test_the_default_renders_as_before() -> None:
    assert render_report([]) == render_report([], skipped=(), unmatched=())
