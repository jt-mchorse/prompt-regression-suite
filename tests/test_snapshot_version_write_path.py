"""`save_snapshot` refuses a `schema_version` its own `load_snapshot` refuses (#165).

`load_snapshot` required `str(schema_version) == SCHEMA_VERSION` and raised with
the dedicated `code="schema_version"`. `save_snapshot` required nothing:
`Snapshot.__post_init__` runs `_require_str(self.schema_version)` and stops, so
the field was checked for being *a string* and never for being *the supported
version*. The canonical writer emitted files its own loader refuses.

Measured before the fix::

    schema_version='1'   (control)   round-trips IDENTICAL
    schema_version='2'               WRITES A FILE ITS LOADER REFUSES
    schema_version='1.5'             WRITES A FILE ITS LOADER REFUSES
    schema_version='01'              WRITES A FILE ITS LOADER REFUSES
    schema_version=''                construction REFUSED (correct, unchanged)

`'01'` is the row worth naming. The comparison is on `str(version)`
deliberately: YAML parses an unquoted `schema_version: 1` as the int `1` while
`save_snapshot` writes the quoted `'1'`, and rejecting a hand-authored snapshot
(the D-003 workflow) with "is 1 ... supports '1'" reads as nonsense. `'01'` is a
string that survives that leniency and still fails — and nothing on the write
side ever looked at it.

Measured and **not** a finding, recorded here so it is not re-hunted: a lone
surrogate (`U+DCFF`, the `sys.argv` `surrogateescape` road `io._eprint`'s
docstring names as real) round-trips byte-identically through
`save_snapshot` → `load_snapshot` in `id`, `prompt.user`, `notes` and
`canonical.text`. Those rows are asserted below as controls rather than left as
a claim in this docstring.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
import yaml

from prompt_regression import io as io_module
from prompt_regression.io import SCHEMA_VERSION, load_snapshot, save_snapshot
from prompt_regression.schema import (
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
    SnapshotValidationError,
)

LONE_SURROGATE = chr(0xDCFF)


def _snapshot(**overrides: Any) -> Snapshot:
    base: dict[str, Any] = {
        "id": "s1",
        "prompt": Prompt(model="claude-opus-4-8", user="hello"),
        "response_shape": ResponseShape(semantic_categories=["a"], structured_slots={}),
        "canonical": CanonicalResponse(text="hi", embedding=[0.1, 0.2], embedding_model="hash-8"),
    }
    base.update(overrides)
    return Snapshot(**base)


# Every row passes the kwarg. An earlier draft of this table put three of the
# values in the *label* only, so three rows silently exercised the default
# snapshot and reported "round-trips OK" — a vacuous table that agreed with the
# unfixed code. The assertion in `_write` below makes that impossible to repeat.
REFUSED_VERSIONS: tuple[str, ...] = ("2", "1.5", "01", "1 ", " 1", "v1")


def _write(tmp_path: Path, **overrides: Any) -> Path:
    assert overrides, "vacuous row: no override passed"
    destination = tmp_path / "snap.yaml"
    save_snapshot(_snapshot(**overrides), destination)
    return destination


@pytest.mark.parametrize("version", REFUSED_VERSIONS, ids=repr)
def test_save_refuses_a_version_load_would_refuse(tmp_path: Path, version: str) -> None:
    with pytest.raises(SnapshotValidationError, match="schema_version") as excinfo:
        save_snapshot(_snapshot(schema_version=version), tmp_path / "snap.yaml")
    # The classification, not only the message: `CODES` exists so "migration
    # tooling can route on the code without parsing the prose" (#155), and a
    # write-side refusal is the same classification as a read-side one.
    assert excinfo.value.code == "schema_version"


@pytest.mark.parametrize("version", REFUSED_VERSIONS, ids=repr)
def test_a_refusal_writes_nothing(tmp_path: Path, version: str) -> None:
    """Before any bytes, so a refusal cannot truncate or half-overwrite a
    snapshot that was already on disk.
    """
    destination = tmp_path / "snap.yaml"
    save_snapshot(_snapshot(), destination)
    before = destination.read_bytes()
    with pytest.raises(SnapshotValidationError, match="schema_version"):
        save_snapshot(_snapshot(schema_version=version), destination)
    assert destination.read_bytes() == before


@pytest.mark.parametrize("version", REFUSED_VERSIONS, ids=repr)
def test_load_refuses_the_same_versions(tmp_path: Path, version: str) -> None:
    """Both halves of the shared rule, over one table.

    The file is written by hand rather than by `save_snapshot`, which now
    refuses these — that is the point of the pair.
    """
    destination = tmp_path / "snap.yaml"
    payload = _snapshot().to_dict()
    payload["schema_version"] = version
    destination.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="schema_version") as excinfo:
        load_snapshot(destination)
    assert excinfo.value.code == "schema_version"


# --- the rows that must NOT move ------------------------------------------


def test_the_supported_version_still_round_trips(tmp_path: Path) -> None:
    """The control. Without it the table above is satisfied by a
    `save_snapshot` that refuses everything.
    """
    destination = _write(tmp_path, schema_version=SCHEMA_VERSION)
    assert load_snapshot(destination).schema_version == SCHEMA_VERSION


def test_the_default_still_round_trips(tmp_path: Path) -> None:
    """A `Snapshot` built without naming a version at all — the ordinary case,
    and the one every other test in this suite depends on.
    """
    destination = tmp_path / "snap.yaml"
    save_snapshot(_snapshot(), destination)
    assert load_snapshot(destination).schema_version == SCHEMA_VERSION


def test_an_unquoted_yaml_int_is_still_accepted_on_read(tmp_path: Path) -> None:
    """The `str()` leniency, which is part of the shared rule and not a
    caller's business.

    YAML parses an unquoted `schema_version: 1` as the int `1`. Rejecting a
    hand-authored snapshot (D-003) with "is 1 ... supports '1'" reads as
    nonsense, so the comparison is on the string form — and this row is what
    stops the shared helper being "simplified" into `version != SCHEMA_VERSION`.
    """
    destination = tmp_path / "snap.yaml"
    payload = _snapshot().to_dict()
    payload["schema_version"] = 1  # the int, as YAML would parse it
    destination.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    assert load_snapshot(destination).schema_version == SCHEMA_VERSION


@pytest.mark.parametrize("bad", [1, 1.0, None, True, ["1"]], ids=repr)
def test_a_non_string_version_is_still_refused_at_construction(bad: Any) -> None:
    """`_require_str` owns this, and the shared version rule must not relax it.

    The helper compares on `str(version)`, so `str(1) == "1"` would *pass* the
    version check — the string requirement has to keep firing first, at
    construction, or `Snapshot(schema_version=1)` becomes legal by accident.
    """
    with pytest.raises(SnapshotValidationError, match="schema_version"):
        _snapshot(schema_version=bad)


def test_an_empty_version_is_still_refused_at_construction() -> None:
    with pytest.raises(SnapshotValidationError, match="schema_version"):
        _snapshot(schema_version="")


# --- measured clean, kept as controls --------------------------------------


@pytest.mark.parametrize(
    ("label", "overrides", "read"),
    [
        ("id", {"id": f"s{LONE_SURROGATE}1"}, lambda s: s.id),
        (
            "prompt.user",
            {"prompt": Prompt(model="m", user=f"hi{LONE_SURROGATE}")},
            lambda s: s.prompt.user,
        ),
        ("notes", {"notes": f"n{LONE_SURROGATE}"}, lambda s: s.notes),
        (
            "canonical.text",
            {
                "canonical": CanonicalResponse(
                    text=f"hi{LONE_SURROGATE}", embedding=[0.1], embedding_model="e"
                )
            },
            lambda s: s.canonical.text,
        ),
    ],
    ids=["id", "prompt.user", "notes", "canonical.text"],
)
def test_a_lone_surrogate_round_trips_byte_identically(
    tmp_path: Path, label: str, overrides: dict[str, Any], read: Any
) -> None:
    """Not a finding — measured clean and pinned so it is not re-hunted.

    `U+DCFF` is the `sys.argv` `surrogateescape` road `io._eprint`'s docstring
    names as real. Every string field survives the YAML write and the read back
    unchanged. The assertion is on the VALUE, not on the absence of an
    exception: "it did not raise" would have passed for a writer that silently
    replaced the character.
    """
    original = _snapshot(**overrides)
    destination = tmp_path / "snap.yaml"
    save_snapshot(original, destination)
    assert read(load_snapshot(destination)) == read(original)


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")], ids=repr)
def test_a_non_finite_embedding_is_refused_at_construction(value: float) -> None:
    """Also measured clean: the `nan`/`inf` class two sibling repos hit today
    cannot reach this writer, because `CanonicalResponse` rejects it first.
    """
    with pytest.raises(SnapshotValidationError, match="finite"):
        CanonicalResponse(text="hi", embedding=[value], embedding_model="e")


# --- one definition, not a copy -------------------------------------------


def test_both_seams_call_the_shared_rule() -> None:
    """The copy-instead-of-share neighbour passes every behavioural row above —
    it has done so in four sibling repos today — so only a structural check
    separates it.
    """
    for func in (save_snapshot, load_snapshot):
        assert "_require_supported_schema_version" in inspect.getsource(func), (
            f"{func.__name__} carries its own copy of the version rule"
        )


def test_the_version_comparison_is_written_once() -> None:
    """Counted over AST string literals and comparison nodes rather than raw
    source text: the docstrings above quote the message, and a raw `.count`
    would false-hit on the prose explaining the fix.
    """
    import ast

    tree = ast.parse(Path(io_module.__file__).read_text(encoding="utf-8"))
    comparisons = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Call)
        and isinstance(node.left.func, ast.Name)
        and node.left.func.id == "str"
        and any(isinstance(c, ast.Name) and c.id == "SCHEMA_VERSION" for c in node.comparators)
    ]
    assert len(comparisons) == 1, (
        f"the `str(version) != SCHEMA_VERSION` comparison appears {len(comparisons)} "
        "times; it must live once, in _require_supported_schema_version"
    )
