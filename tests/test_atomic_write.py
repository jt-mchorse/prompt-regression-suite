"""Atomicity contract for snapshot saves, CLI `--out`, and demo HTML writes (#39).

`Path.write_text` and `p.open("w") + yaml.safe_dump(stream=f)` are both
non-atomic — SIGINT/SIGTERM/disk-full/OOM between the implicit
truncate and the close flush leaves the destination zero-length or
partial. For this repo the load-bearing case is `save_snapshot`:
corrupting a snapshot YAML breaks the round-trip-identity contract
(`io.py:1`) the diff layer relies on.

The fix routes four writes through `prompt_regression.io.atomic_write_text`:
- `save_snapshot` (io.py) — load-bearing.
- `prompt-snap run --out` (cli.py).
- `prompt-snap diff --out` (cli.py).
- `scripts/render_regression_demo.py` — `docs/regression_demo.html`.

Helper shape mirrors `llm-eval-harness/eval_harness/cli.py::_atomic_write_text`
(#48 there) and `llm-cost-optimizer/scripts/_io.py::atomic_write_text`
(#42 there) — portfolio-wide uniformity is intentional.
"""

from __future__ import annotations

import sys
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
from prompt_regression.cli import main as cli_main
from prompt_regression.io import atomic_write_text

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Unit tests on the helper itself.
# ---------------------------------------------------------------------------


def test_atomic_write_text_happy_path(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    atomic_write_text(out, "hello\nworld\n")
    assert out.read_text(encoding="utf-8") == "hello\nworld\n"


def test_atomic_write_text_creates_parent_dirs(tmp_path: Path) -> None:
    out = tmp_path / "deep" / "nested" / "x.yaml"
    assert not out.parent.exists()
    atomic_write_text(out, "k: v\n")
    assert out.read_text(encoding="utf-8") == "k: v\n"


def test_atomic_write_text_overwrites_existing_file(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    out.write_text("STALE-CONTENT-MUST-NOT-SURVIVE", encoding="utf-8")
    atomic_write_text(out, "fresh")
    assert out.read_text(encoding="utf-8") == "fresh"


def test_atomic_write_text_replace_failure_leaves_destination_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Load-bearing atomicity invariant. The helper must never touch
    the destination directly — only via `os.replace`. If the rename
    raises, the destination must not exist."""
    out = tmp_path / "result.json"

    def boom(*_args, **_kwargs):
        raise OSError("simulated mid-rename failure")

    monkeypatch.setattr(io_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated mid-rename failure"):
        atomic_write_text(out, '{"k": "v"}')
    assert not out.exists()


def test_atomic_write_text_replace_failure_cleans_up_tmp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No leftover `.tmp` siblings after a failed atomic write."""
    out = tmp_path / "artifacts" / "snap.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)

    def boom(*_args, **_kwargs):
        raise OSError("simulated mid-rename failure")

    monkeypatch.setattr(io_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated mid-rename failure"):
        atomic_write_text(out, "k: v\n")
    siblings = list(out.parent.iterdir())
    assert siblings == [], f"expected no temp leftovers in {out.parent}, got {siblings}"


def test_atomic_write_text_destination_unchanged_when_overwriting_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property `Path.write_text` could never offer: a failed
    `os.replace` during overwrite leaves the pre-existing destination
    contents intact. For this repo the load-bearing case is a snapshot
    YAML that's already on disk — losing it is the worst outcome.
    """
    out = tmp_path / "existing.yaml"
    out.write_text("keep: true\n", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("simulated")

    monkeypatch.setattr(io_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        atomic_write_text(out, "overwrite: true\n")
    assert out.read_text(encoding="utf-8") == "keep: true\n"


# ---------------------------------------------------------------------------
# Integration tests.
# ---------------------------------------------------------------------------


def _sample_snapshot(
    canonical_text: str = "The Pro plan has a 14-day refund window from purchase.",
) -> Snapshot:
    # Use the hash embedder's reported model name so the CLI's default
    # `diff` path doesn't error out on embedder mismatch — the goal of
    # these tests is the `--out` write atomicity, not the embedding
    # contract.
    from prompt_regression.diff import HashEmbedder

    embedder = HashEmbedder()
    return Snapshot(
        id="refund-window-pro-v1",
        prompt=Prompt(
            model="claude-haiku-4-5-20251001",
            user="What's the refund window for the Pro plan?",
            system="You are a polite support agent.",
            temperature=0.0,
            max_tokens=256,
        ),
        response_shape=ResponseShape(
            semantic_categories=["refund-window", "plan-tier"],
            structured_slots={
                "refund_days": {"type": "integer"},
                "plan_name": {"type": "string"},
            },
        ),
        canonical=CanonicalResponse(
            text=canonical_text,
            embedding=list(embedder.embed(canonical_text)),
            embedding_model=embedder.model_name,
        ),
    )


def test_save_snapshot_routes_through_atomic_helper_no_destination_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`save_snapshot` writes through `atomic_write_text`. A
    monkeypatched `os.replace` failure must leave the destination
    absent — proving the routing.
    """
    out = tmp_path / "snap.yml"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(io_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated rename failure"):
        save_snapshot(_sample_snapshot(), out)
    assert not out.exists()


def test_save_snapshot_overwrite_failure_preserves_existing_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The most consequential invariant for this repo: a `save_snapshot`
    that fails mid-rename must leave the pre-existing snapshot YAML
    fully intact. Operators rely on `prompt-snap update --force` being
    safe to re-run; corrupting the snapshot on a failure would violate
    that contract.
    """
    out = tmp_path / "snap.yml"
    original = _sample_snapshot()
    save_snapshot(original, out)
    original_bytes = out.read_bytes()
    assert load_snapshot(out) == original  # sanity precondition

    # Now mutate the snapshot, simulate save failure, prove disk is unchanged.
    mutated = Snapshot(
        id=original.id,
        prompt=original.prompt,
        response_shape=original.response_shape,
        canonical=CanonicalResponse(
            text="MUTATED TEXT MUST NOT END UP ON DISK",
            embedding=original.canonical.embedding,
            embedding_model=original.canonical.embedding_model,
        ),
    )

    def boom(*_args, **_kwargs):
        raise OSError("simulated mid-rename failure")

    monkeypatch.setattr(io_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated mid-rename failure"):
        save_snapshot(mutated, out)

    # Disk contents are bitwise identical to the pre-failure save.
    assert out.read_bytes() == original_bytes
    # And the snapshot still round-trips to the original — not the mutated copy.
    assert load_snapshot(out) == original


def test_cli_run_out_routes_through_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`prompt-snap run --out` writes through the helper. With
    `os.replace` raising, the destination must not exist.
    """
    snap_path = tmp_path / "refund.snapshot.yaml"
    save_snapshot(_sample_snapshot(), snap_path)

    # One candidate row keyed by snapshot path so `run` has something
    # to score; the --out write happens after diffing, which is the
    # routing we want to exercise.
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text(
        '{"snapshot": "'
        + str(snap_path)
        + '", "candidate": "The Pro plan has a 14-day refund window from purchase."}\n',
        encoding="utf-8",
    )

    out_path = tmp_path / "out" / "report.json"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(io_mod.os, "replace", boom)
    rc = cli_main(
        [
            "run",
            "--snapshots",
            str(tmp_path),
            "--candidates",
            str(candidates),
            "--format",
            "json",
            "--out",
            str(out_path),
        ]
    )
    # Write-seam sibling of #99/#111: an unwritable --out is an I/O error → clean
    # exit 2, not a raw OSError traceback at exit 1. Atomicity invariant holds.
    assert rc == 2
    assert not out_path.exists()


def test_cli_diff_out_routes_through_atomic_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`prompt-snap diff --out` writes through the helper. With
    `os.replace` raising, the destination must not exist.
    """
    snap_path = tmp_path / "refund.snapshot.yaml"
    save_snapshot(_sample_snapshot(), snap_path)

    out_path = tmp_path / "out" / "diff.json"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(io_mod.os, "replace", boom)
    rc = cli_main(
        [
            "diff",
            "--snapshot",
            str(snap_path),
            "--candidate",
            "The Pro plan has a 14-day refund window from purchase.",
            "--format",
            "json",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 2
    assert not out_path.exists()


def test_cli_validate_out_write_failure_exits_2_not_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`prompt-snap validate --out` translates a write OSError to the CLI's
    `error:` + exit-2 contract, not a raw traceback at exit 1 (write-seam
    sibling of the #99/#111 read-seam guards)."""
    snap_dir = tmp_path / "snaps"
    snap_dir.mkdir()
    save_snapshot(_sample_snapshot(), snap_dir / "refund.snapshot.yaml")
    out_path = tmp_path / "out" / "report.json"

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(io_mod.os, "replace", boom)
    rc = cli_main(["validate", str(snap_dir), "--json", "--out", str(out_path)])

    assert rc == 2
    err = capsys.readouterr().err
    assert "error: failed to write" in err
    assert "Traceback" not in err
    assert not out_path.exists()


def test_cli_update_write_failure_exits_2_not_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`prompt-snap update` translates a save_snapshot OSError to the CLI's
    `error:` + exit-2 contract, not a raw traceback at exit 1. The pre-existing
    snapshot is preserved by atomic_write_text on a failed rename."""
    snap_path = tmp_path / "refund.snapshot.yaml"
    save_snapshot(_sample_snapshot(), snap_path)
    original = snap_path.read_text(encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(io_mod.os, "replace", boom)
    rc = cli_main(
        [
            "update",
            "--snapshot",
            str(snap_path),
            "--canonical",
            "A brand-new canonical response for the refund window.",
            "--force",
        ]
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "error: failed to write" in err
    assert "Traceback" not in err
    assert snap_path.read_text(encoding="utf-8") == original  # unchanged on failure
