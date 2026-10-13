"""A lone surrogate inside a snapshot is exit 2 or escaped, never a traceback (#245).

#227 refused a lone surrogate in a candidate and left the snapshot's own strings
unchecked. A double-quoted YAML scalar may carry a `"\\ud800"` escape, which
PyYAML loads as a lone surrogate. Measured on main: `validate` reported such a
file clean (exit 0), and then

- a `semantic_categories` label crashed the embedder on every `run` / `diff`,
- an id passed `run` but crashed `run --format html --out` in the write,

each as a `UnicodeEncodeError` traceback at exit 1, the "regressions found" code.

The two halves get different remedies. A label is embedder input, the population
#227's rule is about, so it is refused at load. An id or text is not embedded
at diff time and is pinned as round-tripping
(`tests/test_snapshot_version_write_path.py`), so `--out` escapes it the way
`io._print` already does on stdout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from prompt_regression.cli import main
from prompt_regression.io import load_snapshot
from prompt_regression.schema import ResponseShape, SnapshotValidationError

REPO = Path(__file__).resolve().parent.parent
KITE = REPO / "examples" / "snapshots" / "creative_kite_v1.yml"
HIGH, ESCAPED = chr(0xD800), chr(0xDCFF)


def _write(tmp_path: Path, edit: Any) -> Path:
    """Copy the kite snapshot into a fresh dir after applying *edit* to its data.

    `safe_dump` without `allow_unicode` writes a surrogate as the `\\uD800`
    escape, the only way one reaches a file decoded as strict UTF-8.
    """
    data = yaml.safe_load(KITE.read_text(encoding="utf-8"))
    edit(data)
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    out = snaps / KITE.name
    out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="ascii")
    return out


def _label(text: str) -> Any:
    def edit(data: dict) -> None:
        data["response_shape"]["semantic_categories"][1] = text

    return edit


def _candidates(tmp_path: Path) -> Path:
    text = load_snapshot(KITE).canonical.text
    cands = tmp_path / "cand.jsonl"
    cands.write_text(json.dumps({"snapshot": KITE.name, "candidate": text}) + "\n")
    return cands


def _run(path: Path, cands: Path, *extra: str) -> int:
    return main(["run", "--snapshots", str(path.parent), "--candidates", str(cands), *extra])


# --- a category label is embedder input: refused at load --------------------


@pytest.mark.parametrize("surrogate", [HIGH, ESCAPED], ids=["U+D800", "U+DCFF"])
def test_an_unencodable_label_is_a_schema_error(surrogate: str) -> None:
    with pytest.raises(SnapshotValidationError, match="has no UTF-8 encoding") as e:
        ResponseShape(semantic_categories=["ok", f"kite {surrogate} imagery"])
    assert e.value.code == "schema"
    assert "semantic_categories[1] contains" in str(e.value)


def test_validate_reports_the_label(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, _label(f"kite {HIGH} imagery"))
    assert main(["validate", str(path.parent)]) == 1
    assert "semantic_categories[1] contains" in capsys.readouterr().err


def test_run_with_an_unencodable_label_is_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, _label(f"kite {HIGH} imagery"))
    assert _run(path, _candidates(tmp_path)) == 2
    assert "semantic_categories[1] contains" in capsys.readouterr().err


def test_diff_with_an_unencodable_label_is_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, _label(f"kite {HIGH} imagery"))
    assert main(["diff", "--snapshot", str(path), "--candidate", "a kite drifts"]) == 2
    assert capsys.readouterr().err.startswith("error: could not load snapshot")


@pytest.mark.parametrize("label", ["kite é imagery", "风筝", "kite \U0001fa81 imagery"])
def test_an_escaped_label_that_encodes_still_runs(tmp_path: Path, label: str) -> None:
    """The control: the same `\\u` / `\\U` escape route, for real characters."""
    path = _write(tmp_path, _label(label))
    assert load_snapshot(path).response_shape.semantic_categories[1] == label
    assert main(["validate", str(path.parent)]) == 0
    assert _run(path, _candidates(tmp_path)) == 0


# --- an id or text is not embedded: --out escapes it, as stdout does --------


def _set_id(data: dict) -> None:
    data["id"] = f"kite{HIGH}"


def _set_text(data: dict) -> None:
    data["canonical"]["text"] = f"{data['canonical']['text']} {ESCAPED}"


@pytest.mark.parametrize("fmt", ["html", "text", "json"])
@pytest.mark.parametrize("edit", [_set_id, _set_text], ids=["id", "canonical.text"])
def test_run_out_with_an_unencodable_string_writes_the_report(
    tmp_path: Path, fmt: str, edit: Any
) -> None:
    path = _write(tmp_path, edit)
    report = tmp_path / f"report.{fmt}"
    # The report is produced whatever the verdict; a crash in the write is the bug.
    assert _run(path, _candidates(tmp_path), "--format", fmt, "--out", str(report)) in (0, 1)
    written = report.read_text(encoding="utf-8")
    assert written
    if fmt == "json":
        json.loads(written)


def test_diff_html_out_with_an_unencodable_id_escapes_it(tmp_path: Path) -> None:
    path = _write(tmp_path, _set_id)
    report = tmp_path / "d.html"
    text = load_snapshot(KITE).canonical.text
    argv = ["diff", "--snapshot", str(path), "--candidate", text]
    assert main([*argv, "--format", "html", "--out", str(report)]) == 0
    assert "kite\\ud800" in report.read_text(encoding="utf-8")


def test_encodable_non_ascii_in_a_report_is_not_escaped(tmp_path: Path) -> None:
    """The escape only runs when the text cannot be encoded."""
    path = _write(tmp_path, lambda data: data.update(id="kite-é"))
    report = tmp_path / "r.html"
    assert _run(path, _candidates(tmp_path), "--format", "html", "--out", str(report)) == 0
    written = report.read_text(encoding="utf-8")
    assert "kite-é" in written
    assert "\\xe9" not in written
