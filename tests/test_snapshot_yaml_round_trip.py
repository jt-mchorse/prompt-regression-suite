"""A saved snapshot loads back as itself, including U+0085 (NEL) (#199).

`save_snapshot` dumped with `allow_unicode=True`; PyYAML writes NEL raw in a
quoted scalar and folds it to a space on load: `'a\\x85b'` came back `'a b'`, so
the stored canonical text differed from the text its embedding came from.
"""

from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from prompt_regression.cli import main
from prompt_regression.diff import HashEmbedder
from prompt_regression.io import load_snapshot, save_snapshot
from prompt_regression.schema import CanonicalResponse, Prompt, ResponseShape, Snapshot

ROOT = Path(__file__).resolve().parents[1]


def _snap(text: str, user: str = "Summarise.", sid: str = "s") -> Snapshot:
    e = HashEmbedder()
    return Snapshot(
        id=sid,
        prompt=Prompt(model="m", user=user),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text=text, embedding=e.embed(text), embedding_model=e.model_name
        ),
    )


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("canonical", {"text": "Refunds take 14 days\x85Contact support."}),
        ("prompt", {"text": "ok", "user": "Summarise\x85"}),
        ("id", {"text": "ok", "sid": "refund\x85v1"}),
    ],
)
def test_nel_round_trips(tmp_path: Path, field: str, kwargs: dict) -> None:
    snap = _snap(**kwargs)
    save_snapshot(snap, tmp_path / "s.yml")
    assert load_snapshot(tmp_path / "s.yml").to_dict() == snap.to_dict()


def test_ordinary_unicode_stays_readable(tmp_path: Path) -> None:
    save_snapshot(_snap("Remboursement sous 14 jours — café 退款"), tmp_path / "s.yml")
    raw = (tmp_path / "s.yml").read_text(encoding="utf-8")
    assert "Remboursement sous 14 jours — café 退款" in raw
    assert "\\u" not in raw


def test_without_nel_the_output_is_the_old_rendering_byte_for_byte(tmp_path: Path) -> None:
    # The fallback only fires when the unicode rendering does not round-trip;
    # for the committed examples (and anything without NEL) nothing changes.
    for src in sorted((ROOT / "examples" / "snapshots").glob("*.yml")):
        snap = load_snapshot(src)
        out = tmp_path / src.name
        save_snapshot(snap, out)
        old = yaml.safe_dump(
            snap.to_dict(), sort_keys=False, default_flow_style=False, allow_unicode=True
        )
        assert out.read_text(encoding="utf-8") == old, src.name


def test_cli_update_from_stdin_keeps_nel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "s.yml"
    shutil.copy(ROOT / "examples" / "snapshots" / "refund_window_v1.yml", path)
    text = "Refunds take 14 days\x85\nContact support."
    monkeypatch.setattr(
        sys, "stdin", io.TextIOWrapper(io.BytesIO(text.encode("utf-8")), encoding="utf-8")
    )
    rc = main(
        ["update", "--snapshot", str(path), "--canonical-stdin", "--force", "--embedder", "hash"]
    )
    assert rc == 0
    assert load_snapshot(path).canonical.text == text
