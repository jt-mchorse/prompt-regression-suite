"""`atomic_write_text` refuses a read-only existing destination (#316).

`os.replace` swaps the directory entry, so the target's own write bit was
never consulted and a ``chmod 444`` file was silently rewritten -- while
`Path.write_text`, the call the helper replaced, raises ``PermissionError``.
The CLI write seams (`update`, every ``--out``) document a read-only path as
``error:`` + exit 2, and ``chmod a-w`` is the natural way to freeze a
baseline. Helper cases run both writers on the same layout, so the lock is
parity with `Path.write_text`.

Root bypasses permission bits (`Path.write_text` succeeds too), so the
read-only arms skip as root. GitHub's ubuntu runners run as the non-root
``runner`` user, so CI exercises them.
"""

from __future__ import annotations

import errno
import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from prompt_regression.cli import main as cli_main
from prompt_regression.io import atomic_write_text, save_snapshot
from tests.test_atomic_write import _sample_snapshot

pytestmark = [
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits"),
    pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses file permission bits, so a 0444 file stays writable",
    ),
]


def _write(writer: str, path: Path, text: str) -> None:
    if writer == "atomic":
        atomic_write_text(path, text)
    else:
        path.write_text(text)


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def frozen(tmp_path: Path) -> Iterator[Path]:
    """A 0444 file holding ``old``; made writable again for tmp_path cleanup."""
    path = tmp_path / "r.json"
    path.write_text("old\n")
    path.chmod(0o444)
    yield path
    path.chmod(0o644)


@pytest.mark.parametrize("writer", ["atomic", "write_text"])
def test_readonly_file_is_refused(frozen: Path, writer: str) -> None:
    with pytest.raises(PermissionError) as excinfo:
        _write(writer, frozen, "new\n")
    assert excinfo.value.errno == errno.EACCES
    assert frozen.read_text() == "old\n"
    assert _mode(frozen) == 0o444


def test_refusal_leaves_no_temp_file(frozen: Path) -> None:
    with pytest.raises(PermissionError):
        atomic_write_text(frozen, "new\n")
    assert sorted(p.name for p in frozen.parent.iterdir()) == ["r.json"]


@pytest.mark.parametrize("writer", ["atomic", "write_text"])
def test_readonly_file_behind_a_symlink_is_refused(tmp_path: Path, writer: str) -> None:
    # The check runs on the RESOLVED file (#219): a writable link name over a
    # read-only file must not get through.
    real = tmp_path / "real.md"
    real.write_text("old\n")
    real.chmod(0o444)
    link = tmp_path / "link.md"
    link.symlink_to(real)
    try:
        with pytest.raises(PermissionError):
            _write(writer, link, "new\n")
        assert real.read_text() == "old\n"
        assert link.is_symlink()
    finally:
        real.chmod(0o644)


@pytest.mark.parametrize("writer", ["atomic", "write_text"])
def test_writable_and_missing_targets_still_write(tmp_path: Path, writer: str) -> None:
    # Controls: the refusal is scoped to an existing unwritable file.
    owner_only = tmp_path / "owner.md"
    owner_only.write_text("old\n")
    owner_only.chmod(0o600)
    _write(writer, owner_only, "new\n")
    assert owner_only.read_text() == "new\n"
    assert _mode(owner_only) == 0o600

    missing = tmp_path / "new.md"
    _write(writer, missing, "fresh\n")
    assert missing.read_text() == "fresh\n"


def test_update_force_on_a_readonly_snapshot_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "s.snapshot.yaml"
    save_snapshot(_sample_snapshot(), path)
    before = path.read_bytes()
    path.chmod(0o444)
    try:
        rc = cli_main(
            [
                "update",
                "--snapshot",
                str(path),
                "--canonical",
                "The Pro plan now has a 30-day refund window.",
                "--force",
            ]
        )
        err = capsys.readouterr().err
        assert rc == 2
        assert err.startswith(f"error: failed to write {path}")
        assert path.read_bytes() == before
    finally:
        path.chmod(0o644)


def test_diff_out_on_a_readonly_file_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = tmp_path / "s.snapshot.yaml"
    save_snapshot(_sample_snapshot(), snap)
    out = tmp_path / "r.json"
    out.write_text("old\n")
    out.chmod(0o444)
    try:
        rc = cli_main(
            ["diff", "--snapshot", str(snap), "--candidate", "anything", "--out", str(out)]
        )
        err = capsys.readouterr().err
        assert rc == 2
        assert err.startswith(f"error: failed to write {out}")
        assert out.read_text() == "old\n"
    finally:
        out.chmod(0o644)
