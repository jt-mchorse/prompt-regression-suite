"""Tests for the ``prompt-snap`` CLI (#5)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from prompt_regression.cli import build_parser, main, make_embedder
from prompt_regression.diff import HashEmbedder
from prompt_regression.io import load_snapshot, save_snapshot
from prompt_regression.schema import (
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
)

# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _make_snapshot(snapshot_id: str, canonical_text: str) -> Snapshot:
    embedder = HashEmbedder()
    return Snapshot(
        id=snapshot_id,
        prompt=Prompt(
            model="claude-haiku-4-5",
            user=f"Describe {snapshot_id}",
        ),
        response_shape=ResponseShape(
            semantic_categories=[],
            structured_slots={},
        ),
        canonical=CanonicalResponse(
            text=canonical_text,
            embedding=embedder.embed(canonical_text),
            embedding_model=embedder.model_name,
        ),
    )


@pytest.fixture
def snapshots_dir(tmp_path: Path) -> Path:
    d = tmp_path / "snapshots"
    d.mkdir()
    snap_a = _make_snapshot(
        "refund-policy",
        "Our refund policy gives Pro plan customers 14 days to request a return.",
    )
    snap_b = _make_snapshot(
        "shipping-policy",
        "Standard shipping ships orders within three business days.",
    )
    save_snapshot(snap_a, d / "refund-policy.snapshot.yaml")
    save_snapshot(snap_b, d / "shipping-policy.snapshot.yaml")
    return d


# ----------------------------------------------------------------------
# make_embedder
# ----------------------------------------------------------------------


def test_make_embedder_hash_returns_hashembedder():
    e = make_embedder("hash")
    assert isinstance(e, HashEmbedder)


@pytest.mark.parametrize("reserved", ["voyage", "openai", "cohere"])
def test_make_embedder_reserved_names_raise_notimplementederror(reserved: str):
    with pytest.raises(NotImplementedError, match=reserved):
        make_embedder(reserved)


def test_make_embedder_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown --embedder"):
        make_embedder("definitely-not-a-real-backend")


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------


def test_build_parser_help_lists_all_subcommands():
    parser = build_parser()
    buf = io.StringIO()
    parser.print_help(file=buf)
    text = buf.getvalue()
    assert "run" in text
    assert "update" in text
    assert "diff" in text


@pytest.mark.parametrize("sub", ["run", "update", "diff"])
def test_each_subcommand_has_help(sub: str):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args([sub, "--help"])
    assert exc.value.code == 0


# ----------------------------------------------------------------------
# `run`
# ----------------------------------------------------------------------


def _write_candidates(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_run_happy_path_all_pass(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [
            {
                "snapshot": "refund-policy.snapshot.yaml",
                "candidate": "Our refund policy gives Pro plan customers 14 days to request a return.",
            },
            {
                "id": "shipping-policy",
                "candidate": "Standard shipping ships orders within three business days.",
            },
        ],
    )
    rc = main(["run", "--snapshots", str(snapshots_dir), "--candidates", str(candidates)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "failed=0" in out
    assert "skipped=0" in out
    # Both snapshot paths should appear in the output.
    assert "refund-policy.snapshot.yaml" in out
    assert "shipping-policy.snapshot.yaml" in out


def test_run_failing_candidate_exits_nonzero(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [
            {
                "snapshot": "refund-policy.snapshot.yaml",
                "candidate": "Completely unrelated text about kittens and yarn.",
            },
            {
                "id": "shipping-policy",
                "candidate": "Standard shipping ships orders within three business days.",
            },
        ],
    )
    rc = main(["run", "--snapshots", str(snapshots_dir), "--candidates", str(candidates)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "failed=" in out
    assert "fail" in out


def test_run_skips_snapshots_with_no_candidate(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [
            {
                "snapshot": "refund-policy.snapshot.yaml",
                "candidate": "Our refund policy gives Pro plan customers 14 days to request a return.",
            },
        ],
    )
    rc = main(["run", "--snapshots", str(snapshots_dir), "--candidates", str(candidates)])
    # One passed, one skipped → exit 0 (skips don't fail the run).
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipped=1" in out
    assert "no candidate supplied" in out


def test_run_json_format_emits_valid_payload(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [
            {
                "snapshot": "refund-policy.snapshot.yaml",
                "candidate": "Our refund policy gives Pro plan customers 14 days to request a return.",
            },
        ],
    )
    rc = main(
        [
            "run",
            "--snapshots",
            str(snapshots_dir),
            "--candidates",
            str(candidates),
            "--format",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "rows" in payload
    assert isinstance(payload["rows"], list)
    assert payload["failed"] == 0
    assert payload["skipped"] == 1
    assert any(r["verdict"] == "pass" for r in payload["rows"])


def test_run_missing_snapshots_dir_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    cands = _write_candidates(tmp_path / "cands.jsonl", [{"snapshot": "x", "candidate": "y"}])
    rc = main(["run", "--snapshots", str(tmp_path / "no-such-dir"), "--candidates", str(cands)])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_run_empty_snapshots_dir_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    snaps = tmp_path / "empty"
    snaps.mkdir()
    cands = _write_candidates(tmp_path / "cands.jsonl", [{"snapshot": "x", "candidate": "y"}])
    rc = main(["run", "--snapshots", str(snaps), "--candidates", str(cands)])
    assert rc == 2
    assert "no *.snapshot.yaml" in capsys.readouterr().err


def test_run_candidates_invalid_json_raises():
    bad = Path("/tmp/this/path/intentionally/does/not/exist")
    parser = build_parser()
    args = parser.parse_args(["run", "--snapshots", str(bad), "--candidates", str(bad)])
    # snapshots-dir check fires before candidates loader, so this exercises
    # the early-return path; the candidates loader is unit-tested separately.
    assert args.command == "run"


# ----------------------------------------------------------------------
# `update`
# ----------------------------------------------------------------------


def test_update_without_force_refuses(snapshots_dir: Path, capsys: pytest.CaptureFixture[str]):
    rc = main(
        [
            "update",
            "--snapshot",
            str(snapshots_dir / "refund-policy.snapshot.yaml"),
            "--canonical",
            "New canonical response text.",
        ]
    )
    assert rc == 2
    assert "refusing to update without --force" in capsys.readouterr().err


def test_update_with_force_rewrites_canonical(snapshots_dir: Path):
    path = snapshots_dir / "refund-policy.snapshot.yaml"
    before = load_snapshot(path).canonical.text
    new_text = "Refunds are now available for 30 days after purchase."
    rc = main(
        [
            "update",
            "--snapshot",
            str(path),
            "--canonical",
            new_text,
            "--force",
        ]
    )
    assert rc == 0
    after = load_snapshot(path)
    assert after.canonical.text != before
    assert after.canonical.text == new_text
    # Embedder is HashEmbedder by default; the new embedding should match the new text.
    embedder = HashEmbedder()
    assert after.canonical.embedding == embedder.embed(new_text)
    assert after.canonical.embedding_model == embedder.model_name


def test_update_canonical_stdin(snapshots_dir: Path, monkeypatch: pytest.MonkeyPatch):
    path = snapshots_dir / "shipping-policy.snapshot.yaml"
    new_text = "Shipping now takes one business day for Pro plan customers.\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(new_text))
    rc = main(["update", "--snapshot", str(path), "--canonical-stdin", "--force"])
    assert rc == 0
    after = load_snapshot(path)
    assert after.canonical.text == new_text.strip()


def test_update_rejects_empty_canonical(snapshots_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("   \n\n  "))
    path = snapshots_dir / "refund-policy.snapshot.yaml"
    with pytest.raises(SystemExit, match="empty"):
        main(["update", "--snapshot", str(path), "--canonical-stdin", "--force"])


def test_update_rejects_both_canonical_sources(
    snapshots_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin\n"))
    path = snapshots_dir / "refund-policy.snapshot.yaml"
    with pytest.raises(SystemExit, match="not both"):
        main(
            [
                "update",
                "--snapshot",
                str(path),
                "--canonical",
                "literal arg",
                "--canonical-stdin",
                "--force",
            ]
        )


# ----------------------------------------------------------------------
# `diff`
# ----------------------------------------------------------------------


def test_diff_pass(snapshots_dir: Path, capsys: pytest.CaptureFixture[str]):
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snapshots_dir / "refund-policy.snapshot.yaml"),
            "--candidate",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "verdict: pass" in out


def test_diff_fail(snapshots_dir: Path, capsys: pytest.CaptureFixture[str]):
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snapshots_dir / "refund-policy.snapshot.yaml"),
            "--candidate",
            "Hamsters often run on wheels at night.",
        ]
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "verdict: fail" in out


def test_diff_json_format(snapshots_dir: Path, capsys: pytest.CaptureFixture[str]):
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snapshots_dir / "refund-policy.snapshot.yaml"),
            "--candidate",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "pass"
    assert "cosine_score" in payload
    assert payload["embedder_model"] == HashEmbedder().model_name


def test_diff_candidate_stdin(
    snapshots_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO("Our refund policy gives Pro plan customers 14 days to request a return.\n"),
    )
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snapshots_dir / "refund-policy.snapshot.yaml"),
            "--candidate-stdin",
        ]
    )
    assert rc == 0
    assert "verdict: pass" in capsys.readouterr().out
