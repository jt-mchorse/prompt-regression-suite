"""A candidate or canonical text with no UTF-8 encoding is exit 2, not a traceback (#227).

The hash embedder encodes every n-gram as UTF-8, so a lone surrogate -- a JSONL
`\\ud800` escape, or a non-UTF-8 argv byte under `surrogateescape` -- raised
UnicodeEncodeError at exit 1, the code `run` and `diff` reserve for a
regression. Measured on main: `run` with such a candidate row and
`diff --candidate $'kite \\xff'` both exited 1 with the traceback.

Stdin is NOT decoded under `surrogateescape`: `sys.stdin` is strict, so a
non-UTF-8 byte on `--candidate-stdin` / `--canonical-stdin` never becomes a
surrogate -- it raised UnicodeDecodeError in the read itself, also at exit 1
(#269). Those tests feed real bytes through a `TextIOWrapper`, not a `StringIO`
that already holds a surrogate a real process cannot produce.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

from prompt_regression.cli import main

REPO = Path(__file__).resolve().parent.parent
SNAP = REPO / "examples" / "snapshots" / "creative_kite_v1.yml"
HIGH, ESCAPED = chr(0xD800), chr(0xDCFF)


def _errors(capsys: pytest.CaptureFixture[str]) -> list[str]:
    cap = capsys.readouterr()
    return [ln for ln in (cap.out + cap.err).splitlines() if ln.startswith("error")]


@pytest.mark.parametrize(
    ("field", "row"),
    [
        ("candidate", {"snapshot": "creative_kite_v1.yml", "candidate": f"kite {HIGH} drifts"}),
        ("snapshot", {"snapshot": f"creative_kite_v1{ESCAPED}.yml", "candidate": "kite drifts"}),
    ],
)
def test_run_refuses_the_row_by_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], field: str, row: dict
) -> None:
    cands = tmp_path / "cand.jsonl"
    cands.write_text(json.dumps(row) + "\n", encoding="utf-8")  # json.dumps escapes the surrogate
    assert main(["run", "--snapshots", str(SNAP.parent), "--candidates", str(cands)]) == 2
    (line,) = _errors(capsys)
    assert f"cand.jsonl:1: `{field}` contains" in line
    assert "has no UTF-8 encoding" in line


def test_diff_refuses_an_argv_candidate(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["diff", "--snapshot", str(SNAP), "--candidate", f"kite {ESCAPED}"]) == 2
    (line,) = _errors(capsys)
    assert line.startswith("error: candidate text contains")


def test_diff_refuses_a_stdin_candidate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(f"kite {HIGH} drifts"))
    assert main(["diff", "--snapshot", str(SNAP), "--candidate-stdin"]) == 2
    assert _errors(capsys)[0].startswith("error: candidate text contains")


def test_update_refuses_a_canonical_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = tmp_path / SNAP.name
    shutil.copy(SNAP, snap)
    before = snap.read_bytes()
    assert (
        main(["update", "--snapshot", str(snap), "--canonical", f"new {ESCAPED}", "--force"]) == 2
    )
    assert snap.read_bytes() == before
    assert _errors(capsys)[0].startswith("error: canonical text contains")


@pytest.mark.parametrize("text", ["kite drifts é", "风筝在漂", "kite \U0001fa81 drifts"])
def test_non_ascii_candidates_still_diff(text: str) -> None:
    assert main(["diff", "--snapshot", str(SNAP), "--candidate", text]) in (0, 1)


# ----------------------------------------------------------------------
# Real non-UTF-8 BYTES on stdin (#269). Built from codepoints, not literals.
# ----------------------------------------------------------------------

BAD_BYTES = {
    "invalid-start-ff": b"kite " + bytes([0xFF]) + b" drifts",
    "lone-continuation-80": b"kite " + bytes([0x80]) + b" drifts",
    "truncated-sequence-at-end": b"kite drifts " + bytes([0xE2, 0x82]),
}


def _byte_stdin(monkeypatch: pytest.MonkeyPatch, data: bytes) -> None:
    # The shape a real process has under a UTF-8 locale: strict decoding.
    monkeypatch.setattr(
        "sys.stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="strict")
    )


@pytest.mark.parametrize("data", BAD_BYTES.values(), ids=BAD_BYTES.keys())
def test_diff_refuses_non_utf8_stdin_bytes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], data: bytes
) -> None:
    _byte_stdin(monkeypatch, data)
    assert main(["diff", "--snapshot", str(SNAP), "--candidate-stdin"]) == 2
    (line,) = _errors(capsys)
    assert line.startswith("error: --candidate-stdin input is not valid utf-8")
    offset = next(i for i, b in enumerate(data) if b >= 0x80)
    assert f"at offset {offset}" in line


@pytest.mark.parametrize("data", BAD_BYTES.values(), ids=BAD_BYTES.keys())
def test_update_refuses_non_utf8_stdin_bytes_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    data: bytes,
) -> None:
    snap = tmp_path / SNAP.name
    shutil.copy(SNAP, snap)
    before = snap.read_bytes()
    _byte_stdin(monkeypatch, data)
    assert main(["update", "--snapshot", str(snap), "--canonical-stdin", "--force"]) == 2
    assert snap.read_bytes() == before
    (line,) = _errors(capsys)
    assert line.startswith("error: --canonical-stdin input is not valid utf-8")


def test_valid_utf8_stdin_bytes_still_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    # Control: well-formed multi-byte UTF-8 through the same strict wrapper.
    _byte_stdin(monkeypatch, ("kite drifts " + chr(0xE9) + " " + chr(0x1FA81)).encode("utf-8"))
    assert main(["diff", "--snapshot", str(SNAP), "--candidate-stdin"]) in (0, 1)
