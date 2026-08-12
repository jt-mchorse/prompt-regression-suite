"""Every input path the README tells you to *type* must exist (#136).

Ported from llm-eval-harness#197, where the same shape was found: a
README path lock that enumerates markdown-link parens `(path.ext)` never
looks inside a code fence, and a code fence is where every path a reader
actually runs a command against lives. Here it let
`--snapshots tests/snapshots --candidates tests/candidates.jsonl` ship in
the flagship CI example against paths that have never existed.

Scoped to the repo-relative directories that hold committed *inputs*, so
the check stays quiet and a finding means something:

- Output paths (`report.html`, `report.json`) are *written* by the
  documented command and must not pre-exist.
- Bare `./snapshots`-style placeholders in generic tours aren't matched;
  only paths rooted at a real fixture directory are.

Nothing in the README writes into `examples/`, so within a shell fence
those paths are unambiguously inputs.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

# Directories that hold committed inputs a README command may consume.
INPUT_ROOTS = ("examples/", "fixtures/", "tests/")
SHELL_LANGS = {"bash", "sh", "shell", "console"}


def _shell_fence_paths() -> set[str]:
    """Paths under an input root appearing inside a shell code fence."""
    path_re = re.compile(
        r"(?<![\w/.-])((?:" + "|".join(r.rstrip("/") for r in INPUT_ROOTS) + r")/[A-Za-z0-9_./-]+)"
    )
    fence_re = re.compile(r"^```(\w*)\s*$")

    found: set[str] = set()
    lang: str | None = None
    for line in README.read_text(encoding="utf-8").splitlines():
        fence = fence_re.match(line)
        if fence:
            lang = None if lang is not None else fence.group(1)
            continue
        if lang in SHELL_LANGS:
            # Strip comment bodies: the README annotates commands with `#
            # → ...` lines that quote *output*, including paths the command
            # creates rather than consumes.
            command = line.split("#", 1)[0]
            found.update(path_re.findall(command))
    return found


def test_readme_shell_input_paths_exist() -> None:
    refs = _shell_fence_paths()
    assert refs, "no input paths found in any shell fence — the pattern went stale"

    missing = sorted(r for r in refs if not (REPO_ROOT / r).exists())
    assert not missing, (
        f"README shell examples reference inputs that don't exist: {missing}. "
        "A reader running them from a fresh clone gets exit 2. Commit the "
        "fixture or fix the command."
    )


def test_lock_covers_the_run_examples_that_regressed() -> None:
    """Anti-vacuous: the lock must actually be looking at the fixed lines.

    Without this, a future edit to the fence-detection could silently stop
    matching the very examples #136 was about, and the test above would
    still pass on an empty-but-nonzero set.
    """
    refs = _shell_fence_paths()
    assert "examples/snapshots" in refs
    assert "examples/candidates.jsonl" in refs
