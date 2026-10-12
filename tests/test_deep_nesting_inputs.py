"""Deeply nested input is bad input at both read seams, not a traceback (#232).

`safe_load_yaml` (#223) converted PyYAML's `ValueError` into a `YAMLError`, but
`RecursionError` is not a `ValueError`. PyYAML recurses once per nesting level,
so a 2 KB snapshot of a thousand `[` escaped every seam at exit 1, and
`validate` lost its whole report. `_load_candidates` caught only
`JSONDecodeError`, and on 3.14, which decodes the nesting, its not-an-object
message echoed `{row!r}`, whose repr overflowed the stack.
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
import yaml

from prompt_regression import io as prs_io
from prompt_regression.cli import main

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _ROOT / "examples" / "snapshots"
_DEEP_YAML = "extra: " + "[" * 1000 + "]" * 1000 + "\n"
_DEEP_JSON = "[" * 100_000 + "]" * 100_000


def test_validate_reports_the_deep_file_and_checks_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for p in _EXAMPLES.glob("*.yml"):
        shutil.copy(p, tmp_path / p.name)
    n_valid = len(list(_EXAMPLES.glob("*.yml")))
    assert n_valid >= 2  # anti-vacuity: there are other files to keep checking
    (tmp_path / "nested.yml").write_text(_DEEP_YAML, encoding="utf-8")
    rc = main(["validate", str(tmp_path)])
    out = capsys.readouterr()
    assert rc == 1
    assert "nested.yml [parse]" in out.out + out.err
    assert f"valid={n_valid} findings=1" in out.out
    assert "Traceback" not in out.err


def test_safe_load_yaml_converts_a_recursion_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Forced, so the conversion is pinned whatever depth the host's stack allows.
    def deep(_stream: object) -> object:
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(prs_io.yaml, "safe_load", deep)
    with pytest.raises(yaml.YAMLError, match="nested too deeply"):
        prs_io.safe_load_yaml(io.StringIO("a: 1"))


@pytest.mark.parametrize(
    "line",
    [_DEEP_JSON, '{"snapshot": "s", "candidate": ' + "1" * 5000 + "}"],
    ids=["deep", "long-int"],
)
def test_run_with_bad_candidates_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], line: str
) -> None:
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text(line + "\n", encoding="utf-8")
    rc = main(["run", "--snapshots", str(_EXAMPLES), "--candidates", str(candidates)])
    err = capsys.readouterr().err
    assert rc == 2
    assert f"{candidates}:1:" in err
    assert "Traceback" not in err
