"""Tests for `prompt-snap diff --format html` + `--out` (issue #31).

Pins the parity gap closed by issue #31: `diff` previously supported
only `text` / `json` formats with output forced to stdout, while sibling
`run` (post-#29) already supported `text` / `json` / `html` with a
generic `--out PATH` and a loud-failure stance for `--format html`
without `--out`. This module asserts:

- `--format html` without `--out` exits 2 with the same stderr message
  shape `run` uses (parity, not a new policy).
- `--format html --out PATH` writes a one-entry `render_report()` shape
  containing a snapshot anchor for the diff'd snapshot.
- `--out PATH` is silent on stdout for text and json too.
- The no-`--out` text path still prints to stdout exactly as pre-#31
  (regression guard against the inline-`print()` → string-builder
  refactor in `_format_diff_text`).
"""

from __future__ import annotations

from pathlib import Path

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


def _write_snapshot(path: Path, snap: Snapshot) -> None:
    save_snapshot(snap, path)


def test_diff_html_without_out_exits_two_with_stderr_message(tmp_path: Path, capsys) -> None:
    snap_path = tmp_path / "refund-policy.snapshot.yaml"
    _write_snapshot(
        snap_path,
        _make_snapshot(
            "refund-policy",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
        ),
    )
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snap_path),
            "--candidate",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
            "--format",
            "html",
        ]
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "--format html requires --out" in captured.err
    # No partial HTML on stdout — the guard runs before render.
    assert "<html" not in captured.out
    assert "<!doctype" not in captured.out.lower()


def test_diff_html_with_out_writes_single_entry_report(tmp_path: Path, capsys) -> None:
    snap_path = tmp_path / "refund-policy.snapshot.yaml"
    _write_snapshot(
        snap_path,
        _make_snapshot(
            "refund-policy",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
        ),
    )
    # Slightly different candidate so the diff is non-trivial but still passes
    # under the default warn-band / threshold for the hash embedder.
    out_path = tmp_path / "deep" / "nested" / "report.html"
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snap_path),
            "--candidate",
            "Our refund policy lets Pro plan customers request a return within 14 days.",
            "--format",
            "html",
            "--out",
            str(out_path),
        ]
    )
    # rc is the verdict's normal exit code (0 unless verdict == fail);
    # asserting it's not the loud-failure 2 is the contract this test pins.
    assert rc != 2
    # Stdout is silent under --out.
    assert capsys.readouterr().out == ""
    # File exists at the nested path (mkdir -p) and looks like the
    # render_report() shape — doctype + snapshot id anchor / heading.
    assert out_path.exists()
    body = out_path.read_text(encoding="utf-8")
    assert body.lower().startswith("<!doctype html>") or "<!DOCTYPE html>" in body
    assert "refund-policy" in body


def test_diff_text_out_keeps_stdout_silent_and_writes_file(tmp_path: Path, capsys) -> None:
    snap_path = tmp_path / "refund-policy.snapshot.yaml"
    _write_snapshot(
        snap_path,
        _make_snapshot(
            "refund-policy",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
        ),
    )
    out_path = tmp_path / "diff.txt"
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snap_path),
            "--candidate",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
            "--out",
            str(out_path),
        ]
    )
    assert rc != 2
    # Stdout silent under --out.
    assert capsys.readouterr().out == ""
    body = out_path.read_text(encoding="utf-8")
    # The pre-#31 text shape: 'verdict: ...', 'cosine: ...', 'embedder: ...'.
    assert "verdict:" in body
    assert "cosine:" in body
    assert "embedder:" in body


def test_diff_json_out_writes_parseable_json_to_file(tmp_path: Path, capsys) -> None:
    import json as _json

    snap_path = tmp_path / "refund-policy.snapshot.yaml"
    _write_snapshot(
        snap_path,
        _make_snapshot(
            "refund-policy",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
        ),
    )
    out_path = tmp_path / "diff.json"
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snap_path),
            "--candidate",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
            "--format",
            "json",
            "--out",
            str(out_path),
        ]
    )
    assert rc != 2
    assert capsys.readouterr().out == ""
    parsed = _json.loads(out_path.read_text(encoding="utf-8"))
    # The _serialize_diff() shape is stable; assert the verdict key is present
    # and the cosine_score is a number — the wire contract for JSON consumers.
    assert "verdict" in parsed
    assert isinstance(parsed.get("cosine_score"), (int, float))


def test_diff_no_out_still_prints_text_to_stdout(tmp_path: Path, capsys) -> None:
    """Regression guard: refactoring `_diff_command` from inline `print()`
    calls to a string-builder + sink dispatch must not change the
    no-`--out` stdout shape.
    """
    snap_path = tmp_path / "refund-policy.snapshot.yaml"
    _write_snapshot(
        snap_path,
        _make_snapshot(
            "refund-policy",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
        ),
    )
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snap_path),
            "--candidate",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
        ]
    )
    assert rc != 2
    out = capsys.readouterr().out
    assert "verdict:" in out
    assert "cosine:" in out
    assert "embedder:" in out
