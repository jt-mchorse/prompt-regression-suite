"""File-mode contract for `prompt_regression.io.atomic_write_text` (#189).

The helper used to create its temp file through `tempfile.NamedTemporaryFile`,
which always creates 0600 whatever the umask is, and `os.replace` carried that
mode onto the target. A new snapshot or `--out` artifact came out owner-only,
and overwriting an existing 0644 snapshot (`prompt-snap update`) demoted it to
0600. `Path.write_text`, which the helper
replaced, did neither. Part of portfolio-ops#81.

The contract now matches `Path.write_text`: a new file gets ``0o666 & ~umask``
and an overwrite keeps the destination's existing mode.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from prompt_regression import (
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
    load_snapshot,
    save_snapshot,
)
from prompt_regression import io as io_mod
from prompt_regression import schema as schema_mod
from prompt_regression.io import atomic_write_text

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits and umask")


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def umask() -> Iterator[object]:
    """Set the process umask for one test, then restore the original."""
    saved: list[int] = []

    def _set(value: int) -> None:
        old = os.umask(value)
        if not saved:
            saved.append(old)

    yield _set
    if saved:
        os.umask(saved[0])


@pytest.mark.parametrize(("mask", "expected"), [(0o022, 0o644), (0o077, 0o600), (0o002, 0o664)])
def test_new_file_mode_honours_umask(tmp_path: Path, umask, mask: int, expected: int) -> None:
    umask(mask)
    out = tmp_path / "new.json"
    atomic_write_text(out, "{}")
    assert out.read_text(encoding="utf-8") == "{}"
    assert _mode(out) == expected, (
        f"umask {mask:#o}: new file is {_mode(out):#o}, expected {expected:#o} "
        "(0o666 & ~umask, as Path.write_text gives)"
    )


@pytest.mark.parametrize("existing", [0o644, 0o600, 0o640, 0o664])
def test_overwrite_preserves_existing_mode(tmp_path: Path, umask, existing: int) -> None:
    # umask 022 would give 0644 to a fresh file; the existing mode must win
    # whether it is wider, narrower or just different.
    umask(0o022)
    out = tmp_path / "artifact.json"
    out.write_text("old", encoding="utf-8")
    os.chmod(out, existing)
    atomic_write_text(out, "new")
    assert out.read_text(encoding="utf-8") == "new"
    assert _mode(out) == existing, (
        f"overwrite changed {existing:#o} to {_mode(out):#o}; Path.write_text keeps the mode"
    )


def test_umask_is_not_changed_by_the_write(tmp_path: Path, umask) -> None:
    """The helper must let the kernel apply the umask, not read it through
    `os.umask(0)` (process-wide, racy across threads) and leave it changed."""
    umask(0o027)
    atomic_write_text(tmp_path / "a.txt", "x")
    current = os.umask(0o027)
    assert current == 0o027


def test_no_temp_file_left_and_name_shape_kept(
    tmp_path: Path, umask, monkeypatch: pytest.MonkeyPatch
) -> None:
    umask(0o022)
    seen: list[str] = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(Path(src).name)
        real_replace(src, dst)

    monkeypatch.setattr(io_mod.os, "replace", spy)
    atomic_write_text(tmp_path / "out.json", "{}")
    assert len(seen) == 1
    assert seen[0].startswith(".out.json.")
    assert seen[0].endswith(".tmp")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.json"]


def test_open_failure_after_create_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If `open` fails after its opener created the file, the temp file is
    unlinked rather than left behind as a `.tmp`."""

    def create_then_fail(file, mode, *, encoding, opener):
        os.close(opener(os.fspath(file), 0))
        raise LookupError("simulated text-layer failure")

    monkeypatch.setattr(io_mod, "open", create_then_fail, raising=False)
    with pytest.raises(LookupError):
        atomic_write_text(tmp_path / "out.txt", "x")
    assert list(tmp_path.iterdir()) == []


def _snapshot() -> Snapshot:
    return Snapshot(
        id="mode-test",
        prompt=Prompt(model="claude-haiku-4-5-20251001", user="hi", max_tokens=16),
        response_shape=ResponseShape(semantic_categories=["greeting"]),
        canonical=CanonicalResponse(text="hello", embedding=[0.25, 0.5], embedding_model="hash"),
    )


def _save_new_and_overwrite(tmp_path: Path) -> None:
    # One snapshot, saved and compared. `created_at` defaults to the wall
    # clock at one-second resolution, so building a second `_snapshot()` to
    # compare against fails whenever the two calls straddle a second (#201).
    snap = _snapshot()
    out = tmp_path / "snapshots" / "mode-test.snapshot.yaml"
    save_snapshot(snap, out)
    assert load_snapshot(out) == snap
    assert _mode(out) == 0o644

    os.chmod(out, 0o640)
    save_snapshot(snap, out)
    assert _mode(out) == 0o640


def test_save_snapshot_real_caller_new_and_overwrite(tmp_path: Path, umask) -> None:
    """A real caller: `save_snapshot`, which `prompt-snap update` uses to
    rewrite a committed snapshot in place."""
    umask(0o022)
    _save_new_and_overwrite(tmp_path)


class _TickingDatetime(datetime):
    """A clock that is one second later on every read, so every pair of
    reads straddles a second boundary."""

    _ticks = 0

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        cls._ticks += 1
        return datetime(2026, 1, 1, tzinfo=tz) + timedelta(seconds=cls._ticks)


def test_save_snapshot_round_trip_holds_across_a_second_boundary(
    tmp_path: Path, umask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#201: main went red when the real-caller test above built its expected
    snapshot one second after the saved one. Drive the same body under a clock
    that ticks on every read; it must still pass."""
    monkeypatch.setattr(schema_mod, "datetime", _TickingDatetime)
    assert _snapshot().created_at != _snapshot().created_at  # the clock does tick
    umask(0o022)
    _save_new_and_overwrite(tmp_path)
