"""`save_snapshot` never writes a file `load_snapshot` refuses (#310).

Every schema rule runs in the constructors, and the dataclasses are mutable:
`update` itself sets `notes` after construction. A field changed after loading
to an invalid value was written to disk, over a good snapshot in place, and the
file then failed to load in `run`, `validate` and `update` (the remedy). #165,
#276 and #278 each closed one field; the writer now reads its own output back
through the loader before writing anything.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from prompt_regression import load_snapshot, save_snapshot
from prompt_regression.schema import Snapshot, SnapshotValidationError

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "snapshots"


def _set_tolerance(s: Snapshot) -> None:
    s.tolerance = 1.5


def _set_tolerance_str(s: Snapshot) -> None:
    s.tolerance = "0.9"  # type: ignore[assignment]


def _dup_category(s: Snapshot) -> None:
    s.response_shape.semantic_categories.append(s.response_shape.semantic_categories[0])


def _bad_slot_type(s: Snapshot) -> None:
    next(iter(s.response_shape.structured_slots.values()))["type"] = "list"


def _temperature(s: Snapshot) -> None:
    s.prompt.temperature = 5.0


def _nan_embedding(s: Snapshot) -> None:
    s.canonical.embedding[0] = float("nan")


MUTATIONS: dict[str, Callable[[Snapshot], None]] = {
    "tolerance=1.5": _set_tolerance,
    "tolerance='0.9'": _set_tolerance_str,
    "duplicate category": _dup_category,
    "slot type list": _bad_slot_type,
    "temperature=5.0": _temperature,
    "nan embedding": _nan_embedding,
}


@pytest.fixture
def snap_path(tmp_path: Path) -> Path:
    p = tmp_path / "refund_window_v1.yml"
    shutil.copy(EXAMPLES / "refund_window_v1.yml", p)
    return p


@pytest.mark.parametrize("name", list(MUTATIONS))
def test_a_mutation_the_loader_refuses_is_not_written(snap_path: Path, name: str) -> None:
    before = snap_path.read_bytes()
    s = load_snapshot(snap_path)
    MUTATIONS[name](s)
    with pytest.raises(
        SnapshotValidationError, match="refusing to write a snapshot load_snapshot would refuse"
    ):
        save_snapshot(s, snap_path)
    assert snap_path.read_bytes() == before
    load_snapshot(snap_path)  # still loads, so `update` can still open it


def test_a_valid_mutation_still_saves_and_reloads(snap_path: Path) -> None:
    """Control: `update`'s own pattern, a field set after construction."""
    s = load_snapshot(snap_path)
    s.notes = "re-baselined"
    s.tolerance = 0.8
    save_snapshot(s, snap_path)
    again = load_snapshot(snap_path)
    assert again.notes == "re-baselined"
    assert again.tolerance == 0.8


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("*.yml")))
def test_the_shipped_examples_still_save_reload_and_resave_stably(
    tmp_path: Path, name: str
) -> None:
    """Control: the read-back accepts what the writer always wrote. (The examples
    are hand-authored, so the first save may reformat them, as it did before.)"""
    s = load_snapshot(EXAMPLES / name)
    out = tmp_path / name
    save_snapshot(s, out)
    first = out.read_bytes()
    assert load_snapshot(out) == s
    save_snapshot(load_snapshot(out), out)
    assert out.read_bytes() == first
