"""Public-surface tests for ``prompt_regression/__init__.py``.

``prompt_regression`` re-exports symbols from four submodules
(``diff``, ``html_report``, ``io``, ``schema``) via *relative*
``from .X import …`` blocks and declares ``__all__``. The README
quotes three library-use snippets that import 10+ symbols directly
from the top-level package.

No test locks the surface SHAPE — a future submodule rename would
silently drop names without breaking any test. These four orthogonal
axes lock it:

1. ``__all__`` agrees bidirectionally with the AST-parsed
   ``from .X import`` block.
2. Every ``__all__`` entry is bound and non-None.
3. Every README ``from prompt_regression import …`` snippet
   (extracted via regex so adding a snippet auto-covers it) resolves
   against the live package; a guard test asserts the source is
   non-empty.
4. One anchor per submodule (diff / html_report / io / schema)
   survives at the top level.

Same hygiene as the sister snapshots in ``llm-eval-harness`` (#25)
and ``llm-cost-optimizer`` (#23). Orthogonal axis to
``test_regression_demo_snapshot.py`` and ``test_readme_defaults_snapshot.py``
(which lock README text and demo output).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import prompt_regression

_INIT_PATH = Path(prompt_regression.__file__)
_REPO_ROOT = _INIT_PATH.parent.parent
_README = _REPO_ROOT / "README.md"

# Matches `from prompt_regression import X, Y, Z` single-line AND
# parenthesised multi-line forms.
_README_IMPORT_RE = re.compile(
    r"from\s+prompt_regression\s+import\s+(?:\(([^)]+)\)|([^\n]+))",
    re.MULTILINE,
)

# Anchors that prove each submodule's re-exports survived. If a
# submodule moves and __init__.py isn't updated, the anchor goes
# missing.
SUBMODULE_ANCHORS = {
    "diff": "diff_response",
    "html_report": "render_report",
    "io": "load_snapshot",
    "schema": "Snapshot",
}


def _parse_init_relative_imports() -> set[str]:
    """Return the set of names imported into ``__init__.py`` via
    top-level relative ``from .X import (...)`` blocks.

    Unlike the sister snapshots in cost_optimizer / eval_harness, this
    package uses relative imports (level=1), so the filter is on
    ``ImportFrom`` nodes with ``level >= 1`` instead of a module-name
    prefix.
    """
    tree = ast.parse(_INIT_PATH.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level >= 1:
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _readme_top_level_imports() -> list[tuple[int, set[str]]]:
    """Extract every ``from prompt_regression import ...`` snippet."""
    text = _README.read_text(encoding="utf-8")
    snippets: list[tuple[int, set[str]]] = []
    for idx, match in enumerate(_README_IMPORT_RE.finditer(text)):
        names_blob = match.group(1) or match.group(2)
        cleaned = re.sub(r"#.*", "", names_blob)
        names = {n.strip() for n in cleaned.split(",")}
        names = {n for n in names if n and n.isidentifier()}
        if names:
            snippets.append((idx, names))
    return snippets


def test_all_is_non_empty_and_names_bound() -> None:
    """Every name in ``__all__`` must be importable and non-None."""
    assert prompt_regression.__all__, "prompt_regression.__all__ is empty."
    missing: list[str] = []
    none_valued: list[str] = []
    for name in prompt_regression.__all__:
        if not hasattr(prompt_regression, name):
            missing.append(name)
            continue
        if getattr(prompt_regression, name) is None:
            none_valued.append(name)
    assert not missing, (
        f"prompt_regression.__all__ advertises names that are not bound: {missing}. "
        f"A re-import line was probably deleted from __init__.py without "
        f"updating __all__."
    )
    assert not none_valued, f"prompt_regression.__all__ entries bound to None: {none_valued}."


def test_all_matches_actual_top_level_imports() -> None:
    """``__all__`` must equal the set of top-level re-exports."""
    advertised = set(prompt_regression.__all__)
    imported = _parse_init_relative_imports()
    only_imported = imported - advertised
    only_advertised = advertised - imported
    assert not only_imported, (
        f"Names imported into prompt_regression/__init__.py but missing "
        f"from __all__: {sorted(only_imported)}. Add to __all__ or stop "
        f"importing at top level."
    )
    assert not only_advertised, (
        f"Names in prompt_regression.__all__ but not imported at the top "
        f"of __init__.py: {sorted(only_advertised)}."
    )


_README_SNIPPETS = _readme_top_level_imports()


@pytest.mark.parametrize(
    ("snippet_idx", "names"),
    _README_SNIPPETS,
    ids=[f"snippet-{idx}" for idx, _ in _README_SNIPPETS],
)
def test_readme_library_use_snippet_imports_resolve(snippet_idx: int, names: set[str]) -> None:
    """Each README ``from prompt_regression import …`` snippet must
    resolve against the live package surface."""
    missing = sorted(n for n in names if not hasattr(prompt_regression, n))
    assert not missing, (
        f"README library-use snippet #{snippet_idx} imports names that "
        f"are no longer on the top-level surface: {missing}."
    )


def test_readme_has_at_least_one_library_use_snippet() -> None:
    """Loud regression mode when the README drops all library snippets
    or the regex stops matching."""
    assert _README_SNIPPETS, (
        "README contains zero `from prompt_regression import …` snippets. "
        "Either the README dropped its library-use examples or the regex "
        "in this test stopped matching."
    )


@pytest.mark.parametrize(
    ("submodule", "anchor"),
    sorted(SUBMODULE_ANCHORS.items()),
    ids=sorted(SUBMODULE_ANCHORS.keys()),
)
def test_submodule_anchor_re_exported(submodule: str, anchor: str) -> None:
    """One anchor per submodule survives at the top level."""
    assert hasattr(prompt_regression, anchor), (
        f"`{anchor}` from `prompt_regression.{submodule}` is no longer "
        f"re-exported. Did `{submodule}` move or get renamed?"
    )
