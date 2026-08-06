"""``prompt-snap`` CLI: run / update / diff / stats / validate for prompt
regression snapshots.

Five subcommands:

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
- ``stats`` (#47) walks a snapshots directory and emits a population-level
  summary (model/embedding/schema-version/structured-slot histograms plus
  the tolerance distribution).
- ``validate`` (#49) lints a snapshots directory in collecting mode,
  reporting every malformed snapshot in one pass.

The default embedder is the dep-free ``HashEmbedder``. The
``--embedder`` flag accepts ``hash`` today; ``voyage`` / ``openai`` /
``cohere`` are reserved names that raise a clear "not yet wired" error
so the surface is stable while operator integrations land in follow-up
issues.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .diff import (
    DEFAULT_THRESHOLD,
    DEFAULT_WARN_BAND,
    DiffResult,
    Embedder,
    EmbedderModelMismatchError,
    EmbeddingDimensionMismatchError,
    HashEmbedder,
    NonFiniteEmbeddingError,
    WarnBandThresholdError,
    diff_response,
)
from .html_report import Entry, ErrorEntry, ReportEntry, render_report
from .io import atomic_write_text, load_snapshot, save_snapshot
from .schema import CanonicalResponse, Snapshot, SnapshotValidationError
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


def _write_output(path: str, rendered: str) -> int | None:
    """Write ``rendered`` to ``path`` atomically, translating an ``OSError``
    to the CLI's ``error:`` + exit-2 contract. Returns ``2`` on failure and
    ``None`` on success so callers can ``if (rc := _write_output(...)) is not
    None: return rc``.

    Write-seam sibling of the read-seam guards (#99/#111): every ``--out`` site
    (``run`` / ``diff`` / ``validate``) called ``atomic_write_text`` bare, so an
    unwritable ``--out`` (a directory, read-only path, unwritable parent)
    escaped as a raw ``OSError`` traceback at exit 1 — breaking the documented
    ``0 / 1 / 2`` exit contract that every read seam already honors.
    """
    try:
        atomic_write_text(path, rendered)
    except OSError as e:
        print(f"error: failed to write {path}: {e}", file=sys.stderr)
        return 2
    return None


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


def _resolve_embedder(name: str) -> Embedder | None:
    """Resolve ``--embedder`` under the CLI's ``error:`` + exit-2 contract.

    ``make_embedder`` raises loudly — ``NotImplementedError`` for a
    reserved-but-unwired name, ``ValueError`` for an unknown one — which is the
    intended *library-level* fail-loud contract. But a bad ``--embedder`` on the
    command line is an operator input error, the sibling of a missing snapshot
    dir / malformed ``--candidates`` (both already land as ``error:`` + exit 2),
    so the CLI translates it here rather than let it escape ``main`` as a raw
    traceback at exit 1 (the "regressions found" code — a typo would otherwise
    read as a failing regression in CI). Returns ``None`` on failure; the caller
    returns 2.
    """
    try:
        return make_embedder(name)
    except (NotImplementedError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return None


def _validate_thresholds(threshold: float, warn_band: float) -> bool:
    """Validate ``--threshold`` / ``--warn-band`` under the ``error:`` + exit-2 contract.

    ``diff_response`` fail-loud range guards raise a *bare* ``ValueError`` for a
    ``--threshold`` outside ``(0, 1]`` or a non-finite / negative ``--warn-band``.
    The per-snapshot ``except`` tuples in ``_run_command`` / ``_diff_command``
    catch only the typed ``diff`` errors (``EmbedderModelMismatchError`` …
    ``WarnBandThresholdError``), so those bare ``ValueError``s escaped ``main`` as
    a raw traceback at exit 1 — the "regressions found" code — instead of the
    ``error:`` + exit 2 operator-input contract every other CLI input honors
    (#119, sibling of the ``--embedder`` translation in #117). A ``--threshold 5``
    typo in CI otherwise reads as a failing regression, not a config error.

    Validating the two CLI args here fully covers the reachable cases: a
    per-snapshot ``tolerance`` is already validated to ``(0, 1]`` at load
    (``schema.py``, raising the caught ``SnapshotValidationError``), so
    ``args.threshold`` is the only ingress that can push ``effective_threshold``
    out of range. ``diff_response``'s library-level raises stay loud (unchanged).
    Returns ``False`` on a bad value; the caller returns 2.
    """
    if not 0.0 < threshold <= 1.0:
        print(f"error: threshold must be in (0, 1]; got {threshold}", file=sys.stderr)
        return False
    if not math.isfinite(warn_band):
        print(f"error: warn_band must be finite; got {warn_band}", file=sys.stderr)
        return False
    if warn_band < 0:
        print(f"error: warn_band must be non-negative; got {warn_band}", file=sys.stderr)
        return False
    return True


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

    # The operator-supplied candidates file is a usage/I-O input, exactly like
    # the snapshots dir handled above: a missing file (OSError via read_text) or
    # a malformed/duplicate/empty JSONL (ValueError, already carrying path:lineno)
    # must land as a clean `error:` + exit 2, not escape `main` as a raw traceback
    # at exit 1 — the "regressions found" code. Mirrors cli.py:157-167; continues
    # the CLI exit-code contract (#85 run warn-band, #89 diff).
    try:
        candidates = _load_candidates(Path(args.candidates))
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    embedder = _resolve_embedder(args.embedder)
    if embedder is None:
        return 2
    if not _validate_thresholds(args.threshold, args.warn_band):
        return 2

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
    entries: list[Entry] = []  # collected for --format html (ReportEntry | ErrorEntry)
    failed = 0
    skipped = 0
    for path in snapshot_paths:
        rel = path.relative_to(snapshots_dir).as_posix()
        # A malformed snapshot under the run dir is an operator input error, not
        # a regression: it must land as a clean `error:` + exit 2, not escape as
        # a raw traceback at exit 1 (the "regressions found" code). `run` aborts
        # on the first bad file by design (that's what the collecting-mode
        # `validate` command is for), but the abort should be legible. Mirrors
        # the `--candidates` handling above (cli.py) and the exit-code contract
        # from #93/#95, #94/#96, #89/#90. `SnapshotValidationError` subclasses
        # `ValueError`; `yaml.YAMLError` (a raw YAML syntax error from
        # `load_snapshot`) does not — so both are named explicitly (#99).
        try:
            snap = load_snapshot(path)
        except (OSError, UnicodeDecodeError, SnapshotValidationError, yaml.YAMLError) as e:
            print(f"error: could not load snapshot {rel}: {e}", file=sys.stderr)
            print(
                f"hint: run 'prompt-snap validate {snapshots_dir}' to list every "
                "malformed snapshot in one pass.",
                file=sys.stderr,
            )
            return 2
        # `rel` takes precedence over `snap.id`, but check key membership
        # explicitly: an `or` chain treats a present empty-string candidate
        # (the model returned nothing — itself a regression) as missing and
        # silently skips it, letting the worst regression pass CI green.
        if rel in candidates:
            candidate = candidates[rel]
        elif snap.id in candidates:
            candidate = candidates[snap.id]
        else:
            candidate = None
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
        except (
            EmbedderModelMismatchError,
            EmbeddingDimensionMismatchError,
            NonFiniteEmbeddingError,
            WarnBandThresholdError,
        ) as e:
            # A dimension mismatch (dimension-blind D-006 guard passes, stored
            # vector length differs) must land as a per-row error like the
            # model-name mismatch, not crash the whole batch.
            #
            # WarnBandThresholdError joins them (#85): a low per-snapshot
            # `tolerance` lowers the effective threshold below the *default*
            # warn_band, so the #35 guard fires even though the operator never
            # set --warn-band. As a typed guard it lands as a per-row `error`
            # instead of escaping the loop and aborting every remaining snapshot.
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
            # Surface the error in the HTML artifact too — it's counted in
            # `failed` and exits non-zero, so the report must not silently omit
            # it and read as "all pass" (#71). Error rows have no DiffResult, so
            # they carry through as ErrorEntry rather than a fabricated one.
            entries.append(ErrorEntry(snapshot_id=snap.id, message=str(e)))
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
        if (rc := _write_output(args.out, rendered)) is not None:
            return rc
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
    # A malformed/missing snapshot is an operator input error: land it as a clean
    # `error:` + exit 2, not a raw traceback at exit 1. `run` got this guard in
    # #99; `update` reads through the same `load_snapshot` seam and needs it too.
    try:
        snap = load_snapshot(snapshot_path)
    except (OSError, UnicodeDecodeError, SnapshotValidationError, yaml.YAMLError) as e:
        print(f"error: could not load snapshot {args.snapshot}: {e}", file=sys.stderr)
        return 2
    embedder = _resolve_embedder(args.embedder)
    if embedder is None:
        return 2

    try:
        new_text = _read_text_arg(args.canonical, args.canonical_stdin)
    except _UsageError as e:
        print(str(e), file=sys.stderr)
        return 2
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
    # `save_snapshot` writes through `atomic_write_text`; an unwritable snapshot
    # path (read-only file/dir, unwritable parent) otherwise escaped as a raw
    # OSError traceback at exit 1. Translate to the error: + exit-2 contract,
    # the write-seam sibling of the read-seam guards (#99/#111).
    try:
        save_snapshot(updated, snapshot_path)
    except OSError as e:
        print(f"error: failed to write {snapshot_path}: {e}", file=sys.stderr)
        return 2
    print(f"updated {snapshot_path}: embedder={embedder.model_name} text_len={len(new_text)}")
    return 0


class _UsageError(Exception):
    """A CLI usage error that callers translate to a clean stderr line + exit 2.

    `_read_text_arg` previously signaled with `raise SystemExit(str)`, which
    prints the string but exits with code **1** — the "regressions found" code —
    for what is a usage error. Raising a typed error instead lets `_diff_command`
    / `_update_command` (both already return `int`) honor the `0/1/2` contract
    (#94).
    """


def _read_text_arg(literal: str | None, from_stdin: bool) -> str:
    if literal is not None and from_stdin:
        raise _UsageError("error: pass --canonical OR --canonical-stdin, not both")
    text = sys.stdin.read() if from_stdin else (literal or "")
    text = text.strip()
    if not text:
        raise _UsageError("error: candidate text was empty after stripping whitespace")
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

    # A malformed/missing snapshot is an operator input error: land it as a clean
    # `error:` + exit 2, not a raw traceback at exit 1 (the "regressions found"
    # code). `run` got this guard in #99; `diff` reads through the same
    # `load_snapshot` seam and already honors exit 2 for its other inputs below.
    try:
        snap = load_snapshot(Path(args.snapshot).resolve())
    except (OSError, UnicodeDecodeError, SnapshotValidationError, yaml.YAMLError) as e:
        print(f"error: could not load snapshot {args.snapshot}: {e}", file=sys.stderr)
        return 2
    embedder = _resolve_embedder(args.embedder)
    if embedder is None:
        return 2
    if not _validate_thresholds(args.threshold, args.warn_band):
        return 2
    try:
        candidate = _read_text_arg(args.candidate, args.candidate_stdin)
    except _UsageError as e:
        print(str(e), file=sys.stderr)
        return 2
    try:
        result = diff_response(
            snap,
            candidate,
            embedder=embedder,
            threshold=args.threshold,
            warn_band=args.warn_band,
            force=args.force_embedder,
        )
    except (
        EmbedderModelMismatchError,
        EmbeddingDimensionMismatchError,
        NonFiniteEmbeddingError,
        # The sibling `run` command catches this too (#85): a per-snapshot
        # `tolerance` below the default warn band lowers the effective threshold
        # under warn_band and fires the #35 guard even though no --warn-band was
        # set. As a typed error it must land as a clean `error:` + exit 2 here,
        # not escape as a raw traceback (exit 1) — the diff-side completion of #85.
        WarnBandThresholdError,
    ) as e:
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
        if (rc := _write_output(args.out, rendered)) is not None:
            return rc
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
    - ``2`` on a missing directory, one with no matching files, or one
      containing a malformed snapshot. ``collect_stats`` translates a
      bad snapshot (invalid YAML / schema-invalid / unreadable) into a
      ``StatsError`` naming the file + a ``validate`` hint, so it lands
      as a clean ``error:`` + exit 2 rather than a raw traceback — the
      same contract ``run`` honors since #99 (#115).
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
        # Directory-level only. A *per-file* read failure used to land here too
        # and take the whole report down at exit 2 — nothing reported about any
        # other file in the pass, under a message blaming a walk that had in fact
        # succeeded. Those are `unreadable` findings now (#133), so anything
        # still reaching this arm really is a failure to enumerate the directory.
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
        if (rc := _write_output(args.out, rendered)) is not None:
            return rc
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
