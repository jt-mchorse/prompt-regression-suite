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

# Cap the target basename's contribution to the temp filename. The temp name is
# `.<base>.<random>.tmp`; the affixes add ~13-20 bytes, so prepending a full
# basename that is itself near NAME_MAX (255 on ext4/APFS) overflows the limit
# and the write fails with `OSError: [Errno 63] File name too long` — even though
# a plain `Path.write_text` of that same target succeeds (sibling of
# rag-production-kit#128 and mcp-server-cookbook#96). The base in the temp name
# is cosmetic (`ls`-ability); uniqueness comes from `NamedTemporaryFile`'s random
# component, so truncating it is safe. Budget is in BYTES (NAME_MAX is a byte
# limit) and we trim on a char boundary so multibyte names are never split
# mid-codepoint.
_MAX_TEMP_BASE_BYTES = 200


def _cap_base_for_temp(base: str) -> str:
    if len(base.encode("utf-8")) <= _MAX_TEMP_BASE_BYTES:
        return base
    out = base
    while out and len(out.encode("utf-8")) > _MAX_TEMP_BASE_BYTES:
        out = out[:-1]
    return out


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
            prefix=f".{_cap_base_for_temp(target.name)}.",
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
    # YAML parses an unquoted `schema_version: 1` as the int 1, not the string
    # "1". `save_snapshot` writes the quoted '1', but a hand-authored /
    # PR-reviewed snapshot (the D-003 use case) naturally omits the quotes —
    # and an int-vs-str rejection here reads as a baffling "is 1 … supports
    # '1'". Compare on the string form so `1` and `'1'` are the same version,
    # while a genuinely-different version ("2", 2, "1.5") still rejects.
    if str(version) != SCHEMA_VERSION:
        raise SnapshotValidationError(
            f"{p}: snapshot schema_version is {version!r}, "
            f"this reader only supports {SCHEMA_VERSION!r}"
        )
    # Normalize to the canonical string before `from_dict`, whose strict
    # `_require_str(schema_version)` would otherwise re-reject the int form.
    return Snapshot.from_dict({**data, "schema_version": SCHEMA_VERSION})
