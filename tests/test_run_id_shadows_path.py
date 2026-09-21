"""The candidate key space is ids UNION relative paths (#171).

`run` looks a candidate up in two namespaces — the snapshot's path relative to
the snapshots dir **first**, then its `Snapshot.id`::

    if rel in candidates:        candidate = candidates[rel];      consumed.add(rel)
    elif snap.id in candidates:  candidate = candidates[snap.id];  consumed.add(snap.id)

#167 made the *id* namespace collision-free. Nothing kept the two namespaces
disjoint, and `Snapshot.id` is validated only as a non-empty string — so an id
may be spelled exactly like another file's relative path, and then one candidate
row is consumed by two different snapshots. `FirstSeenIds` could not see it,
because the two **ids** are distinct.

Measured end to end through the CLI before this change — `a.yml` with id
`refund-v1`, `b.yml` with id `"a.yml"`, one candidate keyed `"a.yml"`::

    CONTROL     distinct ids   b.yml -> skipped  None   exit 0   "no candidate supplied"
    COLLIDE     b differs      b.yml -> fail     0.0    exit 1
    FALSE PASS  b is a copy    b.yml -> pass     1.0    exit 0

The control is the crux, exactly as in #167: with a non-colliding id, `b.yml` is
honestly `skipped`. The collision makes it *evaluated* against a candidate
written for another file. The third row is the harm — `pass` at cosine 1.0 and
**exit 0** for a snapshot that received no candidate of its own, which is the
silently-clean report #150/D-010 established `run` must not produce. D-010's own
mechanism is defeated the same way #167 describes: `consumed.add(rel)` marks the
key used, so `unmatched_candidates` comes back `[]`.

`validate` reported the same directory `n_valid: 2, findings: [], ok: True`.

Two things these arms are careful about:

1. **Self-claim is not a collision.** One file whose own id equals its own
   relative path claims a single key, and the lookup consumes it once. That is
   the over-broad neighbour, and it has its own arm.
2. **Which file is the shadow does not depend on walk order.** A relative path
   is a file's identity; an id is operator-chosen metadata. The id-carrier is
   the offender whether it sorts before or after the file whose path it shadows,
   and both directions occur.
"""

from __future__ import annotations

import json
import subprocess
import sys
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
TEXT_A = "The refund window is 30 days."
TEXT_B = "A kite drifts over the harbour."


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


def _fixture(tmp_path: Path, a_id: str, b_id: str, key: str, b_text: str) -> tuple[Path, Path]:
    """`a.yml` and `b.yml`, and ONE candidate row keyed *key*."""
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    save_snapshot(_snapshot(a_id, "What is the refund window?", TEXT_A), snaps / "a.yml")
    save_snapshot(_snapshot(b_id, "Write a poem about a kite.", b_text), snaps / "b.yml")
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text(
        json.dumps({"snapshot": key, "candidate": TEXT_A}) + "\n", encoding="utf-8"
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
    return next(r for r in payload["rows"] if Path(r["snapshot_path"]).name == filename)


# ----------------------------------------------------------------------
# The harm
# ----------------------------------------------------------------------


def test_the_false_pass_at_exit_zero_is_gone(tmp_path: Path) -> None:
    """The row worth the change.

    `b.yml` is a copy of `a.yml`'s canonical text and has id `"a.yml"`. Before
    this change it reported `verdict=pass`, `cosine=1.0`, **exit 0** — a clean
    CI run for a snapshot that received no candidate of its own.
    """
    snaps, candidates = _fixture(tmp_path, "refund-v1", "a.yml", "a.yml", TEXT_A)
    code, payload = _run(snaps, candidates)

    shadow = _row(payload, "b.yml")
    assert shadow["verdict"] == "error"
    assert shadow["cosine"] is None
    assert code == 1, "a shadowed snapshot must not leave the run green"

    note = " ".join(shadow["notes"])
    assert "is also the relative path of another snapshot file" in note
    assert "'a.yml'" in note

    # The file that legitimately owns the key is untouched.
    assert _row(payload, "a.yml")["verdict"] == "pass"


def test_the_collision_no_longer_fabricates_a_regression_either(tmp_path: Path) -> None:
    """The other pre-fix row: `fail` at cosine 0.000 against a foreign candidate.

    Less dangerous than the false pass and still wrong — it reports a regression
    in a snapshot nobody tested.
    """
    snaps, candidates = _fixture(tmp_path, "refund-v1", "a.yml", "a.yml", TEXT_B)
    code, payload = _run(snaps, candidates)

    shadow = _row(payload, "b.yml")
    assert shadow["verdict"] == "error"
    assert shadow["cosine"] is None
    assert code == 1


# ----------------------------------------------------------------------
# The control that makes the harm legible
# ----------------------------------------------------------------------


def test_without_the_collision_the_second_file_is_honestly_skipped(tmp_path: Path) -> None:
    """The crux, as in #167.

    With a non-colliding id, `b.yml` gets no candidate and says so. It is the
    contrast that shows the collision converts "you did not test this" into a
    verdict computed from another snapshot's candidate — and it is what proves
    the fixture would otherwise be silent.
    """
    snaps, candidates = _fixture(tmp_path, "refund-v1", "poem-v1", "a.yml", TEXT_B)
    code, payload = _run(snaps, candidates)

    shadow = _row(payload, "b.yml")
    assert shadow["verdict"] == "skipped"
    assert shadow["cosine"] is None
    assert shadow["notes"] == ["no candidate supplied"]
    assert code == 0


# ----------------------------------------------------------------------
# Both directions, and the over-broad neighbour
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "a_id", "b_id", "key", "offender", "innocent"),
    [
        # The id-carrier sorts AFTER the file whose path it shadows...
        ("id shadows an earlier path", "refund-v1", "a.yml", "a.yml", "b.yml", "a.yml"),
        # ...and BEFORE it. Both occur, and they are symmetric.
        ("id shadows a later path", "b.yml", "poem-v1", "b.yml", "a.yml", "b.yml"),
    ],
)
def test_the_id_carrier_is_the_offender_whichever_way_it_sorts(
    tmp_path: Path, name: str, a_id: str, b_id: str, key: str, offender: str, innocent: str
) -> None:
    """Walk order decides the shadow for an id/id collision and must not here.

    A relative path is a file's identity — unique by construction, not
    changeable without moving the file. An id is operator-chosen metadata. So
    the file carrying the id is the offender either way, and the file whose path
    was shadowed keeps its candidate.
    """
    snaps, candidates = _fixture(tmp_path, a_id, b_id, key, TEXT_A)
    code, payload = _run(snaps, candidates)

    assert _row(payload, offender)["verdict"] == "error", name
    assert _row(payload, innocent)["verdict"] == "pass", name
    assert code == 1, name


def test_a_file_whose_own_id_equals_its_own_path_is_not_a_collision(tmp_path: Path) -> None:
    """The over-broad neighbour.

    One file claiming one key twice is not two files claiming it. `run`'s lookup
    takes the path branch and consumes it once, and this has always worked —
    dropping the `snapshot_id != where` clause breaks it.
    """
    snaps, candidates = _fixture(tmp_path, "a.yml", "poem-v1", "a.yml", TEXT_B)
    code, payload = _run(snaps, candidates)

    assert _row(payload, "a.yml")["verdict"] == "pass"
    assert _row(payload, "b.yml")["verdict"] == "skipped"
    assert code == 0


# ----------------------------------------------------------------------
# Parity: validate sees it too, and says the same sentence
# ----------------------------------------------------------------------


def test_validate_reports_the_collision_and_stops_calling_the_dir_ok(tmp_path: Path) -> None:
    """`validate` is the pre-flight whose whole purpose is this class.

    It reported `n_valid: 2, findings: [], ok: True` for this directory.
    """
    snaps, _ = _fixture(tmp_path, "refund-v1", "a.yml", "a.yml", TEXT_A)
    report = validate_snapshots(snaps)

    assert report.ok is False
    assert [f.code for f in report.findings] == ["duplicate_id"]
    assert [f.path for f in report.findings] == ["b.yml"]
    assert report.n_valid == 1, "the shadow file must not be counted valid"


def test_the_two_paths_produce_the_identical_sentence(tmp_path: Path) -> None:
    """One definition, one wording — the arrangement #167 established."""
    snaps, candidates = _fixture(tmp_path, "refund-v1", "a.yml", "a.yml", TEXT_A)

    _, payload = _run(snaps, candidates)
    run_note = _row(payload, "b.yml")["notes"][0]
    validate_reason = validate_snapshots(snaps).findings[0].reason

    assert run_note == validate_reason


# ----------------------------------------------------------------------
# The rule itself
# ----------------------------------------------------------------------


def test_first_seen_ids_distinguishes_the_two_collisions() -> None:
    ids = FirstSeenIds(["a.yml", "b.yml"])

    # A path this file does not own.
    shadowed = ids.shadow_reason_for("a.yml", "b.yml")
    assert shadowed is not None
    assert "is also the relative path of another snapshot file" in shadowed

    # Its own path is not a collision, and it still claims the id.
    assert ids.shadow_reason_for("a.yml", "a.yml") is None

    # The #167 id/id rule is unchanged, wording included.
    assert ids.shadow_reason_for("shared", "c.yml") is None
    dup = ids.shadow_reason_for("shared", "d.yml")
    assert dup is not None
    assert dup.startswith("duplicate snapshot id 'shared'; first seen at c.yml")


def test_the_rule_is_inert_without_the_paths() -> None:
    """The no-arg constructor keeps #167's exact behaviour.

    Pinned because the widening is opt-in at the call site, so a caller that
    forgets to pass the paths silently gets the narrower rule — which is what
    the two `FirstSeenIds(...)` construction sites in `validate.py` and `cli.py`
    are for, and what the arms above cover end to end.
    """
    ids = FirstSeenIds()
    assert ids.shadow_reason_for("a.yml", "b.yml") is None
    dup = ids.shadow_reason_for("a.yml", "c.yml")
    assert dup is not None
    assert dup.startswith("duplicate snapshot id ")
