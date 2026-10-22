"""An empty candidate fails even when the canonical embeds to ``e0`` (#285).

``HashEmbedder.embed("")`` returns the ``e0`` fallback (D-016 keeps it). But
slot 0 is also one of the 128 slots a real gram hashes into, so a canonical
whose grams all land there embeds to exactly ``e0``, and an empty response then
scored cosine 1.000 against it -- ``pass`` at ``tolerance: 1.0``, exit 0. #63's
``fail`` for an empty candidate rested on that never happening.

"close" and "ballot" are two such one-word canonicals, found by searching a word
list; the first arm proves it, so the red arms cannot pass vacuously.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prompt_regression.cli import main
from prompt_regression.diff import HashEmbedder, diff_response
from prompt_regression.io import save_snapshot
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

SLOT_ZERO_CANONICALS = ["close", "ballot"]
EMPTY_CANDIDATES = ["", "   ", "\n"]


def _snapshot(text: str, *, tolerance: float | None = 1.0) -> Snapshot:
    embedder = HashEmbedder()
    return Snapshot(
        id="ticket-action",
        prompt=Prompt(model="claude-haiku-4-5", user="Which action applies?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text=text,
            embedding=embedder.embed(text),
            embedding_model=embedder.model_name,
        ),
        tolerance=tolerance,
    )


def _run(tmp_path: Path, canonical: str, candidate: str, capsys) -> tuple[int, dict]:
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    save_snapshot(_snapshot(canonical), snaps / "action.yml")
    cands = tmp_path / "c.jsonl"
    cands.write_text(json.dumps({"id": "ticket-action", "candidate": candidate}) + "\n")
    rc = main(["run", "--snapshots", str(snaps), "--candidates", str(cands), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    (row,) = payload["rows"]
    return rc, row


@pytest.mark.parametrize("canonical", SLOT_ZERO_CANONICALS)
def test_canonical_really_embeds_to_the_empty_texts_vector(canonical: str) -> None:
    # Anti-vacuity: without this the arms below would prove nothing.
    embedder = HashEmbedder()
    assert embedder.embed(canonical) == embedder.embed("")


@pytest.mark.parametrize("candidate", EMPTY_CANDIDATES)
@pytest.mark.parametrize("canonical", SLOT_ZERO_CANONICALS)
def test_run_fails_an_empty_candidate_against_a_slot_zero_canonical(
    tmp_path: Path, canonical: str, candidate: str, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, row = _run(tmp_path, canonical, candidate, capsys)
    assert row["verdict"] == "fail", row
    assert rc == 1
    assert any("#285" in n for n in row["notes"]), row["notes"]


@pytest.mark.parametrize("candidate", EMPTY_CANDIDATES)
@pytest.mark.parametrize("canonical", SLOT_ZERO_CANONICALS)
def test_diff_response_fails_an_empty_candidate_at_every_threshold(
    canonical: str, candidate: str
) -> None:
    # The library path too, and with no per-snapshot tolerance: the score is
    # still the honest 1.0, only the verdict is decided on the text.
    result = diff_response(
        _snapshot(canonical, tolerance=None), candidate, embedder=HashEmbedder(), threshold=0.5
    )
    assert result.cosine_score == pytest.approx(1.0)
    assert result.verdict == "fail"


# ---- controls (green before and after) ----


@pytest.mark.parametrize("candidate", ["", "   "])
def test_control_blank_canonical_with_empty_candidate_still_passes(candidate: str) -> None:
    # The schema refuses an empty canonical text but takes a whitespace-only
    # one; nothing against nothing is not the regression #285 is about.
    result = diff_response(_snapshot("  \n"), candidate, embedder=HashEmbedder())
    assert result.cosine_score == pytest.approx(1.0)
    assert result.verdict == "pass"
    assert not any("#285" in n for n in result.notes)


@pytest.mark.parametrize("canonical", SLOT_ZERO_CANONICALS)
def test_control_the_canonical_itself_still_passes(
    tmp_path: Path, canonical: str, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, row = _run(tmp_path, canonical, canonical, capsys)
    assert row["verdict"] == "pass"
    assert row["cosine"] == pytest.approx(1.0)
    assert rc == 0


def test_control_a_real_wrong_answer_scores_and_fails_as_before(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, row = _run(tmp_path, "close", "open", capsys)
    assert row["verdict"] == "fail"
    assert row["cosine"] == pytest.approx(0.0)
    assert not any("#285" in n for n in row["notes"])
    assert rc == 1


def test_control_the_empty_texts_embedding_is_unchanged() -> None:
    # D-016's THE_EMPTY_TEXT_KEEPS_e0: the fix is in scoring, not the embedder.
    vec = HashEmbedder().embed("")
    assert vec[0] == 1.0
    assert sum(vec) == 1.0
