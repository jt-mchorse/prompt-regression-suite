"""Every `prompt-snap run` table in the README is pinned to measured output (#169).

The README shows `run`'s output twice — once in the feature narrative
("the text format shows the same result") and once at the top of the CLI-tour
fence. Neither was pinned, and one had already drifted: its header read
``total=2 failed=1 skipped=0`` while the tool prints
``total=2 failed=1 skipped=0 unmatched=0``.

Two prose claims would each have caught it and each covered a smaller scope than
it reads as:

* README line 333 says "Every verdict, cosine and count in **the block above** is
  the tool's actual output, pinned by ``tests/test_readme_cli_tour_examples.py``".
  `_readme_tour()` sliced that fence from ``"# Ad-hoc diff"``, which comes *after*
  the `run` demonstration, so the first nine lines of "the block above" were
  outside the lock the sentence cites. #169 widens the slice to the fence so the
  sentence is true.
* ``test_the_pass_cosine_is_the_same_number_the_run_table_reports`` ran `diff`,
  never `run`, and finished with ``assert "0.806" in README.read_text()`` — "the
  substring appears somewhere in a 400-line file", satisfied by any of four
  unrelated mentions. Measured: rewriting **both** run tables to ``0.900`` while
  leaving the `diff` examples alone left all 683 tests green.

So this module asks the question neither asked: does each README run table say what
`run` actually prints? The population is **discovered** from the README, because a
hand list is exactly what produced two blocks and one lock.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
README = _REPO_ROOT / "README.md"

#: The header `run` prints, as a field-name pattern rather than a fixed string, so
#: a row-count change is a value mismatch (loud, specific) and a *new field* is a
#: field-set mismatch (also loud). Finding #1 was a missing field, which a
#: cosine-only comparison would not have caught.
_HEADER = re.compile(r"#\s*prompt-snap run\s+(?P<fields>(?:\w+=\S+\s*)+)")

#: A table row: verdict, cosine (or the `-.--` placeholder), snapshot path.
_ROW = re.compile(
    r"^#?\s*(?P<verdict>pass|warn|fail|error)\s+(?P<cosine>-\.--|[0-9.]+)\s+(?P<path>\S+)\s*$"
)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_table(text: str) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """`(header fields, rows)` from either real CLI output or a README block.

    One parser for both sides on purpose: a README-side parser that accepted a
    shape the CLI never emits would make the comparison vacuous in the direction
    that matters.
    """
    header = _HEADER.search(text)
    fields: dict[str, str] = {}
    if header:
        for pair in header.group("fields").split():
            key, _, value = pair.partition("=")
            fields[key] = value
    rows: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        match = _ROW.match(line.strip())
        if match:
            rows.append(
                (
                    match.group("verdict"),
                    match.group("cosine"),
                    # The CLI resolves `--snapshots` to an absolute path; the README
                    # shows the repo-relative one. Compare the basename, which is
                    # the part that identifies the snapshot either way.
                    Path(match.group("path")).name,
                )
            )
    return fields, rows


def _readme_run_blocks() -> list[tuple[int, str]]:
    """Every fenced block in the README that shows `run`'s output table.

    Discovered, not listed: located by the header signature the tool prints, so a
    third block added later is covered automatically. That is the whole point —
    #169 exists because there were two blocks and a lock that reached neither.
    """
    text = README.read_text(encoding="utf-8")
    blocks: list[tuple[int, str]] = []
    for fence in re.finditer(r"```[a-z]*\n(.*?)```", text, re.S):
        body = fence.group(1)
        if _HEADER.search(body):
            line_no = text[: fence.start()].count("\n") + 1
            blocks.append((line_no, body))
    return blocks


@pytest.fixture(scope="module")
def live_table() -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    proc = _run_cli(
        "run", "--snapshots", "examples/snapshots", "--candidates", "examples/candidates.jsonl"
    )
    # Exit 1 is the documented "a snapshot failed" outcome for these fixtures.
    assert proc.returncode == 1, (
        f"expected exit 1, got {proc.returncode}\n{proc.stdout}{proc.stderr}"
    )
    fields, rows = _parse_table(proc.stdout)
    assert fields, f"could not parse a header from the CLI output:\n{proc.stdout}"
    assert rows, f"could not parse any rows from the CLI output:\n{proc.stdout}"
    return fields, rows


def test_the_readme_has_more_than_one_run_block(live_table: object) -> None:
    """Anti-vacuous, and it pins the reason this module exists.

    If the README is ever reduced to one run block this still passes at >= 1, but
    the assertion message records why the discovery is not a hand list.
    """
    blocks = _readme_run_blocks()
    assert len(blocks) >= 1, "no `run` output block found in the README — the pattern went stale"
    assert len(blocks) == 2, (
        f"expected the two documented run blocks (feature narrative + CLI tour); "
        f"found {len(blocks)} at lines {[n for n, _ in blocks]}. If a block was added "
        f"or removed deliberately, update this count — the point is that the number "
        f"is stated rather than assumed."
    )


def test_every_readme_run_header_matches_the_tool(
    live_table: tuple[dict[str, str], list[tuple[str, str, str]]],
) -> None:
    """The field SET and every value. A missing field was finding #1."""
    live_fields, _ = live_table
    for line_no, body in _readme_run_blocks():
        readme_fields, _ = _parse_table(body)
        assert set(readme_fields) == set(live_fields), (
            f"README:{line_no} run header field set is {sorted(readme_fields)}; the tool "
            f"prints {sorted(live_fields)}. A field added to the header has to reach "
            f"every documented block, not the most recently edited one (#169)."
        )
        assert readme_fields == live_fields, (
            f"README:{line_no} run header is {readme_fields}; the tool prints {live_fields}"
        )


def test_every_readme_run_row_matches_the_tool(
    live_table: tuple[dict[str, str], list[tuple[str, str, str]]],
) -> None:
    """Verdict, cosine and snapshot, per row, in order."""
    _, live_rows = live_table
    for line_no, body in _readme_run_blocks():
        _, readme_rows = _parse_table(body)
        assert readme_rows, f"README:{line_no} shows a run header but no parseable rows"
        assert readme_rows == live_rows, (
            f"README:{line_no} run table is {readme_rows}; the tool prints {live_rows}.\n"
            f"Regenerate by running:\n"
            f"  python -m prompt_regression.cli run --snapshots examples/snapshots "
            f"--candidates examples/candidates.jsonl"
        )


def test_the_run_table_cosine_is_the_number_diff_prints(
    live_table: tuple[dict[str, str], list[tuple[str, str, str]]],
) -> None:
    """The cross-block check `test_readme_cli_tour_examples` was named for.

    That one ran `diff`, never `run`, and ended with `"0.806" in README` — the
    substring, anywhere in the file. This takes the cosine from the **run table**
    and from `diff`, both out of the tool, and asserts the rounding relationship
    the README describes ("Same measurement, different rounding").
    """
    _, live_rows = live_table
    passing = [r for r in live_rows if r[0] == "pass"]
    assert len(passing) == 1, f"expected exactly one passing row; got {passing}"
    table_cosine = passing[0][1]

    kite = "examples/snapshots/creative_kite_v1.yml"
    candidate = (
        "A kite drifts above an empty beach in the late afternoon. The salt wind tugs "
        "the string, a child below laughs and tugs back, and the horizon is a thin "
        "orange line, almost gone."
    )
    proc = _run_cli("diff", "--snapshot", kite, "--candidate", candidate)
    match = re.search(r"cosine:\s+([0-9.]+)", proc.stdout)
    assert match, proc.stdout
    assert f"{float(match.group(1)):.3f}" == table_cosine, (
        f"`diff` prints {match.group(1)} which rounds to "
        f"{float(match.group(1)):.3f}, but the run table prints {table_cosine}. The "
        f"README describes these as the same measurement at different rounding."
    )


def test_the_parsers_reject_a_shape_the_cli_never_emits() -> None:
    """Anti-vacuous for the comparison itself.

    A README-side parser that silently found nothing would make every assertion
    above pass on an empty set. These rows pin that the header and row patterns
    are specific enough to fail rather than shrug.
    """
    fields, rows = _parse_table("nothing resembling a run table here\n")
    assert fields == {}
    assert rows == []
    # A row missing its cosine column is not a row.
    _, bad = _parse_table("# pass      examples/snapshots/creative_kite_v1.yml\n")
    assert bad == []
    # And the real shape IS parsed, or the negatives above prove nothing.
    good_fields, good_rows = _parse_table(
        "# prompt-snap run  total=2 failed=1 skipped=0 unmatched=0\n"
        "# pass      0.806   examples/snapshots/creative_kite_v1.yml\n"
        "# error      -.--   examples/snapshots/refund_window_v1.yml\n"
    )
    assert good_fields == {"total": "2", "failed": "1", "skipped": "0", "unmatched": "0"}
    assert good_rows == [
        ("pass", "0.806", "creative_kite_v1.yml"),
        ("error", "-.--", "refund_window_v1.yml"),
    ]


def test_the_lock_catches_both_drift_shapes() -> None:
    """Both failure modes #169 found, simulated against the parser.

    The cosine rewrite is the edit that left all 683 tests green; the missing
    header field is the drift that had already happened. A check built for one
    does not catch the other, which is why both are asserted here rather than
    trusting one arm to stand for the pair.
    """
    live_fields = {"total": "2", "failed": "1", "skipped": "0", "unmatched": "0"}
    live_rows = [("pass", "0.806", "creative_kite_v1.yml")]

    rewritten_cosine, rows_a = _parse_table(
        "# prompt-snap run  total=2 failed=1 skipped=0 unmatched=0\n"
        "# pass      0.900   examples/snapshots/creative_kite_v1.yml\n"
    )
    assert rewritten_cosine == live_fields, "the header half must be unaffected"
    assert rows_a != live_rows, "a rewritten cosine must be visible as a row mismatch"

    dropped_field, rows_b = _parse_table(
        "# prompt-snap run  total=2 failed=1 skipped=0\n"
        "# pass      0.806   examples/snapshots/creative_kite_v1.yml\n"
    )
    assert rows_b == live_rows, "the row half must be unaffected"
    assert set(dropped_field) != set(live_fields), (
        "a missing header field must be visible as a field-set mismatch, not only "
        "as a value mismatch"
    )
