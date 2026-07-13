"""Architecture-doc lock: catch drift between `docs/architecture.md` and
the actual shipped surface of the repo.

Fourth Python sister of the architecture-doc lock pattern this session
(after `embedding-model-shootout` PR #20, `vector-search-at-scale` PR
#22, `llm-eval-harness` PR #30). Five invariants pinned:

1. Path-token reachability — every backtick-quoted token starting with
   one of `RESOLVABLE_PREFIXES` resolves on disk. Placeholders (`<...>`,
   `{...}`, `*`) are skipped.

2. Closed-feature-issue coverage — every issue in `KNOWN_SHIPPED_ISSUES`
   is referenced at least once.

3. Active-decision coverage — every non-superseded `D-NNN` in
   `MEMORY/core_decisions_ai.md` whose numeric id is
   `>= MIN_ACTIVE_DECISION_ID` is referenced at least once. The next
   `D-NNN` landing without a doc update fails this test loud.

4. Banned-phrase absence — phrases that characterized the pre-#24 drift
   are absent (case-insensitive).

5. Symbol-reference resolution (portfolio-ops #55) — every symbol the
   doc *names* (a `<submodule>.<symbol>` attribute ref or a multi-word
   CamelCase public type) resolves to a real attribute of the
   `prompt_regression` package, one of its submodules, or the Python
   `builtins`. Catches the drift class #55 catalogued portfolio-wide (a
   doc naming a nonexistent type such as llm-cost-optimizer's
   `BatchAPIBackend` stays CI-green). Propagates the
   embedding-model-shootout #71 / python-async #70 / llm-eval-harness
   #140 / chunking-strategies-lab #104 precedents.

Hard-pin tests lock `BANNED_PHRASES`, `KNOWN_SHIPPED_ISSUES`,
`RESOLVABLE_PREFIXES`, `MIN_ACTIVE_DECISION_ID`, `SYMBOL_SKIP_EXTENSIONS`,
and `_SUBPACKAGES` to their exact values so a future loose edit can't
silently weaken the guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "architecture.md"
DECISIONS = REPO_ROOT / "MEMORY" / "core_decisions_ai.md"

# D-001 is the scope baseline (handoff §2) and isn't tied to a shipped
# code surface; it doesn't need to be cited in architecture.md. Every
# active D-NNN with id >= MIN_ACTIVE_DECISION_ID does.
MIN_ACTIVE_DECISION_ID = 2

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
KNOWN_SHIPPED_ISSUES = (1, 2, 3, 4, 5, 10, 47, 49, 51)

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


# Symbol-resolution lock (portfolio-ops #55). The package + its subpackages
# whose attributes count as resolvable doc symbols. `prompt_regression` is a
# flat package (no subpackages today); `_SUBPACKAGES` is kept as an explicit,
# hard-pinned empty tuple so adding one later is a deliberate widening.
_PKG = "prompt_regression"
_PKG_DIR = REPO_ROOT / _PKG
_SUBPACKAGES: tuple[str, ...] = ()

# File-suffix tokens that look like a `<name>.<attr>` symbol reference but are
# really filenames (`cli.py`, `diff.py`). Excluded from the dotted-symbol
# resolution check so a filename isn't mistaken for a submodule attribute.
# Hard-pinned by `test_symbol_skip_extensions_hard_pin_set`.
SYMBOL_SKIP_EXTENSIONS = ("py", "sqlite", "json", "md", "txt", "yaml", "yml", "sh", "toml")


@pytest.fixture(scope="module")
def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def active_decisions() -> tuple[int, ...]:
    """Parse `MEMORY/core_decisions_ai.md` for non-superseded `D-NNN`
    entries whose numeric id is `>= MIN_ACTIVE_DECISION_ID`.
    """
    text = DECISIONS.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=- id:)", text)
    active: list[int] = []
    for block in blocks:
        id_match = re.search(r"- id:\s*D-(\d+)", block)
        if not id_match:
            continue
        sup_match = re.search(r"superseded_by:\s*(\S+)", block)
        is_active = (sup_match is None) or (sup_match.group(1).strip().lower() == "null")
        if is_active:
            n = int(id_match.group(1))
            if n >= MIN_ACTIVE_DECISION_ID:
                active.append(n)
    return tuple(sorted(active))


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


def _package_symbol_resolves(name: str) -> bool:
    """True if `name` is an attribute of the `prompt_regression` package, any of
    its `*.py` submodules, a listed subpackage, or the Python `builtins`.

    Submodule coverage is load-bearing: `ValidationFinding` lives in
    `prompt_regression.validate` and is not re-exported at package level, so a
    surface-only check would false-positive on it. Builtins are included so a
    doc that legitimately names `ValueError` / `KeyboardInterrupt` in its
    error-handling narrative resolves without a hand-maintained allow-list that
    rots.
    """
    import builtins
    import importlib

    if hasattr(builtins, name):
        return True
    pkg = importlib.import_module(_PKG)
    if hasattr(pkg, name):
        return True
    module_names = [f"{_PKG}.{p.stem}" for p in _PKG_DIR.glob("*.py") if p.stem != "__init__"]
    module_names += [f"{_PKG}.{sub}" for sub in _SUBPACKAGES]
    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        if hasattr(module, name):
            return True
    return False


def _extract_symbol_refs(text: str) -> tuple[set[str], set[str]]:
    """Split backtick-quoted tokens into the two symbol-citation styles the doc
    uses, so the resolver only checks genuine symbol claims. Returns
    ``(dotted, camel)``.

    - ``dotted``: ``<submodule>.<symbol>`` where ``<submodule>`` is a real
      ``prompt_regression/*.py`` module stem and the token is not a filename
      (dropped via ``SYMBOL_SKIP_EXTENSIONS``). Package-qualified refs
      (``prompt_regression.stats``) and stdlib refs (``dataclasses.asdict``)
      are skipped: their prefix is not a submodule stem.
    - ``camel``: a *multi-word* CamelCase identifier (an internal
      lowercase->uppercase boundary, e.g. ``CanonicalResponse``,
      ``ToleranceDistribution``). Single-word capitalized tokens (``Prompt``,
      ``Snapshot``, ``Embedder``) are deliberately excluded: they collide with
      prose and would false-positive. Bare snake_case is not locked.
    """
    submodules = {p.stem for p in _PKG_DIR.glob("*.py") if p.stem != "__init__"}
    dotted: set[str] = set()
    camel: set[str] = set()
    for match in re.finditer(r"`([^`\n]+)`", text):
        token = match.group(1).strip()
        token = re.sub(r"\(\)$", "", token)
        while token and token[-1] in ".,;:":
            token = token[:-1]
        dotted_match = re.fullmatch(r"([a-z_]+)\.([A-Za-z_][A-Za-z0-9_]*)", token)
        if dotted_match:
            module, attr = dotted_match.group(1), dotted_match.group(2)
            if module in submodules and attr not in SYMBOL_SKIP_EXTENSIONS:
                dotted.add(token)
            continue
        if re.fullmatch(r"[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*", token) and re.search(
            r"[a-z][A-Z]", token
        ):
            camel.add(token)
    return dotted, camel


def test_doc_exists() -> None:
    assert DOC.exists(), f"missing {DOC}"


def test_decisions_file_exists() -> None:
    assert DECISIONS.exists(), f"missing {DECISIONS}"


def test_backtick_paths_resolve_on_disk(doc_text: str) -> None:
    tokens = _extract_backtick_paths(doc_text)
    unresolved = sorted(t for t in tokens if not _resolves_on_disk(t))
    assert not unresolved, (
        "docs/architecture.md quotes paths that don't exist on disk:\n"
        + "\n".join(f"  - `{t}`" for t in unresolved)
        + "\n(regenerate the doc to match the current layout, or fix the typo)"
    )


def test_doc_symbol_refs_resolve(doc_text: str) -> None:
    """Every symbol the doc names resolves to a real attribute (portfolio-ops #55).

    ``test_backtick_paths_resolve_on_disk`` validates slash-path tokens only; a
    *symbol* reference -- a ``<submodule>.<symbol>`` attribute or a multi-word
    CamelCase public type -- was unguarded. That is exactly the drift class #55
    catalogued (a doc naming a nonexistent ``BatchAPIBackend`` /
    ``compute_frontier`` stays CI-green). Inverse-verified by
    ``test_symbol_resolver_flags_injected_drift``.
    """
    import importlib

    dotted, camel = _extract_symbol_refs(doc_text)
    assert dotted or camel, (
        "expected at least one symbol reference (`<submodule>.<symbol>` or a "
        "multi-word CamelCase type) in docs/architecture.md -- the resolver "
        "would otherwise be vacuously green"
    )

    unresolved: list[str] = []
    for token in sorted(dotted):
        module_name, _, symbol = token.rpartition(".")
        try:
            module = importlib.import_module(f"{_PKG}.{module_name}")
        except ModuleNotFoundError:
            unresolved.append(f"{token} (module {_PKG}.{module_name} not importable)")
            continue
        if not hasattr(module, symbol):
            unresolved.append(token)
    for token in sorted(camel):
        if not _package_symbol_resolves(token):
            unresolved.append(f"{token} (not a prompt_regression symbol or a builtin)")

    assert not unresolved, (
        "docs/architecture.md names symbols that don't exist in the package:\n"
        + "\n".join(f"  - {u}" for u in unresolved)
        + "\n(fix the doc to match the shipped symbol, or update the rename that "
        "orphaned it)"
    )


def test_symbol_resolver_flags_injected_drift() -> None:
    """Inverse safety net: a nonexistent CamelCase type in doc text is flagged.

    Guards against a vacuously-green resolver -- if a refactor ever neutered
    extraction or resolution, this fails. Mirrors the #55 drift shape while a
    real symbol in the same string still resolves.
    """
    fake = "The `NonexistentDiffChannel` produces a `ToleranceDistribution`."
    dotted, camel = _extract_symbol_refs(fake)
    assert "NonexistentDiffChannel" in camel
    assert "ToleranceDistribution" in camel
    unresolved = sorted(t for t in camel if not _package_symbol_resolves(t))
    assert unresolved == ["NonexistentDiffChannel"]


def test_symbol_skip_extensions_hard_pin_set() -> None:
    assert SYMBOL_SKIP_EXTENSIONS == (
        "py",
        "sqlite",
        "json",
        "md",
        "txt",
        "yaml",
        "yml",
        "sh",
        "toml",
    )


def test_symbol_subpackages_hard_pin_set() -> None:
    assert _SUBPACKAGES == ()


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


def test_every_active_decision_referenced(doc_text: str, active_decisions: tuple[int, ...]) -> None:
    referenced = {int(m.group(1)) for m in re.finditer(r"\bD-0*(\d+)\b", doc_text)}
    missing = sorted(set(active_decisions) - referenced)
    assert not missing, (
        "docs/architecture.md doesn't reference these active "
        "(non-superseded) core decisions even once:\n"
        + "\n".join(f"  - D-{n:03d}" for n in missing)
        + "\n(every shipped layer / posture in MEMORY/core_decisions_ai.md "
        "should be annotated in the doc where the relevant code lives; "
        "add a `D-NNN` reference to the relevant bullet)"
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
    assert KNOWN_SHIPPED_ISSUES == (1, 2, 3, 4, 5, 10, 47, 49, 51)


def test_resolvable_prefixes_hard_pin_set() -> None:
    assert RESOLVABLE_PREFIXES == (
        "prompt_regression/",
        "scripts/",
        "tests/",
        "docs/",
        ".github/",
    )


def test_min_active_decision_id_hard_pin() -> None:
    assert MIN_ACTIVE_DECISION_ID == 2


# ---------------------------------------------------------------------------
# Directory-tree completeness lock (#123).
#
# The doc opens with a fenced `prompt_regression/` directory tree annotating
# each module. Its bare `foo.py` entries are neither backtick-quoted path tokens
# nor dotted `<module>.<symbol>` refs, so the resolvers above skip them, and
# nothing asserted the tree matches the package. That is how `stats.py` (#47)
# and `validate.py` (#49) shipped and stayed out of the tree even though the
# doc's prose describes both — so a "basename appears anywhere in the doc" check
# would pass. Parse the tree block itself and assert its `*.py` entries EQUAL
# the package module set (bidirectional: omission and stale-leftover both fail).


def _tree_py_modules(doc_text: str) -> set[str]:
    """Basenames of the `*.py` entries in the fenced directory tree that opens
    with the `prompt_regression/` header line (scan stops at the closing fence)."""
    modules: set[str] = set()
    in_tree = False
    for line in doc_text.splitlines():
        if line.strip() == f"{_PKG}/":
            in_tree = True
            continue
        if in_tree:
            if line.strip().startswith("```"):
                break
            m = re.search(r"([A-Za-z_][A-Za-z0-9_]*\.py)\b", line)
            if m:
                modules.add(m.group(1))
    return modules


def test_directory_tree_lists_every_package_module(doc_text: str) -> None:
    """The fenced `prompt_regression/` tree names exactly the package's `*.py`
    modules — no omission (the #47/#49 drift) and no stale leftover (#123)."""
    tree = _tree_py_modules(doc_text)
    assert tree, f"expected a `{_PKG}/` directory tree with *.py entries in the doc"
    disk = {p.name for p in _PKG_DIR.glob("*.py")}
    missing = sorted(disk - tree)
    extra = sorted(tree - disk)
    drift = [
        *(f"missing from tree: {m}" for m in missing),
        *(f"in tree but not on disk: {e}" for e in extra),
    ]
    assert not drift, (
        f"docs/architecture.md directory tree is out of sync with {_PKG}/:\n"
        + "\n".join(f"  {d}" for d in drift)
        + "\n(update the tree so it depicts the current package layout)"
    )


def test_directory_tree_parser_and_diff_catch_drift() -> None:
    """Inverse safety net: exercise the real parser + set-diff on synthetic
    trees so a vacuous parse can't let drift through."""
    good = f"{_PKG}/\n├── a.py   ← one\n└── b.py   ← two\n```"
    assert _tree_py_modules(good) == {"a.py", "b.py"}
    # A module on disk but absent from the tree is flagged as missing.
    assert sorted({"a.py", "b.py", "c.py"} - _tree_py_modules(good)) == ["c.py"]
    # A stale entry lingering in the tree after a file is deleted is flagged.
    stale = f"{_PKG}/\n├── a.py\n├── b.py\n└── gone.py\n```"
    assert sorted(_tree_py_modules(stale) - {"a.py", "b.py"}) == ["gone.py"]
