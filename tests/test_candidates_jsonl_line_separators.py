"""The candidates JSONL is split on `\\n` only (#241).

`_load_candidates` used `str.splitlines()`, which also breaks on U+0085,
U+2028 and U+2029. JSON allows all three raw inside a string and
`json.dumps(ensure_ascii=False)` writes them raw, so a valid row was cut
mid-string and `run` refused it at exit 2 as "invalid JSON". Built from
codepoints, not literals.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from prompt_regression.cli import _load_candidates, main

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"
SEPARATORS = [chr(0x85), chr(0x2028), chr(0x2029)]


def _rows() -> list[dict]:
    text = (EXAMPLES / "candidates.jsonl").read_text(encoding="utf-8")
    return [json.loads(ln) for ln in text.split("\n") if ln.strip()]


def _write(path: Path, rows: list[dict], newline: str = "\n") -> Path:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + newline for r in rows), encoding="utf-8"
    )
    return path


@pytest.mark.parametrize("sep", SEPARATORS, ids=["U+0085", "U+2028", "U+2029"])
def test_a_separator_inside_a_candidate_is_kept(tmp_path: Path, sep: str) -> None:
    rows = _rows()
    rows[0]["candidate"] = rows[0]["candidate"].replace(". The", "." + sep + "The", 1)
    assert sep in rows[0]["candidate"]  # anti-vacuity: the edit landed
    loaded = _load_candidates(_write(tmp_path / "c.jsonl", rows))
    assert loaded[rows[0]["snapshot"]] == rows[0]["candidate"]
    assert len(loaded) == len(rows)


@pytest.mark.parametrize("sep", SEPARATORS, ids=["U+0085", "U+2028", "U+2029"])
def test_run_diffs_the_row_instead_of_exiting_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], sep: str
) -> None:
    # The kite snapshot alone: the shipped refund one errors on its embedder by
    # design, which would hold the exit at 1 whatever the reader did.
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    shutil.copy(EXAMPLES / "snapshots" / "creative_kite_v1.yml", snaps)
    row = _rows()[0]
    assert row["snapshot"] == "creative_kite_v1.yml"
    row["candidate"] = row["candidate"].replace(". The", "." + sep + "The", 1)
    path = _write(tmp_path / "c.jsonl", [row])
    rc = main(["run", "--snapshots", str(snaps), "--candidates", str(path)])
    cap = capsys.readouterr()
    assert "invalid JSON" not in cap.err
    assert "total=1 failed=0" in cap.out
    assert rc == 0


def test_a_later_bad_row_keeps_its_line_number(tmp_path: Path) -> None:
    rows = _rows()
    rows[0]["candidate"] = "kite" + chr(0x2028) + "drifts"
    path = tmp_path / "c.jsonl"
    path.write_text(json.dumps(rows[0], ensure_ascii=False) + "\n" + "not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"c\.jsonl:2: invalid JSON"):
        _load_candidates(path)


def test_crlf_rows_still_load(tmp_path: Path) -> None:
    rows = _rows()
    loaded = _load_candidates(_write(tmp_path / "c.jsonl", rows, newline="\r\n"))
    assert loaded == {(r.get("snapshot") or r["id"]): r["candidate"] for r in rows}
