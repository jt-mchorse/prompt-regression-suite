"""Collecting-mode lint for a snapshots directory (#49).

``prompt-snap run`` aborts on the first malformed snapshot under the
chosen directory because it calls ``load_snapshot(path)`` per file and
``load_snapshot`` raises ``SnapshotValidationError`` / ``YAMLError``
on the first issue. A directory of 30 snapshots with two bad ones
forces the operator into fix-and-retry cycles.

This module mirrors the eval-harness ``validate_dataset`` pattern: walk
the snapshot files in one pass, collect every problem as a
:class:`ValidationFinding`, return a :class:`ValidationReport` the CLI
can render or emit as JSON. The lone supplemental check (over what
``load_snapshot`` does file-by-file) is ``duplicate_id`` — the run path
silently key-collides on identical ``Snapshot.id`` across files, so
surfacing those at validate time saves a separate audit.

Finding codes (stable, JSON-routable):

- ``parse``          — YAML decode failure or top-level non-mapping.
- ``schema_version`` — schema_version mismatch (its own code so
                       migration tooling can route on it without
                       parsing the schema-error prose).
- ``schema``         — any other ``SnapshotValidationError`` raised by
                       ``Snapshot.from_dict`` (missing required field,
                       wrong type, malformed embedding vector, ...).
- ``duplicate_id``   — two snapshot files in the dir resolve to the
                       same ``Snapshot.id``.
- ``unreadable``     — the file matched a snapshot glob but could not
                       be *read* (permission denied, a directory whose
                       name ends in ``.yaml``, a broken symlink, a file
                       deleted mid-walk). Its own code, not ``parse``:
                       nothing was parsed, and an operator routing on
                       the code needs to fix a filesystem problem, not
                       a snapshot's contents.
- ``empty``          — directory matched zero snapshot files.

The code list above is not prose — it is derived-locked against
:data:`FINDING_CODES` and the README by ``tests/test_validate.py`` (#133).

Exit-code shape (mapped by the CLI): 0 clean / 1 findings / 2 missing
dir or *directory-level* I/O error. A **per-file** I/O error is a
finding, not an abort — collecting mode is the whole point of this
module, and before #133 a single ``chmod 000`` snapshot took the entire
report down with it, reporting nothing about any other file in the
directory. Same convention as ``eval-harness validate`` and
``scripts/audit_phase_a.py`` in portfolio-ops.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .io import SNAPSHOT_GLOBS, iter_snapshot_paths, load_snapshot
from .schema import SnapshotValidationError

# Historical private alias; `io.SNAPSHOT_GLOBS` is the single definition
# (#135). `io` is importable from here without the cycle that `cli` would
# have introduced.
_SNAPSHOT_GLOBS = SNAPSHOT_GLOBS

#: Every ``ValidationFinding.code`` this module can emit, in the order the
#: module docstring documents them. The one source of truth: the docstring
#: list above and the README's `validate` bullet are both checked against
#: this tuple by ``tests/test_validate.py``, so a new code cannot be added
#: to the emit sites and documented in only one of the two places (#133).
FINDING_CODES: tuple[str, ...] = (
    "parse",
    "schema_version",
    "schema",
    "duplicate_id",
    "unreadable",
    "empty",
)


@dataclass(frozen=True)
class ValidationFinding:
    """One per-file issue surfaced by :func:`validate_snapshots`.

    ``path`` is the file's path relative to the validated directory
    (POSIX-style so JSON consumers parse it identically across
    platforms). ``code`` is one of the stable finding-code strings
    documented at module level. ``reason`` is the human-readable
    message — for ``SnapshotValidationError`` it's the message the
    loader produced, unmodified.
    """

    path: str
    reason: str
    code: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "reason": self.reason, "code": self.code}


@dataclass(frozen=True)
class ValidationReport:
    """Result of walking a snapshots directory in collecting mode.

    ``ok`` is true iff zero findings AND the directory contained at
    least one valid snapshot. An empty directory is a finding shape
    (``empty``), not a healthy state — same convention as
    ``eval-harness validate``'s empty-file finding.
    """

    directory: str
    n_files: int
    n_valid: int
    findings: tuple[ValidationFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings and self.n_valid > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "directory": self.directory,
            "ok": self.ok,
            "n_files": self.n_files,
            "n_valid": self.n_valid,
            "findings": [f.to_dict() for f in self.findings],
        }


# Historical private alias; the implementation lives in `io` (#135). Three
# copies of this function each carried a docstring explaining why it had to be
# duplicated — "importing from cli would pull in argparse machinery just to
# share four lines". True of `cli`, and irrelevant to `io`, which every one of
# these modules already imports.
_iter_snapshot_paths = iter_snapshot_paths


def validate_snapshots(directory: str | Path) -> ValidationReport:
    """Walk ``directory`` for snapshot files and lint each in collecting mode.

    Returns one :class:`ValidationFinding` per malformed file (and one
    extra per ``duplicate_id`` collision). Raises ``FileNotFoundError``
    if the directory doesn't exist — the CLI maps that to exit 2 so
    the operator can distinguish "directory missing" from "directory
    is fine but every file is malformed."
    """
    snapshots_dir = Path(directory)
    if not snapshots_dir.exists() or not snapshots_dir.is_dir():
        raise FileNotFoundError(snapshots_dir)

    paths = _iter_snapshot_paths(snapshots_dir)
    findings: list[ValidationFinding] = []
    seen_ids: dict[str, str] = {}
    n_valid = 0

    for path in paths:
        rel = path.relative_to(snapshots_dir).as_posix()
        try:
            with path.open("r", encoding="utf-8") as f:
                data: Any = yaml.safe_load(f)
        except OSError as e:
            # The *read* sibling of the decode failure handled just below. Both
            # surface at this one seam; only the decode half was ever brought
            # into collecting mode, so a single unreadable file — `chmod 000`, a
            # directory whose name ends in `.yaml` (the globs match it), a broken
            # symlink — escaped as an OSError, hit the CLI's directory-level
            # `except OSError` arm, and took the whole report down at exit 2:
            # zero findings for every other file in the pass, mis-labelled
            # "failed to walk snapshots directory" when the walk had succeeded
            # (#133). Nothing was parsed here, so this is not a `parse` finding.
            findings.append(
                ValidationFinding(path=rel, reason=f"unreadable: {e}", code="unreadable")
            )
            continue
        except (yaml.YAMLError, UnicodeDecodeError) as e:
            # UnicodeDecodeError (a ValueError subclass, not a YAMLError) surfaces
            # at this same read seam when the file isn't valid UTF-8 — a decode
            # failure is a parse failure, so route it to the same `parse` finding
            # rather than letting it escape as a raw traceback at exit 1.
            findings.append(ValidationFinding(path=rel, reason=f"invalid YAML: {e}", code="parse"))
            continue
        if not isinstance(data, dict):
            findings.append(
                ValidationFinding(
                    path=rel,
                    reason="snapshot YAML must be a mapping at the top level",
                    code="parse",
                )
            )
            continue
        try:
            snap = load_snapshot(path)
        except OSError as e:
            # `load_snapshot` re-opens the file, so this is a second read seam,
            # not a redundant guard: the file can become unreadable between the
            # two opens (deleted mid-walk, permissions changed by a concurrent
            # sync). Same collecting-mode routing as the first seam (#133).
            findings.append(
                ValidationFinding(path=rel, reason=f"unreadable: {e}", code="unreadable")
            )
            continue
        except SnapshotValidationError as e:
            # Distinguish schema_version mismatch from other schema
            # errors so migration tooling can route on the code without
            # parsing the prose.
            code = "schema_version" if "schema_version" in str(e) else "schema"
            # The SnapshotValidationError reason includes the full path
            # prefix from load_snapshot; keep the original message so
            # operators get the same string the loader would have raised
            # — just routed via the report instead of an abort.
            findings.append(ValidationFinding(path=rel, reason=str(e), code=code))
            continue

        if snap.id in seen_ids:
            findings.append(
                ValidationFinding(
                    path=rel,
                    reason=(
                        f"duplicate snapshot id {snap.id!r}; "
                        f"first seen at {seen_ids[snap.id]}; "
                        "ids must be unique across the directory"
                    ),
                    code="duplicate_id",
                )
            )
            # Don't count the shadow file as valid; the run path would
            # silently overwrite the prior candidate lookup.
            continue
        seen_ids[snap.id] = rel
        n_valid += 1

    if not paths:
        findings.append(
            ValidationFinding(
                path=str(snapshots_dir),
                reason=(
                    f"no snapshot files under {snapshots_dir} (patterns considered: "
                    f"{', '.join(_SNAPSHOT_GLOBS)})"
                ),
                code="empty",
            )
        )

    return ValidationReport(
        directory=str(snapshots_dir),
        n_files=len(paths),
        n_valid=n_valid,
        findings=tuple(findings),
    )
