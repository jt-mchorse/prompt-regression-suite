"""The dimension-mismatch remedy is a command that runs (#257).

`EmbeddingDimensionMismatchError` used to end with "(prompt-snap update
--force)". Typed as given, that stops at argparse (`--snapshot` is required).
With `--snapshot` added, `update` said the canonical text "was empty", because
`_read_text_arg` folded "no text flag at all" into the blank-text case. The
hint now names every argument `update` needs and says which text to pass back
in. These tests run the hint the way an operator would.
"""

from __future__ import annotations

import io
import re
import shlex
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from prompt_regression import HashEmbedder
from prompt_regression.cli import build_parser, main
from prompt_regression.io import load_snapshot, save_snapshot

ROOT = Path(__file__).resolve().parent.parent
REFUND = ROOT / "examples" / "snapshots" / "refund_window_v1.yml"
CANDIDATE = "The Pro plan has a 14-day refund window."


def _short_vector_snapshot(tmp_path: Path) -> Path:
    """The refund example with its model name set to the hash embedder's, so
    the D-006 name guard passes, and its vector cut to 8 dims."""
    path = tmp_path / "refund_window_v1.yml"
    shutil.copy(REFUND, path)
    snap = load_snapshot(path)
    canonical = replace(
        snap.canonical,
        embedding=snap.canonical.embedding[:8],
        embedding_model=HashEmbedder().model_name,
    )
    save_snapshot(replace(snap, canonical=canonical), path)
    return path


def _remedy(path: Path, capsys: pytest.CaptureFixture[str]) -> str:
    rc = main(["diff", "--snapshot", str(path), "--candidate", CANDIDATE])
    err = capsys.readouterr().err
    assert rc == 2, err
    assert "dims but snapshot" in err, err
    match = re.search(r"current embedder: (prompt-snap update [^,]+),", err)
    assert match is not None, f"no runnable update command in: {err!r}"
    return match.group(1)


def _update_options() -> set[str]:
    parser = build_parser()
    sub = next(a for a in parser._actions if a.dest == "command" or a.choices)
    assert isinstance(sub.choices, dict)
    return {opt for action in sub.choices["update"]._actions for opt in action.option_strings}


def test_every_flag_the_hint_names_is_a_real_update_option(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    command = _remedy(_short_vector_snapshot(tmp_path), capsys)
    flags = [t for t in shlex.split(command) if t.startswith("--")]
    assert flags, command
    unknown = [f for f in flags if f not in _update_options()]
    assert unknown == [], f"{command!r} names flags update does not have: {unknown}"


def test_the_hint_names_snapshot_and_a_canonical_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tokens = shlex.split(_remedy(_short_vector_snapshot(tmp_path), capsys))
    assert "--snapshot" in tokens
    assert "--force" in tokens
    assert "--canonical" in tokens or "--canonical-stdin" in tokens


def test_following_the_hint_re_embeds_and_the_next_diff_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _short_vector_snapshot(tmp_path)
    original_text = load_snapshot(path).canonical.text
    tokens = shlex.split(_remedy(path, capsys))
    assert tokens[:2] == ["prompt-snap", "update"]
    argv = [str(path) if t == "<file>" else t for t in tokens[1:]]
    # The hint says the text on stdin is the snapshot's own canonical.text.
    monkeypatch.setattr("sys.stdin", io.StringIO(original_text))
    rc = main(argv)
    err = capsys.readouterr().err
    assert rc == 0, err

    healed = load_snapshot(path)
    assert len(healed.canonical.embedding) == len(HashEmbedder().embed("x"))
    assert healed.canonical.text == original_text.strip()
    rc = main(["diff", "--snapshot", str(path), "--candidate", original_text])
    assert rc == 0, capsys.readouterr()


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            ["update", "--snapshot", str(REFUND), "--force"],
            "error: pass --canonical or --canonical-stdin",
        ),
        (["diff", "--snapshot", str(REFUND)], "error: pass --candidate or --candidate-stdin"),
    ],
    ids=["update", "diff"],
)
def test_no_text_flag_names_the_missing_flag_not_empty_text(
    argv: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("stdin must not be read"))
    rc = main(argv)
    err = capsys.readouterr().err
    assert rc == 2
    assert message in err, err
    assert "empty" not in err, err


def test_no_text_flag_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "refund_window_v1.yml"
    shutil.copy(REFUND, path)
    before = path.read_bytes()
    assert main(["update", "--snapshot", str(path), "--force"]) == 2
    capsys.readouterr()
    assert path.read_bytes() == before
