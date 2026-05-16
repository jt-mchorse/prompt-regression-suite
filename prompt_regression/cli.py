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
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .diff import (
    DEFAULT_THRESHOLD,
    DEFAULT_WARN_BAND,
    DiffResult,
    Embedder,
    EmbedderModelMismatchError,
    HashEmbedder,
    diff_response,
)
from .io import load_snapshot, save_snapshot
from .schema import CanonicalResponse, Snapshot

_SNAPSHOT_GLOB = "*.snapshot.yaml"
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
    return sorted(snapshots_dir.rglob(_SNAPSHOT_GLOB))


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
        print(f"error: no {_SNAPSHOT_GLOB} files under {snapshots_dir}", file=sys.stderr)
        return 2

    candidates = _load_candidates(Path(args.candidates))
    embedder = make_embedder(args.embedder)

    rows: list[dict] = []
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
        except EmbedderModelMismatchError as e:
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
        if result.verdict == "fail":
            failed += 1

    if args.format == "json":
        print(json.dumps({"rows": rows, "failed": failed, "skipped": skipped}, indent=2))
    else:
        _print_text_table(rows, failed=failed, skipped=skipped, total=len(snapshot_paths))
    return 1 if failed > 0 else 0


def _print_text_table(rows: Sequence[dict], *, failed: int, skipped: int, total: int) -> None:
    print(f"# prompt-snap run  total={total} failed={failed} skipped={skipped}")
    print(f"{'verdict':8} {'cosine':>7}  snapshot")
    print(f"{'-' * 8} {'-' * 7}  {'-' * 24}")
    for row in rows:
        cosine = "  -.-- " if row["cosine"] is None else f"{row['cosine']:>6.3f} "
        print(f"{row['verdict']:8} {cosine}  {row['snapshot_path']}")
        for note in row["notes"]:
            print(f"    - {note}")


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
    except EmbedderModelMismatchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(_serialize_diff(result), indent=2))
    else:
        print(f"verdict: {result.verdict}")
        print(f"cosine:  {result.cosine_score:.4f} (threshold {result.threshold})")
        print(f"embedder: {result.embedder_model}  (snapshot: {result.snapshot_embedding_model})")
        if result.slot_deltas:
            print("slots:")
            for d in result.slot_deltas:
                marker = "FAIL" if d.is_failure else "ok"
                print(f"  [{marker}] {d.name}: {d.status}")
        if result.notes:
            print("notes:")
            for note in result.notes:
                print(f"  - {note}")
    return 0 if result.verdict != "fail" else 1


def _serialize_diff(result: DiffResult) -> dict:
    return {
        "verdict": result.verdict,
        "cosine_score": result.cosine_score,
        "threshold": result.threshold,
        "embedder_model": result.embedder_model,
        "snapshot_embedding_model": result.snapshot_embedding_model,
        "slot_deltas": [asdict(d) for d in result.slot_deltas],
        "semantic_category_scores": [asdict(s) for s in result.semantic_category_scores],
        "notes": list(result.notes),
    }


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------


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
        "--format", choices=("text", "json"), default="text", help="Output format (default: text)."
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
        "--format", choices=("text", "json"), default="text", help="Output format (default: text)."
    )
    diff_p.add_argument(
        "--force-embedder",
        action="store_true",
        help="Skip the embedder-model-vs-snapshot-model mismatch guard (D-006).",
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
    parser.error(f"unknown command {args.command!r}")
    return 2  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
