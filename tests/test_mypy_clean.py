"""Type-checking gate for ``prompt_regression`` (#146, D-009).

The in-repo half of the contract: it runs the configured ``mypy`` gate over the
package and asserts it exits clean, so an annotation that drifts out of shape
fails a *test* — not only the (separately wired) CI ``mypy`` step.

The rationale is deliberately not the one two of the three sibling repos give.
``llm-eval-harness`` (D-016) and ``llm-cost-optimizer`` (D-014) justify their
gate by shipping a ``py.typed`` marker, so their annotations are visible to
downstream type-checkers and drift breaks a consumer. ``prompt_regression``
ships no marker. The case here is the **latent green** one, and #146 is the
evidence rather than the hypothesis: six errors sat on a green ``main`` until
someone ran ``mypy`` by hand while working an unrelated issue.

``mypy`` is invoked with **no arguments** so it reads exactly the
``[tool.mypy]`` block in ``pyproject.toml``. That keeps this test, the CI step,
and a developer's bare ``mypy`` checking the same thing; a test that passed its
own file list would be testing a scope nothing else uses.

Skipped (not failed) when mypy isn't importable, so a minimal environment
without the ``dev`` extra can still run the rest of the suite; CI installs
``.[dev]`` so the gate is always exercised there.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_mypy() -> subprocess.CompletedProcess[str]:
    pytest.importorskip("mypy", reason="mypy not installed (dev extra); CI installs it")
    return subprocess.run(
        [sys.executable, "-m", "mypy"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _mypy_config() -> dict:
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["mypy"]


def test_mypy_reports_no_issues() -> None:
    proc = _run_mypy()
    assert proc.returncode == 0, (
        "mypy gate failed — an annotation in prompt_regression drifted from "
        "the code. Output:\n" + proc.stdout + proc.stderr
    )


def test_the_gate_actually_checks_source_files() -> None:
    """Anti-vacuous: a clean exit means nothing if nothing was checked.

    ``files = []`` would make ``test_mypy_reports_no_issues`` pass while
    checking zero files. Parse the count mypy prints and require more than one.
    """
    proc = _run_mypy()
    match = re.search(r"no issues found in (\d+) source file", proc.stdout)
    assert match is not None, f"unexpected mypy output: {proc.stdout!r}"
    assert int(match.group(1)) > 1, (
        f"mypy checked only {match.group(1)} source file(s) — the gate is "
        "effectively vacuous. Check `files` in [tool.mypy]."
    )


def test_mypy_config_is_scoped_to_the_package() -> None:
    cfg = _mypy_config()
    assert cfg["files"] == ["prompt_regression"]
    assert (_REPO_ROOT / "prompt_regression").is_dir()


def test_no_blanket_ignore_missing_imports() -> None:
    """The four `yaml` errors in #146 were *stubless imports*, not typos.

    A top-level `ignore_missing_imports` would have silenced them — and would
    silence a genuine typo just as effectively. `types-PyYAML` in the `dev`
    extra is the honest fix: the import is real and resolvable, only its types
    were missing.
    """
    cfg = _mypy_config()
    assert "ignore_missing_imports" not in cfg
    assert "overrides" not in cfg, (
        "no per-module override should be needed — every third-party import in "
        "this package has real stubs available"
    )


def test_yaml_stubs_are_a_declared_dev_dependency() -> None:
    """Four of #146's six errors came back the moment the stubs were absent, so
    the gate is only reproducible if the stub package is declared — not merely
    present in whoever's virtualenv happened to run it first."""
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = config["project"]["optional-dependencies"]["dev"]
    assert any(d.lower().startswith("types-pyyaml") for d in dev), dev
    assert any(d.lower().startswith("mypy") for d in dev), dev


def test_ci_lint_job_runs_the_gate() -> None:
    """The test and the CI step must both exist — either alone is a gate that
    can be bypassed by running the other."""
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    workflow = yaml.safe_load(
        (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    runs = [
        step.get("run", "") for step in workflow["jobs"]["lint"]["steps"] if isinstance(step, dict)
    ]
    assert any(r.strip() == "mypy" for r in runs), (
        f"the CI lint job does not run `mypy`; steps were {runs!r}"
    )
