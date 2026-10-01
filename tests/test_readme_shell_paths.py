"""Every input path the README tells you to *type* must exist (#136).

Ported from llm-eval-harness#197, where the same shape was found: a
README path lock that enumerates markdown-link parens `(path.ext)` never
looks inside a code fence, and a code fence is where every path a reader
actually runs a command against lives. Here it let
`--snapshots tests/snapshots --candidates tests/candidates.jsonl` ship in
the flagship CI example against paths that have never existed.

Scoped to the repo-relative directories that hold committed *inputs*, so
the check stays quiet and a finding means something:

- Output paths (`/tmp/report.html`, the tour's snapshot copy) are
  *written* by the documented command and must not pre-exist. Where they
  are written is the second test below (#185).
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
    # #138: the `diff`/`update` half of the same fence used a bare `snapshots/`
    # root, which this lock deliberately does not match — a bare relative dir in
    # a generic tour is a plausible placeholder, and matching it would make the
    # lock noisy. Now that those lines point at a committed root they are in
    # scope, so assert the lock sees them; the behavioural half lives in
    # `test_readme_cli_tour_examples.py`, which runs the commands.
    assert "examples/snapshots/creative_kite_v1.yml" in refs
    assert "examples/snapshots/refund_window_v1.yml" in refs


def _shell_fence_outputs() -> list[str]:
    """Every `--out` value and every `cp` destination in a shell fence."""
    fence_re = re.compile(r"^```(\w*)\s*$")
    out_re = re.compile(r"--out[ =]+(\S+)")
    cp_re = re.compile(r"^\s*cp\s+(?:-\S+\s+)*\S+\s+(\S+)")

    found: list[str] = []
    lang: str | None = None
    for line in README.read_text(encoding="utf-8").splitlines():
        fence = fence_re.match(line)
        if fence:
            lang = None if lang is not None else fence.group(1)
            continue
        if lang in SHELL_LANGS:
            command = line.split("#", 1)[0]
            found.extend(out_re.findall(command))
            found.extend(cp_re.findall(command))
    return found


def test_readme_shell_outputs_are_written_outside_the_checkout() -> None:
    """A command a reader types from a fresh clone must not leave files in it (#185).

    `--out report.html` and the tour's `cp ... ./creative_kite_v1.copy.yml`
    both wrote into the checkout root, and `.gitignore` covers neither, so
    the next `git add -A` committed an HTML report and a rewritten snapshot.
    #138 moved the copy off `examples/`, which was right, but the copy stayed
    inside the checkout.
    """
    outputs = _shell_fence_outputs()
    # The html example's `--out` and the tour's `cp`. A floor, so a reworded
    # fence cannot leave this test checking nothing.
    assert len(outputs) >= 2, f"found only {outputs} — the pattern went stale"
    inside = sorted(o for o in outputs if not o.startswith("/tmp/"))
    assert not inside, (
        f"README shell examples write inside the checkout: {inside}. "
        "A reader following them gets untracked files in the repo. Write under /tmp/."
    )
