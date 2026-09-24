"""The README's elision list is derived from real output, not trusted (#173).

Under the CLI-tour fence the README used to say:

    The one elision is ``update``'s ``<abs-path>`` prefix

and there were three. The second one was already known *inside the repo*:
``tests/test_readme_run_tables.py`` normalises the `run` table's snapshot paths
to their basename, with a comment saying "the CLI resolves ``--snapshots`` to an
absolute path; the README shows the repo-relative one". A lock compensating for
an elision the prose three sections down denies exists is the shape this module
is here to stop.

The paragraph's whole job is to say *where the block departs from literal
output*. A completeness claim that is wrong is worse than no claim, because a
reader who runs the command and sees different text has been told there is
exactly one difference and what it is.

So this module does not check the paragraph against a list of three strings —
that is the same defect one layer up. It **computes** the elisions by diffing
the tool's real output against the block, and then asserts the paragraph
accounts for what it found. If `run` ever starts printing relative paths, or
stops emitting the per-row notes, the derived set shrinks and the prose arm goes
red for being over-stated.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
README = _REPO_ROOT / "README.md"

#: Same header signature `test_readme_run_tables.py` discovers blocks by. One
#: spelling of "this is a run block" in the repo, not two.
_HEADER = re.compile(r"#\s*prompt-snap run\s+(?:\w+=\S+\s*)+")

#: A table row in either artifact: verdict, cosine (or the `-.--` placeholder),
#: path.
_ROW = re.compile(
    r"^#?\s*(?P<verdict>pass|warn|fail|error)\s+(?P<cosine>-\.--|[0-9.]+)\s+(?P<path>\S+)\s*$"
)

#: A per-row detail line, in the tool's output (`    - …`) or a README fence
#: (`#   - …`).
_NOTE = re.compile(r"^#?\s+-\s+\S")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def live_run() -> str:
    """The documented command's real stdout."""
    proc = _run_cli(
        "run", "--snapshots", "examples/snapshots", "--candidates", "examples/candidates.jsonl"
    )
    assert proc.returncode == 1, (
        f"expected the documented exit 1, got {proc.returncode}\n{proc.stdout}{proc.stderr}"
    )
    return proc.stdout


@pytest.fixture(scope="module")
def tour_block() -> str:
    """The CLI-tour fence, which is the block the elision paragraph is about.

    Located by the `run` header inside it *and* by the tour's own anchor, so it
    cannot silently resolve to the feature-narrative block, which the paragraph
    does not describe.
    """
    text = README.read_text(encoding="utf-8")
    anchor = text.index("# Walk a snapshot dir, diff each against candidates in a JSONL")
    start = text.rindex("```", 0, anchor)
    end = text.index("```", anchor)
    block = text[start:end]
    assert _HEADER.search(block), "the CLI-tour fence no longer contains a `run` output table"
    return block


def _rows(text: str) -> list[tuple[str, str, str]]:
    out = []
    for line in text.splitlines():
        match = _ROW.match(line.strip())
        if match:
            out.append((match.group("verdict"), match.group("cosine"), match.group("path")))
    return out


def _notes(text: str) -> list[str]:
    return [line.strip().lstrip("#").strip() for line in text.splitlines() if _NOTE.match(line)]


def _run_section(block: str) -> str:
    """The `run` demonstration only — from the fence start to the next command.

    The tour fence also contains `diff` and `update`, and `diff` prints its notes
    under a `notes:` heading. Slicing to the `run` portion is what makes "the
    block omits the per-row notes" a statement about the run table rather than
    about the whole fence.
    """
    end = block.index("# Ad-hoc diff")
    return block[:end]


# ----------------------------------------------------------------------
# Anti-vacuity: the two comparisons below are only meaningful if the tool
# actually produces the things being compared.
# ----------------------------------------------------------------------


def test_the_tool_emits_rows_and_notes_to_elide(live_run: str) -> None:
    """Without this, every assertion below is over an empty difference.

    Both derived elisions are "the tool produced X and the README did not". A
    tool that produced neither absolute paths nor notes would satisfy the prose
    arm trivially while the paragraph described things that no longer happen.
    """
    rows = _rows(live_run)
    assert len(rows) == 2, f"expected the two documented rows, got {rows}"
    assert all(Path(p).is_absolute() for _, _, p in rows), (
        f"`run` no longer prints absolute snapshot paths: {[p for _, _, p in rows]}. "
        "Elision 2 in the README paragraph is now stale and must be removed."
    )
    assert len(_notes(live_run)) == 2, (
        f"expected one detail line per row, got {_notes(live_run)}. Elision 3 in "
        "the README paragraph describes lines the tool no longer emits."
    )


# ----------------------------------------------------------------------
# The derived elisions
# ----------------------------------------------------------------------


def test_the_run_table_paths_are_elided(live_run: str, tour_block: str) -> None:
    """Elision 2, derived: tool absolute, README relative, same basenames."""
    live = _rows(live_run)
    doc = _rows(_run_section(tour_block))
    assert [Path(p).name for _, _, p in live] == [Path(p).name for _, _, p in doc]
    assert not any(Path(p).is_absolute() for _, _, p in doc), (
        "the README run block now shows absolute paths; it no longer elides them, "
        "so elision 2 must come out of the paragraph."
    )


def test_the_run_table_notes_are_elided(live_run: str, tour_block: str) -> None:
    """Elision 3, derived: the tool's detail lines, absent from the run block.

    And the sharp half — both texts appear elsewhere in the same fence, under
    `diff`. That is the justification the paragraph gives for omitting them, so
    it is checked rather than asserted: if a note stopped appearing under `diff`,
    the reason would be false and the paragraph would need rewriting.
    """
    live_notes = _notes(live_run)
    assert _notes(_run_section(tour_block)) == [], (
        "the README run block now carries detail lines; elision 3 is stale."
    )
    for note in live_notes:
        # The leading bullet is the *run* table's framing; under `diff` the same
        # text is introduced by `notes:` for the tolerance override and by
        # `error:` for the embedder mismatch. Compare the message, not the
        # marker -- and compare a prefix, because the README fence hard-wraps
        # the long one across three comment lines.
        head = note.lstrip("- ").strip()[:40]
        assert head in tour_block, (
            f"the run block omits {note!r} and the paragraph justifies that by it "
            f"appearing under `diff` in the same fence — it does not."
        )


# ----------------------------------------------------------------------
# The paragraph accounts for what was derived
# ----------------------------------------------------------------------


def test_the_paragraph_no_longer_claims_a_single_elision() -> None:
    """The exact false claim, pinned by value. Red against the pre-#173 README."""
    text = README.read_text(encoding="utf-8")
    assert "The one elision" not in text, (
        "the README claims a single elision again; there are three, and "
        "test_readme_run_tables.py normalises the second one away."
    )


def test_the_paragraph_names_every_derived_elision() -> None:
    """Each derived elision is described, and the count is stated.

    Keyed on the numbered list the paragraph now carries rather than on a
    sentence, so a rewording survives and a *dropped item* does not.
    """
    text = README.read_text(encoding="utf-8")
    start = text.index("Three things in the block are **not** literal")
    end = text.index("tests/test_readme_run_block_elisions.py")
    para = text[start:end]
    items = re.findall(r"^\d+\. ", para, re.M)
    assert len(items) == 3, f"the elision list has {len(items)} items, the prose says three"
    assert "<abs-path>" in para
    assert "absolute paths" in para
    assert "repo-relative" in para
    assert "detail lines" in para
