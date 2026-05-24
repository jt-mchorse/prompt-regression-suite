"""Tests for `prompt-snap run --format html --out <path>`.

Pins the parity gap closed by issue #29: `run` previously supported
`text` and `json` formats only, even though `render_report()` was a
public surface (#3). HTML output ships through the same `render_report`
the library exposes — these tests assert the dispatch and the
loud-failure guard when `--out` is omitted.

`--out` works for every format, not just HTML; tests cover all three.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prompt_regression.cli import main
from prompt_regression.diff import HashEmbedder
from prompt_regression.io import save_snapshot
from prompt_regression.schema import (
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
)


def _make_snapshot(snapshot_id: str, canonical_text: str) -> Snapshot:
    embedder = HashEmbedder()
    return Snapshot(
        id=snapshot_id,
        prompt=Prompt(model="claude-haiku-4-5", user=f"Describe {snapshot_id}"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
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
    save_snapshot(
        _make_snapshot(
            "refund-policy",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
        ),
        d / "refund-policy.snapshot.yaml",
    )
    save_snapshot(
        _make_snapshot(
            "shipping-policy",
            "Standard shipping ships orders within three business days.",
        ),
        d / "shipping-policy.snapshot.yaml",
    )
    return d


@pytest.fixture
def candidates_passing(tmp_path: Path) -> Path:
    p = tmp_path / "cands.jsonl"
    p.write_text(
        json.dumps(
            {
                "snapshot": "refund-policy.snapshot.yaml",
                "candidate": "Our refund policy gives Pro plan customers 14 days to request a return.",
            }
        )
        + "\n"
        + json.dumps(
            {
                "id": "shipping-policy",
                "candidate": "Standard shipping ships orders within three business days.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return p


def test_run_format_html_without_out_errors_with_clear_message(
    snapshots_dir: Path, candidates_passing: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The guard mirrors the loud-failure pattern (`update --force`).
    HTML dumped to a terminal is a UX bug we'd rather refuse than commit."""
    rc = main(
        [
            "run",
            "--snapshots",
            str(snapshots_dir),
            "--candidates",
            str(candidates_passing),
            "--format",
            "html",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "--format html requires --out" in captured.err
    assert captured.out == ""


def test_run_format_html_writes_self_contained_report_to_out(
    snapshots_dir: Path, candidates_passing: Path, tmp_path: Path
) -> None:
    out_path = tmp_path / "nested" / "subdir" / "report.html"
    assert not out_path.parent.exists(), "parent dirs should not exist yet"

    rc = main(
        [
            "run",
            "--snapshots",
            str(snapshots_dir),
            "--candidates",
            str(candidates_passing),
            "--format",
            "html",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.exists(), "--out should create parent dirs and write the HTML"
    html = out_path.read_text(encoding="utf-8")
    # The renderer's contract: a self-contained HTML page. Pin the load-bearing
    # markers — page wrapper + per-entry section anchors render_report builds.
    assert html.lstrip().lower().startswith("<!doctype html"), "expected a full HTML page"
    assert "<style" in html, "expected inline styles (self-contained, no external CSS)"
    assert 'id="snapshot-refund-policy"' in html
    assert 'id="snapshot-shipping-policy"' in html


def test_run_format_html_skips_entries_with_no_candidate(
    snapshots_dir: Path, tmp_path: Path
) -> None:
    """Skipped entries (no candidate supplied) don't have a DiffResult and
    should be omitted from the HTML report — render_report can't render them
    safely without a diff. Exit code stays 0 since skips aren't failures."""
    cands = tmp_path / "cands.jsonl"
    cands.write_text(
        json.dumps(
            {
                "snapshot": "refund-policy.snapshot.yaml",
                "candidate": "Our refund policy gives Pro plan customers 14 days to request a return.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "report.html"
    rc = main(
        [
            "run",
            "--snapshots",
            str(snapshots_dir),
            "--candidates",
            str(cands),
            "--format",
            "html",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    html = out_path.read_text(encoding="utf-8")
    assert 'id="snapshot-refund-policy"' in html
    assert 'id="snapshot-shipping-policy"' not in html


def test_run_text_format_with_out_writes_to_file_and_no_stdout(
    snapshots_dir: Path,
    candidates_passing: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--out` works for text too, not just HTML."""
    out_path = tmp_path / "report.txt"
    rc = main(
        [
            "run",
            "--snapshots",
            str(snapshots_dir),
            "--candidates",
            str(candidates_passing),
            "--out",
            str(out_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "", "with --out, nothing should be written to stdout"
    text = out_path.read_text(encoding="utf-8")
    assert "failed=0" in text
    assert "refund-policy.snapshot.yaml" in text


def test_run_json_format_with_out_writes_valid_payload(
    snapshots_dir: Path,
    candidates_passing: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_path = tmp_path / "report.json"
    rc = main(
        [
            "run",
            "--snapshots",
            str(snapshots_dir),
            "--candidates",
            str(candidates_passing),
            "--format",
            "json",
            "--out",
            str(out_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["failed"] == 0
    assert len(payload["rows"]) == 2
