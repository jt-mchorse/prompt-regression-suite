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


def test_run_format_html_surfaces_error_verdicts_not_just_silently_drops(
    tmp_path: Path,
) -> None:
    """Issue #71: an error verdict (embedder/snapshot model mismatch) is counted
    in `failed` and exits non-zero, so the HTML artifact must show it — not read
    as "all pass" while the run actually failed. Pre-fix the error row was
    appended to `rows` (JSON/text) but never to `entries`, so the HTML omitted it
    and the summary `total` undercounted."""
    embedder = HashEmbedder()
    d = tmp_path / "snapshots"
    d.mkdir()
    # One good snapshot (model matches the run embedder).
    save_snapshot(
        _make_snapshot("good-snap", "Refund within 14 days for Pro plan customers."),
        d / "good.snapshot.yaml",
    )
    # One snapshot whose embedding_model mismatches the run embedder -> the D-006
    # guard raises EmbedderModelMismatchError, recorded as an "error" verdict row.
    bad = Snapshot(
        id="bad-snap",
        prompt=Prompt(model="claude-haiku-4-5", user="Describe bad-snap"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text="Standard shipping ships orders within three business days.",
            embedding=embedder.embed("Standard shipping ships orders within three business days."),
            embedding_model="some-other-embedder-v9",
        ),
    )
    save_snapshot(bad, d / "bad.snapshot.yaml")

    cands = tmp_path / "cands.jsonl"
    cands.write_text(
        json.dumps(
            {"id": "good-snap", "candidate": "Refund within 14 days for Pro plan customers."}
        )
        + "\n"
        + json.dumps(
            {
                "id": "bad-snap",
                "candidate": "Standard shipping ships orders within three business days.",
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
            str(d),
            "--candidates",
            str(cands),
            "--format",
            "html",
            "--out",
            str(out_path),
        ]
    )
    # The mismatch is a failure: non-zero exit, same as JSON/text.
    assert rc == 1
    html = out_path.read_text(encoding="utf-8")
    # The erroring snapshot must have its own section, not be silently dropped.
    assert 'id="snapshot-bad-snap"' in html
    assert 'id="snapshot-good-snap"' in html
    # The error message (the mismatch reason) is surfaced in the report.
    assert "some-other-embedder-v9" in html
    # The summary header counts both snapshots and shows the error stat.
    assert ">2</strong>snapshots" in html
    assert ">1</strong>error" in html


def test_run_format_html_clean_run_has_no_error_stat(
    snapshots_dir: Path, candidates_passing: Path, tmp_path: Path
) -> None:
    """Regression guard: a run with no errors keeps the original four-stat header
    (no spurious `error` stat). Scopes the #71 change to the error case only."""
    out_path = tmp_path / "report.html"
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
    html = out_path.read_text(encoding="utf-8")
    assert "strong>error</" not in html
    assert ">error</div>" not in html


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
