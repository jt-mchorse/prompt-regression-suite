"""`score_semantic_categories` refuses a bare string of categories (#192).

`ResponseShape` already refuses `semantic_categories="refund"` on the snapshot
path; this exported function is the other road in, and measured on `main`
`score_semantic_categories(text, "refund", embedder=...)` returned six scores
named r, e, f, u, n, d -- six embedder calls, no error.
"""

from __future__ import annotations

from typing import Any

import pytest

from prompt_regression import score_semantic_categories
from prompt_regression.diff import HashEmbedder
from prompt_regression.schema import ResponseShape, SnapshotValidationError

_SPLIT = "would be scored one character at a time"


class _CountingEmbedder(HashEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return super().embed(text)


@pytest.mark.parametrize("bare", ["refund", b"refund", bytearray(b"r"), ""], ids=repr)
def test_a_bare_string_is_refused_before_any_embedder_call(bare: Any) -> None:
    emb = _CountingEmbedder()
    with pytest.raises(ValueError, match=_SPLIT) as exc:
        score_semantic_categories("a refund was issued", bare, embedder=emb)
    assert str(exc.value).startswith("categories must be a list of labels")
    assert emb.calls == 0


def test_the_message_shows_the_working_spelling() -> None:
    with pytest.raises(ValueError, match=r"pass \['refund'\]"):
        score_semantic_categories("x", "refund", embedder=HashEmbedder())


@pytest.mark.parametrize("cats", [["refund"], ("refund",)], ids=["list", "tuple"])
def test_the_working_spelling_scores_one_category(cats: Any) -> None:
    emb = _CountingEmbedder()
    got = score_semantic_categories("a refund was issued", cats, embedder=emb)
    assert [s.name for s in got] == ["refund"]
    assert emb.calls == 2  # the response, then the one label


def test_an_empty_list_still_returns_nothing() -> None:
    emb = _CountingEmbedder()
    assert score_semantic_categories("x", [], embedder=emb) == []
    assert emb.calls == 0


def test_the_snapshot_path_keeps_its_own_rule() -> None:
    # The other road in, unchanged: ResponseShape refused this before #192.
    with pytest.raises(SnapshotValidationError, match="semantic_categories must be a list"):
        ResponseShape(semantic_categories="refund")  # type: ignore[arg-type]
