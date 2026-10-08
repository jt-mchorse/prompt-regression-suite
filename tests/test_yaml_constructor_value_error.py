"""A YAML scalar the constructor can't build is a parse failure, not a traceback (#223).

PyYAML raises a plain ``ValueError`` (not ``yaml.YAMLError``) for an impossible
date in an unquoted timestamp or an int past CPython's 4300-digit limit. Every
read seam catches ``yaml.YAMLError``, so before #223 it escaped ``validate``,
``stats``, ``diff`` and ``run`` as a raw traceback at exit 1.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from prompt_regression.io import load_snapshot
from prompt_regression.validate import validate_snapshots

_EXAMPLE = Path(__file__).resolve().parent.parent / "examples/snapshots/creative_kite_v1.yml"


def _message_of(build: Callable[[], object]) -> str:
    # The constructor's own wording varies by interpreter (3.12: "day is out of
    # range for month"; 3.14: "day 30 must be in range 1..28 ..."), so derive
    # the expected text from the same call on the running interpreter.
    try:
        build()
    except ValueError as e:
        return str(e)
    raise AssertionError("the constructor accepted the value")


_CASES = [
    pytest.param(
        "created_at: 2026-02-30T10:00:00Z",
        _message_of(lambda: datetime(2026, 2, 30, 10, 0, 0)),
        id="feb-30",
    ),
    pytest.param("created_at: 2026-13-01", _message_of(lambda: date(2026, 13, 1)), id="month-13"),
    pytest.param(
        "tolerance: " + "1" * 4301, _message_of(lambda: int("1" * 4301)), id="int-4301-digits"
    ),
]


def _mutated(line: str) -> str:
    key = line.split(":", 1)[0]
    src = _EXAMPLE.read_text(encoding="utf-8")
    out, n = re.subn(rf"^{key}: .*$", lambda _m: line, src, count=1, flags=re.M)
    assert n == 1, key
    return out


def _dir_with_bad_and_good(tmp_path: Path, line: str) -> Path:
    d = tmp_path / "snaps"
    d.mkdir()
    (d / "bad.yml").write_text(_mutated(line), encoding="utf-8")
    good = _EXAMPLE.read_text(encoding="utf-8").replace(
        "id: creative-kite-poem-v1", "id: creative-kite-poem-v1-good", 1
    )
    assert "creative-kite-poem-v1-good" in good
    (d / "good.yml").write_text(good, encoding="utf-8")
    return d


@pytest.mark.parametrize(("line", "msg"), _CASES)
def test_load_snapshot_raises_a_yaml_error(tmp_path: Path, line: str, msg: str) -> None:
    p = tmp_path / "s.yml"
    p.write_text(_mutated(line), encoding="utf-8")
    with pytest.raises(yaml.YAMLError, match=re.escape(msg)):
        load_snapshot(p)


@pytest.mark.parametrize(("line", "msg"), _CASES)
def test_validate_reports_a_parse_finding_and_keeps_collecting(
    tmp_path: Path, line: str, msg: str
) -> None:
    report = validate_snapshots(_dir_with_bad_and_good(tmp_path, line))
    assert [(f.path, f.code) for f in report.findings] == [("bad.yml", "parse")]
    assert msg in report.findings[0].reason
    assert report.n_valid == 1


@pytest.mark.parametrize(("line", "msg"), _CASES)
@pytest.mark.parametrize("command", ["stats", "diff"])
def test_cli_exits_2_with_error_not_a_traceback(
    tmp_path: Path, line: str, msg: str, command: str
) -> None:
    d = _dir_with_bad_and_good(tmp_path, line)
    args = (
        [str(d)] if command == "stats" else ["--snapshot", str(d / "bad.yml"), "--candidate", "x"]
    )
    proc = subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", command, *args],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, proc.stderr
    assert "Traceback" not in proc.stderr
    assert proc.stderr.startswith("error:")
    assert msg in proc.stderr


def test_non_utf8_still_raises_unicode_decode_error(tmp_path: Path) -> None:
    # Control: UnicodeDecodeError is also a ValueError and keeps its own route (#125).
    p = tmp_path / "s.yml"
    p.write_bytes(b"id: caf\xe9\n")
    with pytest.raises(UnicodeDecodeError):
        load_snapshot(p)


def test_a_valid_unquoted_created_at_still_loads(tmp_path: Path) -> None:
    # Control: the #209 hand-authoring path is unchanged for a real date.
    p = tmp_path / "s.yml"
    p.write_text(_mutated("created_at: 2026-02-28T10:00:00Z"), encoding="utf-8")
    assert load_snapshot(p).created_at == "2026-02-28T10:00:00Z"
