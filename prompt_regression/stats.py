"""Directory-wide snapshot summary (issue #47).

``prompt-snap stats`` walks a snapshots directory and emits a
population-level summary the operator can scan at a glance: how many
snapshots total, which models cover which slots, what tolerance
distribution is in play, how structured-slot vs. plain-text use
breaks down. Closes the gap between per-snapshot regression signal
(``prompt-snap run``) and per-snapshot HTML reporting (``--format
html``) — neither tells you the shape of the snapshot population
itself.

The library entry point is ``collect_stats(directory) -> StatsReport``.
Operators wanting their own summary shape build it on top of the
frozen ``StatsReport.to_dict`` output rather than re-walking the
directory.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from prompt_regression.io import SNAPSHOT_GLOBS, iter_snapshot_paths, load_snapshot
from prompt_regression.schema import SnapshotValidationError

# Historical private alias. This used to be its own two-pattern tuple with
# a comment asking the next author to keep it in sync with `cli` — and it had
# already drifted (2 patterns vs 4), which only stayed harmless because the
# two it kept are supersets of the two it dropped. Now derived (#135).
_STATS_SNAPSHOT_GLOBS = SNAPSHOT_GLOBS


@dataclass(frozen=True)
class HistogramEntry:
    """One bin in a categorical histogram (model name → count, etc.).

    Sorted descending by ``count`` with alphabetical tiebreak when
    emitted, so the JSON shape is deterministic for downstream
    snapshot tests.
    """

    key: str
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "count": self.count}


@dataclass(frozen=True)
class ToleranceDistribution:
    """Summary of per-snapshot ``tolerance`` field across the directory.

    ``count_default`` is the number of snapshots that omit ``tolerance``
    entirely and inherit the per-run default. ``count_strictest`` is the
    number explicitly pinned to ``1.0`` — the *strictest* possible gate,
    not "always-pass": the diff requires ``cosine >= tolerance``, so
    ``1.0`` passes only an embedding-identical response and fails any
    drift. ``min`` / ``median`` / ``max`` are
    over the explicit numeric values only; ``None`` when no snapshot in
    the directory carries an explicit tolerance.
    """

    count_default: int
    count_explicit: int
    count_strictest: int
    min: float | None
    median: float | None
    max: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "count_default": self.count_default,
            "count_explicit": self.count_explicit,
            "count_strictest": self.count_strictest,
            "min": self.min,
            "median": self.median,
            "max": self.max,
        }


@dataclass(frozen=True)
class StatsReport:
    """Aggregate stats across one snapshots directory."""

    directory: str
    n_snapshots: int
    prompt_model_histogram: tuple[HistogramEntry, ...]
    embedding_model_histogram: tuple[HistogramEntry, ...]
    schema_version_histogram: tuple[HistogramEntry, ...]
    structured_slot_count_histogram: tuple[HistogramEntry, ...]
    tolerance_distribution: ToleranceDistribution

    def to_dict(self) -> dict[str, Any]:
        return {
            "directory": self.directory,
            "n_snapshots": self.n_snapshots,
            "prompt_model_histogram": [h.to_dict() for h in self.prompt_model_histogram],
            "embedding_model_histogram": [h.to_dict() for h in self.embedding_model_histogram],
            "schema_version_histogram": [h.to_dict() for h in self.schema_version_histogram],
            "structured_slot_count_histogram": [
                h.to_dict() for h in self.structured_slot_count_histogram
            ],
            "tolerance_distribution": self.tolerance_distribution.to_dict(),
        }


# Historical private alias; the implementation lives in `io` (#135). The
# duplication existed so importing `stats` wouldn't pull in the CLI module's
# argparse setup — `io` has no such baggage, so the constraint is satisfied
# without a second copy.
_iter_snapshot_paths = iter_snapshot_paths


def _hist(counter: Counter[Any]) -> tuple[HistogramEntry, ...]:
    """Render a ``Counter`` as a descending-by-count histogram tuple.

    Tiebreak by alpha on the string representation of the key so the
    JSON snapshot is deterministic across Python builds.
    """
    return tuple(
        HistogramEntry(key=str(k), count=c)
        for k, c in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    )


class StatsError(RuntimeError):
    """Raised when the stats walker can't produce a report.

    Today's two cases: directory is missing, or directory contains no
    matching snapshot files. The CLI converts this into exit 2.
    """


def collect_stats(directory: str | Path) -> StatsReport:
    """Walk ``directory`` and return aggregate stats over its snapshots.

    Raises :class:`StatsError` if the directory is missing, not a
    directory, empty of matching files, or contains a snapshot that
    fails to load (malformed YAML / schema-invalid / unreadable). A load
    failure names the offending file and points at ``prompt-snap
    validate`` — the same clean, exit-2 translation ``prompt-snap run``
    honors since #99 (before #99 ``run`` also leaked a raw traceback;
    ``stats`` was the last loader-walk still doing so, #115).
    """
    path = Path(directory)
    if not path.exists() or not path.is_dir():
        raise StatsError(f"snapshots directory not found: {path}")
    snapshot_paths = _iter_snapshot_paths(path)
    if not snapshot_paths:
        patterns = ", ".join(_STATS_SNAPSHOT_GLOBS)
        raise StatsError(f"no snapshot files under {path} (patterns considered: {patterns})")

    prompt_models: Counter[str] = Counter()
    embedding_models: Counter[str] = Counter()
    schema_versions: Counter[str] = Counter()
    slot_counts: Counter[int] = Counter()
    explicit_tolerances: list[float] = []
    count_default = 0
    count_strictest = 0

    for p in snapshot_paths:
        # Translate a malformed snapshot (bad YAML / schema-invalid / unreadable)
        # into a clean StatsError — which _stats_command maps to exit 2 — instead
        # of letting SnapshotValidationError / yaml.YAMLError / OSError escape as a
        # raw traceback at exit 1. This mirrors the guarded load_snapshot loop in
        # the `run` seam (cli.py) that #99 introduced; `stats` was the last
        # loader-walk still leaking the pre-#99 traceback (#115).
        rel = p.relative_to(path) if p.is_relative_to(path) else Path(p.name)
        try:
            snap = load_snapshot(p)
        except (OSError, UnicodeDecodeError, SnapshotValidationError, yaml.YAMLError) as e:
            raise StatsError(
                f"could not load snapshot {rel}: {e}\n"
                f"hint: run 'prompt-snap validate {path}' to list every "
                "malformed snapshot in one pass."
            ) from e
        prompt_models[snap.prompt.model] += 1
        embedding_models[snap.canonical.embedding_model] += 1
        schema_versions[snap.schema_version] += 1
        slot_counts[len(snap.response_shape.structured_slots)] += 1
        if snap.tolerance is None:
            count_default += 1
        else:
            explicit_tolerances.append(snap.tolerance)
            if snap.tolerance == 1.0:
                count_strictest += 1

    tol = ToleranceDistribution(
        count_default=count_default,
        count_explicit=len(explicit_tolerances),
        count_strictest=count_strictest,
        min=min(explicit_tolerances) if explicit_tolerances else None,
        median=float(median(explicit_tolerances)) if explicit_tolerances else None,
        max=max(explicit_tolerances) if explicit_tolerances else None,
    )

    return StatsReport(
        directory=str(path),
        n_snapshots=len(snapshot_paths),
        prompt_model_histogram=_hist(prompt_models),
        embedding_model_histogram=_hist(embedding_models),
        schema_version_histogram=_hist(schema_versions),
        structured_slot_count_histogram=_hist(slot_counts),
        tolerance_distribution=tol,
    )


def render_summary(report: StatsReport) -> str:
    """Human-readable one-paragraph rendering of ``report``.

    Surfaces the totals + each histogram + the tolerance distribution.
    Stable line ordering so a future snapshot test can lock it.
    """
    lines: list[str] = []
    lines.append(f"snapshots: {report.n_snapshots} under {report.directory}")
    if report.prompt_model_histogram:
        bits = ", ".join(f"{h.key}={h.count}" for h in report.prompt_model_histogram)
        lines.append(f"prompt.model: {bits}")
    if report.embedding_model_histogram:
        bits = ", ".join(f"{h.key}={h.count}" for h in report.embedding_model_histogram)
        lines.append(f"canonical.embedding_model: {bits}")
    if report.schema_version_histogram:
        bits = ", ".join(f"v{h.key}={h.count}" for h in report.schema_version_histogram)
        lines.append(f"schema_version: {bits}")
    if report.structured_slot_count_histogram:
        bits = ", ".join(f"{h.key}={h.count}" for h in report.structured_slot_count_histogram)
        lines.append(f"structured_slots count: {bits}")
    tol = report.tolerance_distribution
    tol_summary = (
        f"tolerance: default={tol.count_default} explicit={tol.count_explicit} "
        f"strictest={tol.count_strictest}"
    )
    if tol.count_explicit:
        tol_summary += f" min={tol.min} median={tol.median} max={tol.max}"
    lines.append(tol_summary)
    return "\n".join(lines)
