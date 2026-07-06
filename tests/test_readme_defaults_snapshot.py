"""README ↔ source-constant defaults snapshot (#17).

Sister to `test_regression_demo_snapshot.py` (which locks the rendered
HTML to script output) and to the portfolio-wide snapshot pattern. This
module closes the orthogonal axis: README claims that quote source
constants in prose, plus the `prompt-snap` subcommand bullet that the
existing CLI tests don't yet pin against the README.

Source of truth is the live source value — if a test fails, update the
README quote to match (not the other way around).

Pairings locked:

1. README `threshold=0.85` (quoted multiple times) ↔
   `prompt_regression.diff.DEFAULT_THRESHOLD`.
2. README `pip install -e '.[dev]'` ↔ keys under
   `[project.optional-dependencies]` in `pyproject.toml`.
3. README `prompt-snap` console-script name ↔ keys under
   `[project.scripts]` in `pyproject.toml`.
4. README `prompt-snap run | update | diff` bullet ↔ live argparse
   subcommand surface from `prompt_regression.cli.build_parser()`.
5. The Diff-layer runnable code block (snapshot path + candidate +
   `HashEmbedder()`) actually executes without raising. This caught #109:
   the block paired `HashEmbedder()` (128-dim, `hash-embedder-128d-ngram2`)
   with `refund_window_v1.yml` (8-dim, OpenAI `text-embedding-3-small-
   truncated-8d`), which crashed on BOTH the D-006 model-name guard and the
   embedding-dimension check — `force=True` couldn't rescue it. The example
   must use a snapshot the documented embedder can actually diff.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from prompt_regression import HashEmbedder, diff_response, load_snapshot
from prompt_regression.cli import build_parser
from prompt_regression.diff import DEFAULT_THRESHOLD

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"

REGEN_HINT = (
    "Source is the truth: update the README quote to match the new live "
    "value (not the other way around)."
)


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _live_subcommands() -> set[str]:
    """Discover the live `prompt-snap` subcommand surface via argparse."""
    parser = build_parser()
    # Find the subparsers action (first `_SubParsersAction` in the parser).
    for action in parser._actions:  # noqa: SLF001 — argparse exposes no public iteration
        choices = getattr(action, "choices", None)
        if choices and all(isinstance(k, str) for k in choices):
            return set(choices)
    raise AssertionError(
        "Could not locate the subparsers action in build_parser()'s parser. "
        "Has the CLI structure changed?"
    )


def test_readme_quotes_live_default_threshold() -> None:
    """README `threshold=0.85` (signature example + `(threshold 0.85)`
    in CLI output) must equal `prompt_regression.diff.DEFAULT_THRESHOLD`."""
    body = _readme()
    # Two surfaces in the README quote the default:
    #   - `diff_response(..., threshold=0.85)` in the diff-layer code block.
    #   - `cosine: 0.812 (threshold 0.85)` in the prompt-snap diff example.
    sig_match = re.search(r"diff_response\([^)]*threshold=([\d.]+)", body)
    out_match = re.search(r"\(threshold ([\d.]+)\)", body)
    assert sig_match, (
        "README must quote the default threshold as `diff_response(..., "
        "threshold=<N>, ...)` in the Diff-layer code block."
    )
    assert out_match, (
        "README must quote the default threshold as `(threshold <N>)` in "
        "the `prompt-snap diff` example output."
    )
    sig_v = float(sig_match.group(1))
    out_v = float(out_match.group(1))
    assert sig_v == out_v, (
        f"README quotes two different default thresholds: "
        f"`threshold={sig_v}` in the signature and `(threshold {out_v})` in "
        f"the CLI output. Pick one and align both anchors."
    )
    assert sig_v == DEFAULT_THRESHOLD, (
        f"README quotes default threshold as {sig_v} but "
        f"prompt_regression.diff.DEFAULT_THRESHOLD = {DEFAULT_THRESHOLD}. "
        f"{REGEN_HINT}"
    )


def test_readme_pip_extras_all_exist_in_pyproject() -> None:
    """Every `pip install -e '.[<extra>]'` quoted in the README must be a
    declared optional-dependencies key."""
    body = _readme()
    quoted = set(re.findall(r"pip install -e '\.\[([^\]]+)\]'", body))
    assert quoted, (
        "README must quote at least one `pip install -e '.[<extra>]'` "
        "command for this test to lock anything."
    )
    with PYPROJECT.open("rb") as fh:
        pyproject = tomllib.load(fh)
    live = set(pyproject.get("project", {}).get("optional-dependencies", {}).keys())
    missing = sorted(quoted - live)
    assert not missing, (
        f"README quotes `pip install -e '.[{','.join(missing)}]'` but "
        f"{missing} are not keys under [project.optional-dependencies] in "
        f"pyproject.toml (live keys: {sorted(live)}). {REGEN_HINT}"
    )


def test_readme_console_script_name_matches_pyproject() -> None:
    """The README's `prompt-snap` console-script name must match the key
    under `[project.scripts]` in pyproject.toml — a rename would silently
    orphan every example in the README."""
    body = _readme()
    # README must mention the script by name in the Quickstart or CLI section.
    quoted = set(re.findall(r"`(prompt-[a-z-]+)`", body))
    assert quoted, (
        "README must reference the console script by name in backticks "
        "(e.g., `prompt-snap`) for this test to lock anything."
    )

    with PYPROJECT.open("rb") as fh:
        pyproject = tomllib.load(fh)
    live = set(pyproject.get("project", {}).get("scripts", {}).keys())
    # The README may mention multiple `prompt-*` strings (e.g. project name); we
    # only care that the one(s) it backticks intersect the registered scripts.
    overlap = quoted & live
    assert overlap, (
        f"README backticks `prompt-*` strings {sorted(quoted)} but none of "
        f"them are registered under [project.scripts] in pyproject.toml "
        f"(live: {sorted(live)}). If the script was renamed, update both "
        f"the README and any usage examples. {REGEN_HINT}"
    )


def test_readme_subcommand_bullet_matches_live_argparse() -> None:
    """`What this is` bullet 5 quotes `prompt-snap run | update | diff`.
    Must match the live argparse subcommand surface."""
    body = _readme()
    bullet_match = re.search(r"\*\*CLI\*\* \(#5\)\s*—\s*`([^`]+)`", body)
    assert bullet_match, (
        "README 'What this is' bullet 5 must quote the CLI surface as "
        "'**CLI** (#5) — `prompt-snap <a> | <b> | <c>`' for this test to lock it."
    )
    raw = bullet_match.group(1)
    if raw.startswith("prompt-snap "):
        raw = raw[len("prompt-snap ") :]
    documented = {tok.strip() for tok in raw.split("|") if tok.strip()}

    live = _live_subcommands()

    missing = sorted(live - documented)
    extra = sorted(documented - live)
    assert not missing, (
        f"README CLI bullet (#5) is missing live subcommand(s): {missing}. "
        f"Live argparse surface: {sorted(live)}. Documented: {sorted(documented)}. "
        f"{REGEN_HINT}"
    )
    assert not extra, (
        f"README CLI bullet (#5) lists subcommand(s) that aren't in argparse: "
        f"{extra}. Live: {sorted(live)}. Documented: {sorted(documented)}. "
        f"Remove the stale name. {REGEN_HINT}"
    )


def _diff_layer_section() -> str:
    """Return the README's `## Diff layer` section text (up to the next
    heading) so the runnable example can be extracted from exactly what a
    reader copies."""
    body = _readme()
    start = body.index("## Diff layer")
    # Next `## ` heading (not `### `) ends the section.
    rest = body[start + len("## Diff layer") :]
    end_rel = rest.index("\n## ")
    return body[start : start + len("## Diff layer") + end_rel]


def test_readme_diff_layer_example_executes_hermetically() -> None:
    """The Diff-layer code block must run as written: load the documented
    snapshot and run `diff_response(..., embedder=HashEmbedder())` on the
    documented candidate without raising.

    The snapshot path and candidate are extracted from the README so the
    test exercises exactly the copy-pasteable example — if the block is
    ever re-pointed at a snapshot the documented embedder can't diff (model
    or dimension mismatch), this fails instead of shipping a crashing
    quickstart (#109).
    """
    section = _diff_layer_section()

    snap_match = re.search(r'load_snapshot\("([^"]+)"\)', section)
    cand_match = re.search(r'candidate = "([^"]+)"', section)
    assert snap_match, (
        "README Diff-layer block must call "
        '`load_snapshot("examples/snapshots/<name>.yml")` for this test to lock it.'
    )
    assert cand_match, (
        'README Diff-layer block must assign `candidate = "..."` for this test to lock it.'
    )
    assert "diff_response(" in section, "README Diff-layer block must call `diff_response(...)`."
    assert "HashEmbedder()" in section, (
        "README Diff-layer block must diff with `embedder=HashEmbedder()`."
    )

    snap_path = REPO_ROOT / snap_match.group(1)
    candidate = cand_match.group(1)
    snap = load_snapshot(snap_path)

    # Must not raise EmbedderModelMismatchError / EmbeddingDimensionMismatchError.
    result = diff_response(snap, candidate, embedder=HashEmbedder())
    assert result.verdict in {"pass", "warn", "fail"}, (
        f"Diff-layer example produced an unexpected verdict {result.verdict!r}; "
        f"the README documents the range as 'pass | warn | fail'. {REGEN_HINT}"
    )
    assert result.cosine_score == result.cosine_score, (  # NaN guard
        "Diff-layer example produced a non-finite cosine score."
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(__import__("pytest").main([__file__, "-v"]))
