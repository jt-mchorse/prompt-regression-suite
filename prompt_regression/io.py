"""YAML load/save for Snapshot objects.

Round-trip identity is the contract: ``load_snapshot(save_snapshot(s)) == s``
for any snapshot whose fields validate. Reader is strict about schema
version mismatches — that's the diff-layer's escape hatch when an old
snapshot would otherwise be silently misinterpreted.
"""

from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import Any

import yaml

from .schema import SCHEMA_VERSION, Snapshot, SnapshotValidationError

PathArg = str | PathLike[str]


def save_snapshot(snapshot: Snapshot, path: PathArg) -> Path:
    """Write a snapshot to ``path`` as YAML. Returns the resolved path.

    The output is deterministic (sorted keys turned off so author order
    survives, default_flow_style=False so blocks are readable in PR diffs).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = snapshot.to_dict()
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            payload,
            f,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )
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
