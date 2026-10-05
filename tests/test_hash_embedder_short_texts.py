"""A text shorter than one n-gram no longer embeds to a shared sentinel (#195, D-016).

`HashEmbedder` (default `ngram=2`) built bigrams only, so a one-word text had
none and fell through to `vec[0] = 1.0`: every one-word text -- and the empty
text -- embedded to the same vector, and any two scored cosine 1.0. Measured on
`main`, against a snapshot whose canonical text is `positive`:

    candidate=negative   verdict: pass  cosine: 1.0000   exit 0
    candidate=Error:     verdict: pass  cosine: 1.0000   exit 0

and every single-token semantic-category label scored identically (the
committed demo showed 0.204 for all three).
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest
import yaml

from prompt_regression.cli import main
from prompt_regression.diff import HashEmbedder, cosine, score_semantic_categories
from prompt_regression.io import save_snapshot
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

ROOT = Path(__file__).resolve().parents[1]


def _snapshot_file(tmp_path: Path, canonical: str) -> Path:
    emb = HashEmbedder()
    snap = Snapshot(
        id="sentiment",
        prompt=Prompt(model="claude-haiku-4-5", user="Classify the sentiment."),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text=canonical, embedding=emb.embed(canonical), embedding_model=emb.model_name
        ),
    )
    path = tmp_path / "sentiment.yml"
    save_snapshot(snap, path)
    return path


@pytest.mark.parametrize(("candidate", "rc"), [("negative", 1), ("Error:", 1), ("positive", 0)])
def test_a_one_word_snapshot_catches_a_one_word_swap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], candidate: str, rc: int
) -> None:
    path = _snapshot_file(tmp_path, "positive")
    assert main(["diff", "--snapshot", str(path), "--candidate", candidate]) == rc
    out = capsys.readouterr().out
    assert ("verdict: pass" in out) == (rc == 0), out


def test_distinct_one_word_texts_do_not_share_a_vector() -> None:
    emb = HashEmbedder()
    words = ["positive", "negative", "neutral", "error:", "yes", "no", "kite-imagery", "plan-tier"]
    vecs = {w: emb.embed(w) for w in words}
    # Hash collisions are possible in 128 slots; none occur in this set.
    assert len({tuple(v) for v in vecs.values()}) == len(words)
    assert cosine(vecs["positive"], vecs["negative"]) == 0.0


def test_the_empty_text_keeps_its_sentinel() -> None:
    vec = HashEmbedder().embed("")
    assert vec[0] == 1.0
    assert sum(abs(v) for v in vec) == 1.0


def test_single_token_categories_are_no_longer_scored_identically() -> None:
    # Before: every label was e0, so every category scored the same number for
    # any candidate. Now a label scores only where the candidate contains it as
    # its own one-token text.
    emb = HashEmbedder()
    got = score_semantic_categories("kite-imagery", ["kite-imagery", "plan-tier"], embedder=emb)
    assert [round(s.cosine_to_response, 6) for s in got] == [1.0, 0.0]


def test_every_committed_snapshot_embedding_is_reproduced_bit_for_bit() -> None:
    # The no-change guarantee for texts with >= ngram tokens, against the
    # embeddings actually stored in the repo.
    files = [f for f in glob.glob(str(ROOT / "**" / "*.yml"), recursive=True) if ".venv" not in f]
    checked = 0
    for f in files:
        data = yaml.safe_load(Path(f).read_text(encoding="utf-8"))
        canonical = data.get("canonical") if isinstance(data, dict) else None
        if (
            not isinstance(canonical, dict)
            or canonical.get("embedding_model") != HashEmbedder().model_name
        ):
            continue
        assert HashEmbedder().embed(canonical["text"]) == canonical["embedding"], f
        checked += 1
    # refund_window_v1 stores an OpenAI embedding; creative_kite_v1 is the
    # committed HashEmbedder snapshot.
    assert checked >= 1
