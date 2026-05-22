"""Architecture-doc lock: catch drift between `docs/architecture.md` and
the actual shipped surface of the repo.

Fourth Python sister of the architecture-doc lock pattern this session
(after `embedding-model-shootout` PR #20, `vector-search-at-scale` PR
#22, `llm-eval-harness` PR #30). Three invariants pinned:

1. Path-token reachability — every backtick-quoted token starting with
   one of `RESOLVABLE_PREFIXES` resolves on disk. Placeholders (`<...>`,
   `{...}`, `*`) are skipped.

2. Closed-feature-issue coverage — every issue in `KNOWN_SHIPPED_ISSUES`
   is referenced at least once.

3. Banned-phrase absence — phrases that characterized the pre-#24 drift
   are absent (case-insensitive).

Three hard-pin tests lock `BANNED_PHRASES`, `KNOWN_SHIPPED_ISSUES`,
and `RESOLVABLE_PREFIXES` to their exact contents.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "architecture.md"

# Closed feature issues whose work the architecture doc should
# enumerate. Each represents a shipped surface with a code/artifact
# home in the repo.
#
# Intentionally excluded from the coverage check (locked elsewhere):
#   - #12  HTML demo snapshot — locked by
#          tests/test_regression_demo_snapshot.py
#   - #14  README session-framing pivot — locked by
#          tests/test_readme_defaults_snapshot.py
#   - #15  60-second capture (operator artifact)
#   - #17  README defaults snapshot — locked by
#          tests/test_readme_defaults_snapshot.py
#   - #19  Public surface lock — locked by tests/test_public_surface.py
#   - #22  CLI glob fix — locked by tests/test_cli.py
KNOWN_SHIPPED_ISSUES = (1, 2, 3, 4, 5, 10)

# Drift shapes specific to issue #24's pre-fix state. Lowercase
# substring match. Pinned in a tuple so a future loose edit of the
# test can't silently drop one.
BANNED_PHRASES = (
    "this pr",
    "(unfiled)",
    "to-be-filed",
)

# Path-token prefixes that must resolve on disk if quoted in the doc.
RESOLVABLE_PREFIXES = (
    "prompt_regression/",
    "scripts/",
    "tests/",
    "docs/",
    ".github/",
)


@pytest.fixture(scope="module")
def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def _extract_backtick_paths(text: str) -> set[str]:
    """Collect every backtick-quoted token starting with a resolvable
    prefix. Placeholder shapes (`<...>`, `{...}`, `*`) are skipped.
    """
    found: set[str] = set()
    for match in re.finditer(r"`([^`\n]+)`", text):
        token = match.group(1).strip()
        for prefix in RESOLVABLE_PREFIXES:
            if token.startswith(prefix):
                while token and token[-1] in ".,;:":
                    token = token[:-1]
                token = re.sub(r"\(\)$", "", token)
                if "<" in token or "{" in token or "*" in token:
                    break
                if token:
                    found.add(token)
                break
    return found


def _resolves_on_disk(token: str) -> bool:
    return (REPO_ROOT / token).exists()


def test_doc_exists() -> None:
    assert DOC.exists(), f"missing {DOC}"


def test_backtick_paths_resolve_on_disk(doc_text: str) -> None:
    tokens = _extract_backtick_paths(doc_text)
    unresolved = sorted(t for t in tokens if not _resolves_on_disk(t))
    assert not unresolved, (
        "docs/architecture.md quotes paths that don't exist on disk:\n"
        + "\n".join(f"  - `{t}`" for t in unresolved)
        + "\n(regenerate the doc to match the current layout, or fix the typo)"
    )


def test_every_shipped_issue_referenced(doc_text: str) -> None:
    referenced = {int(m.group(1)) for m in re.finditer(r"#(\d+)\b", doc_text)}
    missing = sorted(set(KNOWN_SHIPPED_ISSUES) - referenced)
    assert not missing, (
        "docs/architecture.md doesn't reference these closed-feature-issues "
        "even once:\n"
        + "\n".join(f"  - #{n}" for n in missing)
        + "\n(every shipped surface should have its origin issue annotated "
        "in the doc; add a `(#NN)` to the relevant component bullet or diagram node)"
    )


def test_no_banned_phrases(doc_text: str) -> None:
    lowered = doc_text.lower()
    hits = [p for p in BANNED_PHRASES if p in lowered]
    assert not hits, (
        "docs/architecture.md contains pre-#24 drift phrases:\n"
        + "\n".join(f"  - {p!r}" for p in hits)
        + "\n(these phrases described the pre-shipping state; the doc is "
        "now a steady-state reference, not a PR description)"
    )


def test_banned_phrases_hard_pin_set() -> None:
    assert BANNED_PHRASES == (
        "this pr",
        "(unfiled)",
        "to-be-filed",
    )


def test_known_shipped_issues_hard_pin_set() -> None:
    assert KNOWN_SHIPPED_ISSUES == (1, 2, 3, 4, 5, 10)


def test_resolvable_prefixes_hard_pin_set() -> None:
    assert RESOLVABLE_PREFIXES == (
        "prompt_regression/",
        "scripts/",
        "tests/",
        "docs/",
        ".github/",
    )
