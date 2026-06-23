"""``prompt-snap`` CLI: run / update / diff for prompt regression snapshots.

Three subcommands:

- ``run`` walks a directory of ``*.snapshot.yaml`` files, loads candidate
  responses keyed by snapshot path from a JSONL, runs ``diff_response``
  against each, prints a per-snapshot status table, and exits non-zero
  on any ``fail`` verdict.
- ``update`` rewrites the canonical response (and its embedding) on a
  single snapshot. **Requires ``--force``** so a stray invocation can't
  silently re-baseline a snapshot that was failing.
- ``diff`` performs an ad-hoc single-snapshot diff against a candidate
  supplied via ``--candidate`` or stdin. Useful for "is this output
  drifting?" probes outside a CI run.

The default embedder is the dep-free ``HashEmbedder``. The
``--embedder`` flag accepts ``hash`` today; ``voyage`` / ``openai`` /
``cohere`` are reserved names that raise a clear "not yet wired" error
so the surface is stable while operator integrations land in follow-up
issues.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from .diff import (
    DEFAULT_THRESHOLD,
    DEFAULT_WARN_BAND,
    DiffResult,
    Embedder,
    EmbedderModelMismatchError,
    EmbeddingDimensionMismatchError,
    HashEmbedder,
    diff_response,
)
from .html_report import ReportEntry, render_report
from .io import atomic_write_text, load_snapshot, save_snapshot
from .schema import CanonicalResponse, Snapshot
from .stats import StatsError, collect_stats, render_summary
from .validate import validate_snapshots

# `run` walks any of these globs under the snapshots dir, deduped + sorted.
# The opinionated `*.snapshot.yaml` convention is preferred for fresh
# projects (clearly distinguishes snapshot files from other yaml in the
# repo), but the plain `.yml` / `.yaml` extensions are also accepted so
# the committed `examples/snapshots/*.yml` files and any pre-existing
# convention an operator already uses just work without renames.
_SNAPSHOT_GLOBS: tuple[str, ...] = (
    "*.snapshot.yaml",
    "*.snapshot.yml",
    "*.yml",
    "*.yaml",
)
_RESERVED_EMBEDDERS = frozenset({"voyage", "openai", "cohere"})


def make_embedder(name: str) -> Embedder:
    """Resolve an ``--embedder`` argument to an Embedder instance.

    Reserved-but-not-yet-wired names raise loudly so a misconfigured
    invocation fails at startup, not silently against a stale stub.
    """
    if name == "hash":
        return HashEmbedder()
    if name in _RESERVED_EMBEDDERS:
        raise NotImplementedError(
            f"--embedder {name!r} is reserved but not yet wired in this release. "
            "Implement the Embedder protocol locally and import via the library API."
        )
    raise ValueError(
        f"unknown --embedder value {name!r}; known: hash"
        + (", reserved: " + ", ".join(sorted(_RESERVED_EMBEDDERS)) if _RESERVED_EMBEDDERS else "")
    )


# ----------------------------------------------------------------------
# `run` — directory + candidates JSONL
# ----------------------------------------------------------------------


def _iter_snapshot_paths(snapshots_dir: Path) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for pattern in _SNAPSHOT_GLOBS:
        for p in snapshots_dir.rglob(pattern):
            if p not in seen:
                seen.add(p)
                out.append(p)
    out.sort()
    return out


def _load_candidates(path: Path) -> dict[str, str]:
    """Read a JSONL of ``{"snapshot": "<path-or-id>", "candidate": "<text>"}`` rows.

    The key is the snapshot's file path *relative to the snapshots
    directory* OR its ``snapshot.id`` — the lookup tries the relative
    path first, falls back to id. This means an operator can keep
    candidates keyed either way without re-writing the JSONL.
    """
    out: dict[str, str] = {}
    raw = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {e}") from e
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{lineno}: row is not an object: {row!r}")
        key = row.get("snapshot") or row.get("id")
        candidate = row.get("candidate")
        if not isinstance(key, str) or not isinstance(candidate, str):
            raise ValueError(
                f"{path}:{lineno}: row must have string `snapshot` (or `id`) and `candidate`"
            )
        if key in out:
            raise ValueError(f"{path}:{lineno}: duplicate candidate key {key!r}")
        out[key] = candidate
    if not out:
        raise ValueError(f"{path}: no candidate rows loaded")
    return out


def _row_for(path: Path, snap: Snapshot, result: DiffResult) -> dict:
    return {
        "snapshot_path": str(path),
        "snapshot_id": snap.id,
        "verdict": result.verdict,
        "cosine": round(result.cosine_score, 4),
        "threshold": result.threshold,
        "embedder": result.embedder_model,
        "snapshot_embedder": result.snapshot_embedding_model,
        "slot_failures": [d.name for d in result.slot_deltas if d.is_failure],
        "notes": list(result.notes),
    }


def _run_command(args: argparse.Namespace) -> int:
    snapshots_dir = Path(args.snapshots).resolve()
    if not snapshots_dir.is_dir():
        print(f"error: snapshots dir not found: {snapshots_dir}", file=sys.stderr)
        return 2
    snapshot_paths = _iter_snapshot_paths(snapshots_dir)
    if not snapshot_paths:
        patterns = ", ".join(_SNAPSHOT_GLOBS)
        print(
            f"error: no snapshot files under {snapshots_dir} (patterns considered: {patterns})",
            file=sys.stderr,
        )
        return 2

    candidates = _load_candidates(Path(args.candidates))
    embedder = make_embedder(args.embedder)

    # `--format html` writes a non-trivial multi-KB payload; refuse to
    # dump it into a terminal. Mirrors the loud-failure stance the
    # `update --force` flag takes elsewhere in this CLI.
    if args.format == "html" and not args.out:
        print(
            "error: --format html requires --out: HTML writes to a file, not stdout.",
            file=sys.stderr,
        )
        return 2

    rows: list[dict] = []
    entries: list[ReportEntry] = []  # collected for --format html
    failed = 0
    skipped = 0
    for path in snapshot_paths:
        snap = load_snapshot(path)
        rel = path.relative_to(snapshots_dir).as_posix()
        candidate = candidates.get(rel) or candidates.get(snap.id)
        if candidate is None:
            skipped += 1
            rows.append(
                {
                    "snapshot_path": str(path),
                    "snapshot_id": snap.id,
                    "verdict": "skipped",
                    "cosine": None,
                    "threshold": args.threshold,
                    "embedder": embedder.model_name,
                    "snapshot_embedder": snap.canonical.embedding_model,
                    "slot_failures": [],
                    "notes": ["no candidate supplied"],
                }
            )
            continue
        try:
            result = diff_response(
                snap,
                candidate,
                embedder=embedder,
                threshold=args.threshold,
                warn_band=args.warn_band,
                force=args.force_embedder,
            )
        except (EmbedderModelMismatchError, EmbeddingDimensionMismatchError) as e:
            # A dimension mismatch (dimension-blind D-006 guard passes, stored
            # vector length differs) must land as a per-row error like the
            # model-name mismatch, not crash the whole batch.
            failed += 1
            rows.append(
                {
                    "snapshot_path": str(path),
                    "snapshot_id": snap.id,
                    "verdict": "error",
                    "cosine": None,
                    "threshold": args.threshold,
                    "embedder": embedder.model_name,
                    "snapshot_embedder": snap.canonical.embedding_model,
                    "slot_failures": [],
                    "notes": [str(e)],
                }
            )
            continue
        rows.append(_row_for(path, snap, result))
        entries.append(
            ReportEntry(
                snapshot_id=snap.id,
                diff=result,
                candidate_text=candidate,
                baseline_text=snap.canonical.text,
            )
        )
        if result.verdict == "fail":
            failed += 1

    rendered: str
    if args.format == "json":
        rendered = json.dumps({"rows": rows, "failed": failed, "skipped": skipped}, indent=2) + "\n"
    elif args.format == "html":
        rendered = render_report(entries)
    else:
        rendered = _format_text_table(
            rows, failed=failed, skipped=skipped, total=len(snapshot_paths)
        )

    if args.out:
        atomic_write_text(args.out, rendered)
    else:
        # text/json keep their trailing newline; print() would add a second one.
        sys.stdout.write(rendered)
    return 1 if failed > 0 else 0


def _format_text_table(rows: Sequence[dict], *, failed: int, skipped: int, total: int) -> str:
    lines: list[str] = [
        f"# prompt-snap run  total={total} failed={failed} skipped={skipped}",
        f"{'verdict':8} {'cosine':>7}  snapshot",
        f"{'-' * 8} {'-' * 7}  {'-' * 24}",
    ]
    for row in rows:
        cosine = "  -.-- " if row["cosine"] is None else f"{row['cosine']:>6.3f} "
        lines.append(f"{row['verdict']:8} {cosine}  {row['snapshot_path']}")
        for note in row["notes"]:
            lines.append(f"    - {note}")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------
# `update` — re-baseline one snapshot
# ----------------------------------------------------------------------


def _update_command(args: argparse.Namespace) -> int:
    if not args.force:
        print(
            "error: refusing to update without --force "
            "(prevents accidental re-baselining of a failing snapshot)",
            file=sys.stderr,
        )
        return 2

    snapshot_path = Path(args.snapshot).resolve()
    snap = load_snapshot(snapshot_path)
    embedder = make_embedder(args.embedder)

    new_text = _read_text_arg(args.canonical, args.canonical_stdin)
    new_embedding = embedder.embed(new_text)
    new_canonical = CanonicalResponse(
        text=new_text,
        embedding=new_embedding,
        embedding_model=embedder.model_name,
    )
    updated = Snapshot(
        id=snap.id,
        prompt=snap.prompt,
        response_shape=snap.response_shape,
        canonical=new_canonical,
        schema_version=snap.schema_version,
        created_at=snap.created_at,
        notes=snap.notes,
        # Preserve the author's per-snapshot tolerance (issue #10) across a
        # re-baseline — same "don't trample author intent" rule as notes
        # below. Omitting it silently reverted a tuned threshold to the
        # per-run default and quietly changed the diff verdict (#61).
        tolerance=snap.tolerance,
    )
    # Stamp the canonical re-baseline timestamp into notes if no notes field
    # already exists; otherwise leave the user-supplied notes alone so we
    # don't trample author intent.
    if not updated.notes:
        updated.notes = f"re-baselined {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    save_snapshot(updated, snapshot_path)
    print(f"updated {snapshot_path}: embedder={embedder.model_name} text_len={len(new_text)}")
    return 0


def _read_text_arg(literal: str | None, from_stdin: bool) -> str:
    if literal is not None and from_stdin:
        raise SystemExit("error: pass --canonical OR --canonical-stdin, not both")
    text = sys.stdin.read() if from_stdin else (literal or "")
    text = text.strip()
    if not text:
        raise SystemExit("error: candidate text was empty after stripping whitespace")
    return text


# ----------------------------------------------------------------------
# `diff` — ad-hoc single snapshot
# ----------------------------------------------------------------------


def _diff_command(args: argparse.Namespace) -> int:
    # `--format html` writes a non-trivial multi-KB payload; refuse to
    # dump it into a terminal. Mirrors the loud-failure stance `run`
    # takes on the same arg (post-#29) and `update --force` elsewhere.
    if args.format == "html" and not args.out:
        print(
            "error: --format html requires --out: HTML writes to a file, not stdout.",
            file=sys.stderr,
        )
        return 2

    snap = load_snapshot(Path(args.snapshot).resolve())
    embedder = make_embedder(args.embedder)
    candidate = _read_text_arg(args.candidate, args.candidate_stdin)
    try:
        result = diff_response(
            snap,
            candidate,
            embedder=embedder,
            threshold=args.threshold,
            warn_band=args.warn_band,
            force=args.force_embedder,
        )
    except (EmbedderModelMismatchError, EmbeddingDimensionMismatchError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    rendered: str
    if args.format == "json":
        rendered = json.dumps(_serialize_diff(result), indent=2) + "\n"
    elif args.format == "html":
        rendered = render_report(
            [
                ReportEntry(
                    snapshot_id=snap.id,
                    diff=result,
                    candidate_text=candidate,
                    baseline_text=snap.canonical.text,
                )
            ]
        )
    else:
        rendered = _format_diff_text(result)

    if args.out:
        atomic_write_text(args.out, rendered)
    else:
        # text/json keep their trailing newline; sys.stdout.write avoids
        # the doubled newline `print()` would add.
        sys.stdout.write(rendered)
    return 0 if result.verdict != "fail" else 1


def _format_diff_text(result: DiffResult) -> str:
    """Render the human-readable text shape of a single `diff_response` result.

    Pre-#31 this was inlined as a sequence of `print()` calls in
    `_diff_command`. Extracted into a string-returning helper so the
    sink decision (`--out` vs. stdout) lives in one place and the text
    shape is exercisable from tests without `capsys`.
    """
    lines: list[str] = [
        f"verdict: {result.verdict}",
        f"cosine:  {result.cosine_score:.4f} (threshold {result.threshold})",
        f"embedder: {result.embedder_model}  (snapshot: {result.snapshot_embedding_model})",
    ]
    if result.slot_deltas:
        lines.append("slots:")
        for d in result.slot_deltas:
            marker = "FAIL" if d.is_failure else "ok"
            lines.append(f"  [{marker}] {d.name}: {d.status}")
    if result.notes:
        lines.append("notes:")
        for note in result.notes:
            lines.append(f"  - {note}")
    return "\n".join(lines) + "\n"


def _serialize_diff(result: DiffResult) -> dict:
    # Field-by-field contract now lives on DiffResult.to_dict (#51) so
    # downstream consumers of `prompt-snap diff --json` bind to the
    # dataclass's explicit shape, not whatever asdict happens to emit.
    return result.to_dict()


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------


def _stats_command(args: argparse.Namespace) -> int:
    """Aggregate stats over a snapshots directory.

    Exit codes mirror the ``run`` subcommand convention:
    - ``0`` on a populated directory.
    - ``2`` on a missing directory or one with no matching files.
    Schema-validation errors propagate from ``load_snapshot`` as
    ``SnapshotValidationError`` — same loud failure ``run`` would
    surface, so a single fix-and-rerun cycle resolves both surfaces.
    """
    try:
        report = collect_stats(args.snapshots)
    except StatsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_summary(report))
    return 0


def _validate_command(args: argparse.Namespace) -> int:
    """Lint a snapshots directory; exit 0 clean / 1 findings / 2 missing-dir.

    Mirrors ``eval-harness validate`` exit-code shape so CI consumers
    can chain validators uniformly. Findings print one per stderr line
    (with the file's path relative to the validated directory and the
    code); a one-line totals row goes to stdout. ``--json`` emits the
    full ``ValidationReport`` dict instead of the human-readable
    summary.
    """
    try:
        report = validate_snapshots(args.snapshots)
    except FileNotFoundError as e:
        print(f"error: snapshots directory not found: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: failed to walk snapshots directory: {e}", file=sys.stderr)
        return 2

    if args.as_json:
        rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    else:
        # Findings go to stderr regardless of --out so the operator's diagnostic
        # channel is preserved even when stdout is captured to a file. Parity
        # with llm-eval-harness validate (#66) and chunking_lab.validate (#45).
        for finding in report.findings:
            print(f"{finding.path} [{finding.code}]: {finding.reason}", file=sys.stderr)
        status = "ok" if report.ok else "fail"
        rendered = (
            f"{status}: {args.snapshots} files={report.n_files} valid={report.n_valid} "
            f"findings={len(report.findings)}\n"
        )
    if args.out:
        atomic_write_text(args.out, rendered)
    else:
        print(rendered, end="")
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prompt-snap",
        description="CLI for prompt-regression-suite: run / update / diff snapshots.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser(
        "run",
        help="Walk a snapshots dir, diff each against candidates, exit non-zero on failure.",
        description="Diff a directory of snapshots against a JSONL of candidate responses.",
    )
    run_p.add_argument(
        "--snapshots", required=True, help="Directory of *.snapshot.yaml files (recursive)."
    )
    run_p.add_argument(
        "--candidates",
        required=True,
        help='JSONL of {"snapshot": "<path-or-id>", "candidate": "<text>"} rows.',
    )
    run_p.add_argument("--embedder", default="hash", help="Embedder name (default: hash).")
    run_p.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD, help="Cosine pass threshold."
    )
    run_p.add_argument(
        "--warn-band",
        type=float,
        default=DEFAULT_WARN_BAND,
        help="Width of the warn band immediately below the threshold.",
    )
    run_p.add_argument(
        "--format",
        choices=("text", "json", "html"),
        default="text",
        help="Output format (default: text). `html` renders the same report as render_report() and requires --out.",
    )
    run_p.add_argument(
        "--out",
        default=None,
        help="Write the rendered output to this path (parent dirs created). Required for --format html.",
    )
    run_p.add_argument(
        "--force-embedder",
        action="store_true",
        help="Skip the embedder-model-vs-snapshot-model mismatch guard (D-006).",
    )

    update_p = sub.add_parser(
        "update",
        help="Re-baseline a single snapshot's canonical response. REQUIRES --force.",
    )
    update_p.add_argument("--snapshot", required=True, help="Path to a *.snapshot.yaml file.")
    update_p.add_argument(
        "--canonical",
        default=None,
        help="New canonical response text (pass --canonical-stdin to read from stdin instead).",
    )
    update_p.add_argument(
        "--canonical-stdin", action="store_true", help="Read the new canonical text from stdin."
    )
    update_p.add_argument("--embedder", default="hash", help="Embedder name (default: hash).")
    update_p.add_argument(
        "--force",
        action="store_true",
        help="Required. Without this flag, `update` refuses to write to prevent silent re-baselining.",
    )

    diff_p = sub.add_parser(
        "diff",
        help="Ad-hoc diff: compare one candidate response against one snapshot.",
    )
    diff_p.add_argument("--snapshot", required=True, help="Path to a *.snapshot.yaml file.")
    diff_p.add_argument(
        "--candidate",
        default=None,
        help="Candidate response text (or pass --candidate-stdin to read from stdin).",
    )
    diff_p.add_argument(
        "--candidate-stdin", action="store_true", help="Read the candidate text from stdin."
    )
    diff_p.add_argument("--embedder", default="hash", help="Embedder name (default: hash).")
    diff_p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    diff_p.add_argument("--warn-band", type=float, default=DEFAULT_WARN_BAND)
    diff_p.add_argument(
        "--format",
        choices=("text", "json", "html"),
        default="text",
        help=(
            "Output format (default: text). `html` renders a one-entry "
            "report via render_report() and requires --out."
        ),
    )
    diff_p.add_argument(
        "--out",
        default=None,
        help=(
            "Write the rendered output to this path (parent dirs created). "
            "Required for --format html. Parity with `run --out`."
        ),
    )
    diff_p.add_argument(
        "--force-embedder",
        action="store_true",
        help="Skip the embedder-model-vs-snapshot-model mismatch guard (D-006).",
    )

    stats_p = sub.add_parser(
        "stats",
        help="Aggregate population stats over a snapshots directory.",
        description=(
            "Walk a snapshots directory and emit per-model, per-embedder, per-tolerance, "
            "and per-slot-count summaries. Useful before a big model upgrade."
        ),
    )
    stats_p.add_argument(
        "snapshots", help="Directory of *.yml / *.yaml snapshot files (recursive)."
    )
    stats_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the report as JSON instead of the human-readable summary.",
    )

    validate_p = sub.add_parser(
        "validate",
        help="Lint a snapshots dir in collecting mode; report every malformed file in one pass.",
        description=(
            "Walk a snapshots directory and surface every malformed file (parse / "
            "schema_version / schema / duplicate_id) plus the empty-dir case in a "
            "single pass. Pre-flight before `run`. Exit codes: 0 clean / 1 findings "
            "/ 2 missing directory."
        ),
    )
    validate_p.add_argument("snapshots", help="Directory of snapshot files to lint (recursive).")
    validate_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the report as JSON instead of the human-readable summary.",
    )
    validate_p.add_argument(
        "--out",
        default=None,
        help=(
            "Write the rendered output to this path instead of stdout. Parent dirs "
            "are auto-created via prompt_regression/io.atomic_write_text. Parity with "
            "`run --out`, llm-eval-harness `validate --out` (#66), chunking-strategies-lab "
            "`validate --out` (#45). Findings still print to stderr in human-readable mode "
            "even when --out is set, so the operator's diagnostic channel is preserved."
        ),
    )

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "run":
        return _run_command(args)
    if args.command == "update":
        return _update_command(args)
    if args.command == "diff":
        return _diff_command(args)
    if args.command == "stats":
        return _stats_command(args)
    if args.command == "validate":
        return _validate_command(args)
    parser.error(f"unknown command {args.command!r}")
    return 2  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
