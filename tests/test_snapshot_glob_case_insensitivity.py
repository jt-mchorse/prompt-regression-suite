"""A snapshot file must not be skipped because its extension isn't lowercase.

`iter_snapshot_paths` used `root.rglob(pattern)` per pattern, and `pathlib`'s
glob is case-sensitive on every platform — so a snapshot named `foo.YAML` was
invisible to the entire suite. All three consumers share this walker
(`validate`, `stats`, and `cli._run_command`, the regression check itself), so
such a file was not merely unvalidated, it was never *run*, and the `run`
summary's `total=` counts only what was walked, leaving nothing to notice the
gap against (#144).

`SNAPSHOT_GLOBS` remains the single definition of what a snapshot file is —
#135 consolidated it into `io` after three modules had drifted, so matching is
done against it rather than by re-listing extensions with case variants.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from prompt_regression.io import SNAPSHOT_GLOBS, iter_snapshot_paths
from prompt_regression.stats import collect_stats
from prompt_regression.validate import validate_snapshots

BASE = {
    "id": "s0",
    "schema_version": "1",
    "created_at": "2026-01-01T00:00:00Z",
    "prompt": {
        "model": "m",
        "user": "hi",
        "system": None,
        "temperature": None,
        "max_tokens": None,
        "extra": {},
    },
    "response_shape": {"semantic_categories": ["greeting"], "structured_slots": {}},
    "canonical": {"text": "hello", "embedding": [0.1, 0.2], "embedding_model": "hash-64"},
    "notes": None,
    "tolerance": None,
}

# The measured table from the issue. Before the fix, `found` was 4 of 7 and
# `validate_snapshots` reported the directory CLEAN.
MIXED_CASE_NAMES = [
    "one.snapshot.yaml",
    "two.snapshot.yaml",
    "three.snapshot.YAML",
    "four.SNAPSHOT.yaml",
    "five.Yml",
    "six.yaml",
    "seven.YML",
]

NOT_SNAPSHOTS = ["ignore.txt", "notes.md", "data.json", "almost.yamll"]


def _write(dirpath: Path, name: str, snapshot_id: str) -> Path:
    body = copy.deepcopy(BASE)
    body["id"] = snapshot_id
    path = dirpath / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return path


def _populate(dirpath: Path) -> None:
    for i, name in enumerate(MIXED_CASE_NAMES):
        _write(dirpath, name, f"s{i}")
    for name in NOT_SNAPSHOTS:
        (dirpath / name).write_text("not a snapshot", encoding="utf-8")


def test_every_mixed_case_snapshot_is_walked(tmp_path: Path) -> None:
    _populate(tmp_path)
    found = {p.name for p in iter_snapshot_paths(tmp_path)}
    assert found == set(MIXED_CASE_NAMES), sorted(set(MIXED_CASE_NAMES) - found)


@pytest.mark.parametrize("name", MIXED_CASE_NAMES)
def test_each_extension_spelling_is_matched_individually(tmp_path: Path, name: str) -> None:
    """One file per directory, so a pass can't be carried by its neighbours."""
    _write(tmp_path, name, "solo")
    assert [p.name for p in iter_snapshot_paths(tmp_path)] == [name]


@pytest.mark.parametrize("name", NOT_SNAPSHOTS)
def test_non_snapshot_files_are_still_excluded(tmp_path: Path, name: str) -> None:
    """Case-insensitivity must not turn into matching everything.

    `almost.yamll` is the interesting one: it contains `.yaml` as a substring,
    so a fix that reached for `in` rather than a glob would wrongly accept it.
    """
    (tmp_path / name).write_text("x", encoding="utf-8")
    assert iter_snapshot_paths(tmp_path) == []


def test_validate_no_longer_reports_a_partially_walked_directory_as_clean(
    tmp_path: Path,
) -> None:
    """The headline symptom: 3 of 7 unchecked and the suite called CLEAN.

    Each file carries a distinct id, so a clean report here means all seven were
    actually loaded — `duplicate_id` would fire otherwise.
    """
    _populate(tmp_path)
    report = validate_snapshots(tmp_path)
    assert list(report.findings) == []
    assert len(iter_snapshot_paths(tmp_path)) == 7


def test_stats_sees_all_seven(tmp_path: Path) -> None:
    """`stats` shares the walker, so it under-counted the same way."""
    _populate(tmp_path)
    report = collect_stats(tmp_path)
    assert report.n_snapshots == 7


def test_run_command_sees_all_seven(tmp_path: Path) -> None:
    """The one that matters most: `run` is the regression check itself.

    Assert on the number of rows the run *emitted*, not on its verdict: the
    verdict depends on the embedder and is not what this test is about. Before
    the fix `run` emitted four rows for these seven files, and its summary's
    `total` counted only those four — so there was nothing for an operator to
    notice the gap against.
    """
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    for i, name in enumerate(MIXED_CASE_NAMES):
        _write(snaps, name, f"s{i}")

    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text(
        "\n".join(
            json.dumps({"snapshot": f"s{i}", "candidate": BASE["canonical"]["text"]})
            for i in range(len(MIXED_CASE_NAMES))
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "prompt_regression.cli",
            "run",
            "--snapshots",
            str(snaps),
            "--candidates",
            str(candidates),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    combined = result.stdout + result.stderr
    assert "no snapshot files" not in combined, combined
    payload = json.loads(result.stdout)
    assert len(payload["rows"]) == len(MIXED_CASE_NAMES), payload


# ----------------------------------------------------------------------
# Properties the fix could plausibly have broken
# ----------------------------------------------------------------------


def test_a_file_matching_several_patterns_is_yielded_once(tmp_path: Path) -> None:
    """`*.yml` also matches `*.snapshot.yml` — the overlap is by design."""
    _write(tmp_path, "dup.snapshot.yml", "only")
    assert len(iter_snapshot_paths(tmp_path)) == 1


def test_result_is_sorted(tmp_path: Path) -> None:
    for i, name in enumerate(["z.yaml", "a.yaml", "m.snapshot.yaml"]):
        _write(tmp_path, name, f"id{i}")
    paths = iter_snapshot_paths(tmp_path)
    assert paths == sorted(paths)


def test_nested_directories_are_still_walked(tmp_path: Path) -> None:
    _write(tmp_path, "top.yaml", "a")
    _write(tmp_path, "sub/deep.SNAPSHOT.YAML", "b")
    assert {p.name for p in iter_snapshot_paths(tmp_path)} == {"top.yaml", "deep.SNAPSHOT.YAML"}


def test_a_directory_matching_a_glob_is_still_yielded(tmp_path: Path) -> None:
    """#133 made a directory named like a snapshot surface as an `unreadable`
    finding rather than aborting the walk. Filtering to `is_file()` here would
    make it vanish silently — the very class this change fixes, reintroduced.
    """
    (tmp_path / "bundle.yaml").mkdir()
    assert [p.name for p in iter_snapshot_paths(tmp_path)] == ["bundle.yaml"]

    report = validate_snapshots(tmp_path)
    assert "unreadable" in {f.code for f in report.findings}


def test_snapshot_globs_is_still_the_single_definition() -> None:
    """Guards against the fix re-forking the patterns with case variants."""
    assert SNAPSHOT_GLOBS == ("*.snapshot.yaml", "*.snapshot.yml", "*.yml", "*.yaml")
    assert all(g == g.lower() for g in SNAPSHOT_GLOBS)


def test_empty_directory_still_reports_empty(tmp_path: Path) -> None:
    assert iter_snapshot_paths(tmp_path) == []
    report = validate_snapshots(tmp_path)
    assert "empty" in {f.code for f in report.findings}
