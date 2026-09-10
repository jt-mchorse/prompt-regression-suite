"""`run` enforces the id-uniqueness rule `validate` has enforced since #49 (#167).

`validate.py`'s own module docstring stated the gap in its own words:

    The lone supplemental check (over what `load_snapshot` does file-by-file)
    is `duplicate_id` — *the run path silently key-collides on identical
    `Snapshot.id` across files*, so surfacing those at validate time saves a
    separate audit.

`run` is the path CI executes and it had no equivalent. `Snapshot`'s docstring
says the id "should be unique within a repo's snapshot directory" — an operator
obligation with no check where it matters.

Measured end to end through the CLI on `main`, two snapshot files and ONE
candidate keyed by the shared id::

    CONTROL   distinct ids  b.yml -> verdict=skipped  cosine=None   exit 0
    BUG       same id       b.yml -> verdict=fail     cosine=0.0    exit 1
    FALSE PASS same id/copy b.yml -> verdict=pass     cosine=1.0    exit 0

The control is the crux. With **distinct** ids and a missing candidate the
second file is correctly `skipped` with "no candidate supplied". With a
**duplicate** id it is *evaluated* — so the collision converts an honest "you
did not test this" into a verdict computed against another snapshot's
candidate.

The third row is the one worth the change: `pass`, cosine 1.0, **exit 0**, for
a snapshot that received no candidate of its own. That is the silently-clean
report #150/D-010 established `run` must not produce, and the collision defeats
D-010's own mechanism — `consumed.add(snap.id)` marks the key *used*, so the
unmatched-candidate detection sees nothing wrong.

No new verdict value ships. `ErrorEntry` already exists for a snapshot that
"errored before a `DiffResult` could be produced ... rather than a synthetic
`DiffResult` that would fabricate numbers", is counted in `failed` so the run
exits non-zero, and carries into the HTML artifact so the report cannot read
"all pass" (#71). The shape was already here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from prompt_regression.diff import HashEmbedder
from prompt_regression.io import save_snapshot
from prompt_regression.schema import (
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
)
from prompt_regression.validate import FirstSeenIds, validate_snapshots

EMBEDDER = HashEmbedder()


def _snapshot(snapshot_id: str, user: str, text: str) -> Snapshot:
    return Snapshot(
        id=snapshot_id,
        prompt=Prompt(model="claude-sonnet-5", user=user),
        response_shape=ResponseShape(),
        canonical=CanonicalResponse(
            text=text,
            embedding_model=EMBEDDER.model_name,
            embedding=list(EMBEDDER.embed(text)),
        ),
    )


BASE = _snapshot("refund-v1", "What is the refund window?", "The refund window is 30 days.")
OTHER = _snapshot("poem-v1", "Write a poem about a kite.", "A kite drifts over the harbour.")


def _fixture(tmp_path: Path, second: Snapshot) -> tuple[Path, Path]:
    """`a.yml` is BASE; `b.yml` is *second*. One candidate, keyed by BASE's id.

    Sorted order is `a.yml` then `b.yml`, which is the order both `run` and
    `validate_snapshots` walk — so `b.yml` is the shadow in both.
    """
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    save_snapshot(BASE, snaps / "a.yml")
    save_snapshot(second, snaps / "b.yml")
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text(
        json.dumps({"snapshot": BASE.id, "candidate": BASE.canonical.text}) + "\n",
        encoding="utf-8",
    )
    return snaps, candidates


def _run(snaps: Path, candidates: Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "prompt_regression.cli",
            "run",
            "--snapshots",
            str(snaps),
            "--candidates",
            str(candidates),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.stdout, f"no JSON on stdout; stderr={proc.stderr!r}"
    return proc.returncode, json.loads(proc.stdout)


def _row(payload: dict, filename: str) -> dict:
    matches = [r for r in payload["rows"] if r["snapshot_path"].endswith(filename)]
    assert len(matches) == 1, f"expected one row for {filename}, got {len(matches)}"
    return matches[0]


# --- the control, which must not move --------------------------------------


def test_distinct_ids_with_a_missing_candidate_is_still_skipped(tmp_path: Path) -> None:
    """The anti-vacuous half, and the reason the bug was invisible.

    An id-uniqueness check written too broadly would turn this row into an
    error too — and *this* is the honest report. `skipped` says "you did not
    supply a candidate for this snapshot", which is exactly true.
    """
    code, payload = _run(*_fixture(tmp_path, OTHER))
    assert _row(payload, "a.yml")["verdict"] == "pass"
    row = _row(payload, "b.yml")
    assert row["verdict"] == "skipped"
    assert row["cosine"] is None
    assert "no candidate supplied" in row["notes"]
    assert code == 0, "a clean run with an untested snapshot still exits 0"


# --- the two duplicate cases ------------------------------------------------


@pytest.mark.parametrize(
    ("label", "second"),
    [
        # A genuinely different prompt wearing the same id. On main: fail, cosine 0.0.
        ("different prompt, same id", replace(OTHER, id=BASE.id)),
        # A copy someone renamed. On main: pass, cosine 1.0, EXIT 0 — the row
        # worth the change.
        ("a copy of the first file", replace(BASE, notes="a second file")),
    ],
    ids=["different-prompt", "copy"],
)
def test_a_shadowed_snapshot_is_an_error_and_never_a_cosine(
    tmp_path: Path, label: str, second: Snapshot
) -> None:
    code, payload = _run(*_fixture(tmp_path, second))

    # The first file is untouched — it owns the id and the candidate.
    first = _row(payload, "a.yml")
    assert first["verdict"] == "pass", label
    assert first["cosine"] == pytest.approx(1.0), label

    shadow = _row(payload, "b.yml")
    assert shadow["verdict"] == "error", label
    # The assertion that separates this from every plausible alternative: no
    # number is invented for a row that was not evaluated. `verdict == "error"`
    # alone would pass for an implementation that still computed the cosine and
    # then relabelled it.
    assert shadow["cosine"] is None, f"{label}: a cosine was fabricated for a shadowed file"
    assert shadow["slot_failures"] == [], label
    note = " ".join(shadow["notes"])
    assert "duplicate snapshot id" in note, label
    assert repr(BASE.id) in note, f"{label}: the message does not name the id"
    assert "a.yml" in note, f"{label}: the message does not name the first-seen file"

    assert code == 1, f"{label}: a shadowed snapshot must make the run exit non-zero"


def test_the_false_pass_row_specifically_changed_exit_code(tmp_path: Path) -> None:
    """Named on its own because it is the row that was `exit 0` on main.

    `pass`, cosine 1.0, exit 0, for a snapshot that received no candidate. A
    green CI run reporting two snapshots tested when one candidate was supplied.
    """
    code, payload = _run(*_fixture(tmp_path, replace(BASE, notes="a second file")))
    verdicts = sorted(r["verdict"] for r in payload["rows"])
    assert verdicts == ["error", "pass"], verdicts
    assert code != 0


# --- run and validate must agree -------------------------------------------


def test_run_and_validate_flag_the_same_file_with_the_same_sentence(
    tmp_path: Path,
) -> None:
    """Both walk the directory in sorted order, so `b.yml` is the shadow in
    both, and the reason text comes from one definition.

    Asserted rather than assumed: the shared rule exists precisely so these two
    cannot answer differently, and the previous state of this repo — a rule in
    `validate` and none in `run` — is what that looks like when it drifts all
    the way apart.
    """
    snaps, candidates = _fixture(tmp_path, replace(OTHER, id=BASE.id))

    report = validate_snapshots(snaps)
    assert not report.ok
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.code == "duplicate_id"
    assert finding.path == "b.yml"

    _, payload = _run(snaps, candidates)
    run_note = " ".join(_row(payload, "b.yml")["notes"])

    assert run_note == finding.reason, (
        "run and validate describe the same collision differently:\n"
        f"  run:      {run_note!r}\n"
        f"  validate: {finding.reason!r}"
    )


# --- the shared rule itself -------------------------------------------------


def test_first_seen_ids_records_the_first_and_names_it(tmp_path: Path) -> None:
    ids = FirstSeenIds()
    assert ids.shadow_reason_for("x", "a.yml") is None
    assert ids.shadow_reason_for("y", "b.yml") is None, "a distinct id is not a shadow"
    reason = ids.shadow_reason_for("x", "c.yml")
    assert reason is not None
    assert "a.yml" in reason, "names the FIRST file, not the previous call"
    assert "c.yml" not in reason
    # A third collision still names the first, not the second.
    again = ids.shadow_reason_for("x", "d.yml")
    assert again is not None
    assert "a.yml" in again
    assert "c.yml" not in again


def test_neither_caller_holds_a_second_copy_of_the_rule() -> None:
    """Structural, because a copy passes every behavioural row above.

    This repo measured that exact neighbour in #165 — "copy the rule into
    save_snapshot -> 2 red, and ONLY the two STRUCTURAL arms". Counted over AST
    string literals excluding docstrings, so the paragraphs in this file and in
    `validate.py` quoting the message are not false hits.
    """
    import ast

    from prompt_regression import cli as cli_module
    from prompt_regression import validate as validate_module

    def literals(module: object) -> list[str]:
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))  # type: ignore[attr-defined]
        doc_ids: set[int] = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if (
                isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and body
            ):
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    doc_ids.add(id(first.value))
        return [
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids
        ]

    marker = "duplicate snapshot id "
    val_hits = [t for t in literals(validate_module) if marker in t]
    cli_hits = [t for t in literals(cli_module) if marker in t]
    assert len(val_hits) == 1, f"validate.py holds {len(val_hits)} copies of the message"
    assert cli_hits == [], (
        "cli.py restated the duplicate-id message instead of using "
        f"validate.FirstSeenIds: {cli_hits}"
    )
    # Anti-vacuous: the literal scan really does see validate.py's strings.
    assert len(literals(validate_module)) > 10
    assert len(literals(cli_module)) > 10


def test_the_literal_scan_would_catch_an_inlined_copy() -> None:
    """The check above is `cli_hits == []`, which a scan finding nothing also
    satisfies. Prove the marker is the one actually in use."""
    from prompt_regression.validate import FirstSeenIds as F

    ids = F()
    ids.shadow_reason_for("x", "a.yml")
    reason = ids.shadow_reason_for("x", "b.yml")
    assert reason is not None
    assert reason.startswith("duplicate snapshot id "), (
        "the marker the structural test greps for is no longer the message's prefix, "
        "so that test has stopped testing anything"
    )
