"""Each subcommand's text-argument messages name its own flag and noun (#183).

`_read_text_arg` is shared by `update` (`--canonical`) and `diff`
(`--candidate`), and both of its messages were hard-coded: `diff --candidate x
--candidate-stdin` was told to "pass --canonical OR --canonical-stdin", flags
`diff` does not have, and `update` with blank text was told the "candidate
text was empty".
"""

from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest

from prompt_regression import cli

_ROOT = Path(__file__).resolve().parent.parent
_SNAPSHOT = _ROOT / "examples" / "snapshots" / "refund_window_v1.yml"


def _run(argv: list[str], stdin: str, monkeypatch: pytest.MonkeyPatch, capsys) -> tuple[int, str]:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    rc = cli.main(argv)
    return rc, capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "stdin", "message"),
    [
        (
            ["diff", "--snapshot", str(_SNAPSHOT), "--candidate", "x", "--candidate-stdin"],
            "hi",
            "error: pass --candidate OR --candidate-stdin, not both",
        ),
        (
            ["diff", "--snapshot", str(_SNAPSHOT), "--candidate", "   "],
            "",
            "error: candidate text was empty after stripping whitespace",
        ),
        (
            ["update", "--snapshot", "SNAP", "--canonical", "x", "--canonical-stdin", "--force"],
            "hi",
            "error: pass --canonical OR --canonical-stdin, not both",
        ),
        (
            ["update", "--snapshot", "SNAP", "--canonical-stdin", "--force"],
            "   ",
            "error: canonical text was empty after stripping whitespace",
        ),
    ],
    ids=["diff-both", "diff-blank", "update-both", "update-blank"],
)
def test_the_message_names_the_subcommands_own_flag(
    argv: list[str],
    stdin: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snap = tmp_path / "s.yml"
    snap.write_bytes(_SNAPSHOT.read_bytes())
    argv = [str(snap) if a == "SNAP" else a for a in argv]
    rc, err = _run(argv, stdin, monkeypatch, capsys)
    assert rc == 2
    assert err.strip() == message
    # The snapshot `update` was pointed at is untouched by a refused call.
    assert snap.read_bytes() == _SNAPSHOT.read_bytes()


def test_every_call_site_passes_a_flag_its_parser_defines() -> None:
    """A third caller must name its own flags, not inherit another's."""
    tree = ast.parse((_ROOT / "prompt_regression" / "cli.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_read_text_arg"
    ]
    assert len(calls) == 2
    for call in calls:
        kw = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
        # `args.canonical` -> "--canonical": the attribute read and the flag named
        # in the message are the same option.
        attr = ast.unparse(call.args[0]).removeprefix("args.")
        assert kw["flag"] == "--" + attr.replace("_", "-")
        assert kw["noun"] == attr
