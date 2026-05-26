"""YAML load/save for Snapshot objects.

Round-trip identity is the contract: ``load_snapshot(save_snapshot(s)) == s``
for any snapshot whose fields validate. Reader is strict about schema
version mismatches — that's the diff-layer's escape hatch when an old
snapshot would otherwise be silently misinterpreted.

Writes route through ``atomic_write_text`` (#39) so an interrupted
``save_snapshot`` cannot leave a snapshot YAML zero-length or partial.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from os import PathLike
from pathlib import Path
from typing import Any

import yaml

from .schema import SCHEMA_VERSION, Snapshot, SnapshotValidationError

PathArg = str | PathLike[str]


def atomic_write_text(path: PathArg, text: str) -> None:
    # `Path.write_text` is not atomic: SIGINT/SIGTERM/disk-full/OOM
    # between the implicit `open(..., "w")` truncate and `close()`
    # flush leaves the destination zero-length or partial. For this
    # repo the load-bearing case is `save_snapshot` — corrupting a
    # snapshot YAML breaks the round-trip-identity contract that the
    # diff layer relies on. The same harm class applies to CLI
    # `--out` artifacts and the HTML demo report.
    #
    # Pattern mirrors `llm-eval-harness/eval_harness/cli.py::_atomic_write_text`
    # (#48 there) and `llm-cost-optimizer/scripts/_io.py::atomic_write_text`
    # (#42 there) so the portfolio-wide shape is uniform.
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, target)
        tmp_path = None
    finally:
        if tmp_path is not None:
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()


def save_snapshot(snapshot: Snapshot, path: PathArg) -> Path:
    """Write a snapshot to ``path`` as YAML. Returns the resolved path.

    The output is deterministic (sorted keys turned off so author order
    survives, default_flow_style=False so blocks are readable in PR diffs).
    Atomic via ``atomic_write_text``.
    """
    p = Path(path)
    payload = snapshot.to_dict()
    rendered = yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    atomic_write_text(p, rendered)
    return p


def load_snapshot(path: PathArg) -> Snapshot:
    """Read a snapshot YAML file from ``path``.

    Validates schema_version against the package's current SCHEMA_VERSION;
    raises ``SnapshotValidationError`` on mismatch so callers can decide
    whether to migrate or skip.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data: Any = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SnapshotValidationError(f"{p}: snapshot YAML must be a mapping at the top level")
    version = data.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise SnapshotValidationError(
            f"{p}: snapshot schema_version is {version!r}, "
            f"this reader only supports {SCHEMA_VERSION!r}"
        )
    return Snapshot.from_dict(data)
