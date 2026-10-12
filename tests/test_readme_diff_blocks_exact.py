"""Each `diff` example in the README's CLI tour prints exactly what the tool prints (#229).

The tour says every verdict and number in it is the tool's actual output, and
lists the only three things that are not literal (#173). The failing example
showed three of the five lines `diff` prints -- no `embedder:` line, no
tolerance note, and its warn-floor note cut short -- and its lock checked
substrings, one of which was a prefix of the real note. Here the comment lines
under each command must equal the command's stdout, line for line.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"


def _tour() -> str:
    text = README.read_text(encoding="utf-8")
    anchor = text.index("# Walk a snapshot dir, diff each against candidates in a JSONL")
    return text[text.rindex("```", 0, anchor) : text.index("```", anchor)]


def _diff_examples() -> list[tuple[list[str], list[str]]]:
    """`(argv, documented stdout lines)` for each exit-0/1 `prompt-snap diff` in the tour."""
    lines = _tour().splitlines()
    out = []
    for i, line in enumerate(lines):
        if not line.startswith("prompt-snap diff"):
            continue
        command = []
        j = i
        while True:
            command.append(lines[j].rstrip("\\").strip())
            if not lines[j].endswith("\\"):
                break
            j += 1
        documented = []
        for doc in lines[j + 1 :]:
            if not doc.startswith("#") or doc.startswith("# error:"):
                break
            documented.append(doc[2:] if doc.startswith("# ") else doc[1:])
        if documented and not documented[0].startswith("error"):
            argv = re.findall(r'"([^"]*)"|(\S+)', " ".join(command))
            out.append(([a or b for a, b in argv][1:], documented))
    return out


EXAMPLES = _diff_examples()


def test_the_tour_has_the_pass_and_fail_examples() -> None:
    verdicts = [doc[0] for _argv, doc in EXAMPLES]
    assert verdicts == ["verdict: pass", "verdict: fail"]


@pytest.mark.parametrize(("argv", "documented"), EXAMPLES, ids=["pass", "fail"])
def test_the_documented_lines_are_the_real_output(argv: list[str], documented: list[str]) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", *argv],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode in (0, 1), proc.stderr
    assert proc.stdout.splitlines() == documented
