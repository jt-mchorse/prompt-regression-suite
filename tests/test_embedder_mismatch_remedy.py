"""The D-006 mismatch error names a switch that exists where it is printed (#255).

`EmbedderModelMismatchError` told the operator to "pass force=True to
override". That is the `diff_response()` keyword. `prompt-snap run` and
`prompt-snap diff` relay `str(e)` unchanged -- as a row note (text / JSON /
HTML) and as the `error:` line -- and on the CLI there is no `force=True`: the
switch is `--force-embedder`, and typing what the error said is a usage error.

One message is shared by every surface, so it names both spellings. These locks
check each surface carries the CLI flag, that the flag it names really is the
one that switches the guard off, and that the README's copies are the live text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from prompt_regression.cli import build_parser, main
from prompt_regression.diff import EmbedderModelMismatchError, HashEmbedder, diff_response
from prompt_regression.io import save_snapshot
from prompt_regression.schema import (
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
TEXT = "Our refund policy gives Pro plan customers 14 days to request a return."
FOREIGN_MODEL = "different-embedder-v1"


def _snapshot() -> Snapshot:
    # Embedded with the hash embedder (so a forced diff can compare vectors of
    # the same dimension) but *recorded* under another model's name, which is
    # exactly the case the D-006 guard refuses.
    e = HashEmbedder()
    return Snapshot(
        id="mismatch",
        prompt=Prompt(model="claude-haiku-4-5", user="?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text=TEXT, embedding=e.embed(TEXT), embedding_model=FOREIGN_MODEL
        ),
    )


@pytest.fixture
def snap_path(tmp_path: Path) -> Path:
    d = tmp_path / "snapshots"
    d.mkdir()
    p = d / "mismatch.snapshot.yaml"
    save_snapshot(_snapshot(), p)
    return p


def _candidates(tmp_path: Path) -> Path:
    p = tmp_path / "cands.jsonl"
    p.write_text(json.dumps({"id": "mismatch", "candidate": TEXT}) + "\n", encoding="utf-8")
    return p


def _mismatch_message() -> str:
    with pytest.raises(EmbedderModelMismatchError) as info:
        diff_response(_snapshot(), TEXT, embedder=HashEmbedder())
    return str(info.value)


def test_library_message_names_both_spellings():
    msg = _mismatch_message()
    assert "force=True" in msg
    assert "--force-embedder" in msg


def test_named_flag_is_a_real_option_on_run_and_diff():
    parser = build_parser()
    for sub in ("run", "diff"):
        # parse_args exits on an unknown option, so this is the existence check.
        args = parser.parse_args(
            [sub, "--force-embedder"]
            + (
                ["--snapshots", "d", "--candidates", "c"]
                if sub == "run"
                else ["--snapshot", "s", "--candidate", "x"]
            )
        )
        assert args.force_embedder is True


def test_diff_error_line_names_the_cli_flag(snap_path: Path, capsys: pytest.CaptureFixture[str]):
    rc = main(["diff", "--snapshot", str(snap_path), "--candidate", TEXT])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--force-embedder" in err


def test_diff_with_the_named_flag_passes_the_guard(
    snap_path: Path, capsys: pytest.CaptureFixture[str]
):
    rc = main(["diff", "--snapshot", str(snap_path), "--candidate", TEXT, "--force-embedder"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "--force-embedder" not in captured.err
    assert "pass" in captured.out


@pytest.mark.parametrize("fmt", ["text", "json"])
def test_run_row_note_names_the_cli_flag(
    snap_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], fmt: str
):
    rc = main(
        [
            "run",
            "--snapshots",
            str(snap_path.parent),
            "--candidates",
            str(_candidates(tmp_path)),
            "--format",
            fmt,
        ]
    )
    assert rc != 0
    assert "--force-embedder" in capsys.readouterr().out


def test_run_html_row_note_names_the_cli_flag(snap_path: Path, tmp_path: Path):
    out = tmp_path / "report.html"
    main(
        [
            "run",
            "--snapshots",
            str(snap_path.parent),
            "--candidates",
            str(_candidates(tmp_path)),
            "--format",
            "html",
            "--out",
            str(out),
        ]
    )
    assert "--force-embedder" in out.read_text(encoding="utf-8")


def test_run_with_the_named_flag_passes_the_guard(
    snap_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    rc = main(
        [
            "run",
            "--snapshots",
            str(snap_path.parent),
            "--candidates",
            str(_candidates(tmp_path)),
            "--force-embedder",
        ]
    )
    assert rc == 0
    assert "failed=0" in capsys.readouterr().out


def test_readme_copies_are_the_live_message():
    # The live message with this snapshot's model names swapped for the README
    # example's, so the check is on the remedy wording, not on the fixture.
    live = _mismatch_message().replace(FOREIGN_MODEL, "text-embedding-3-small-truncated-8d")
    readme = README.read_text(encoding="utf-8")
    # The `run` table under "HTML report" carries the message on one line.
    assert live in readme
    # The CLI tour's `diff` example wraps it across `# ` comment lines.
    wrapped = re.search(r"# error: snapshot was embedded with .*?override\.", readme, re.S)
    assert wrapped is not None
    unwrapped = re.sub(r"\n# ", " ", wrapped.group(0)).removeprefix("# error: ")
    assert unwrapped == live
