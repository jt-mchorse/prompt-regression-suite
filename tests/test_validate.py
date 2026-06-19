"""Tests for ``validate_snapshots`` + ``prompt-snap validate`` CLI (#49).

Coverage matrix:

- Happy path against the committed ``examples/snapshots/`` directory
  → ``ok=True``, no findings, ``n_valid == n_files``.
- ``parse`` finding shape: a non-mapping YAML and a YAML decode error.
- ``schema_version`` finding shape: a snapshot whose ``schema_version``
  doesn't match the reader's ``SCHEMA_VERSION``.
- ``schema`` finding shape: a snapshot missing a required field
  (anything ``Snapshot.from_dict`` rejects with a non-version error).
- ``duplicate_id`` finding shape: two snapshot files in the same dir
  with the same ``Snapshot.id``; the shadow file is excluded from
  ``n_valid``.
- ``empty`` finding shape: directory has zero matching snapshot files.
- Missing directory → ``FileNotFoundError`` propagates from the
  library; CLI maps to exit 2.
- ``ValidationReport.to_dict`` shape stability lock.
- CLI: clean dir exits 0 with an ``ok:`` summary; malformed dir exits
  1 with one stderr line per finding; ``--json`` round-trip; missing
  dir exits 2.
- Glob parity: the validator and the runner walk the same file set.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from prompt_regression import load_snapshot, save_snapshot
from prompt_regression.cli import _SNAPSHOT_GLOBS as RUN_GLOBS
from prompt_regression.validate import (
    _SNAPSHOT_GLOBS as VALIDATE_GLOBS,
)
from prompt_regression.validate import (
    ValidationFinding,
    ValidationReport,
    validate_snapshots,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples" / "snapshots"


# --- glob parity lock ------------------------------------------------------


def test_validate_globs_match_run_subcommand_globs() -> None:
    """The validator must see the same files the runner sees. If
    the runner's glob set ever extends, the validator's pre-flight
    has to follow — otherwise a "clean" validate could be followed
    by a `run` aborting on a file the validator never looked at."""
    assert set(VALIDATE_GLOBS) == set(RUN_GLOBS), (
        f"validate globs {VALIDATE_GLOBS} drifted from run globs {RUN_GLOBS}"
    )


# --- library: happy path --------------------------------------------------


def test_happy_path_examples_dir_returns_clean_report() -> None:
    """Both committed examples are well-formed; validator returns
    ``ok=True`` with no findings."""
    report = validate_snapshots(EXAMPLES_DIR)
    assert report.ok, f"examples should validate clean; got findings={report.findings}"
    assert report.findings == ()
    assert report.n_files == report.n_valid
    assert report.n_files >= 2, "examples dir should contain at least two snapshots"


# --- library: parse-shape findings ----------------------------------------


def test_non_mapping_top_level_is_parse_finding(tmp_path: Path) -> None:
    """YAML that parses to a list (not a mapping) at the top level
    is a ``parse`` finding, since ``load_snapshot`` requires a
    mapping. The file's relative path is in the finding."""
    bad = tmp_path / "list_top.yml"
    bad.write_text("- not_a_mapping\n", encoding="utf-8")
    report = validate_snapshots(tmp_path)
    assert not report.ok
    assert report.n_files == 1
    assert report.n_valid == 0
    assert len(report.findings) == 1
    assert report.findings[0].code == "parse"
    assert report.findings[0].path == "list_top.yml"


def test_yaml_decode_error_is_parse_finding(tmp_path: Path) -> None:
    """Malformed YAML surfaces as ``parse`` with the YAML library's
    error message; the validator does not abort."""
    bad = tmp_path / "broken.yml"
    bad.write_text("this: : : not valid yaml: [\n", encoding="utf-8")
    report = validate_snapshots(tmp_path)
    assert not report.ok
    codes = [f.code for f in report.findings]
    assert codes == ["parse"]
    assert "invalid YAML" in report.findings[0].reason


# --- library: schema_version + schema findings ----------------------------


def test_schema_version_mismatch_is_its_own_finding_code(tmp_path: Path) -> None:
    """``schema_version`` collisions get their own code so migration
    tooling can route on it without parsing the prose."""
    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    save_snapshot(base, tmp_path / "snap.yml")
    # Mutate the on-disk YAML to declare a future schema_version.
    text = (tmp_path / "snap.yml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    data["schema_version"] = "99.0.0"
    (tmp_path / "snap.yml").write_text(yaml.safe_dump(data), encoding="utf-8")

    report = validate_snapshots(tmp_path)
    assert not report.ok
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.code == "schema_version"
    assert "99.0.0" in finding.reason


def test_schema_missing_required_field_is_schema_finding(tmp_path: Path) -> None:
    """A snapshot missing a required field is a ``schema`` finding
    (not ``schema_version``). Reuses the loader's reason text."""
    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    save_snapshot(base, tmp_path / "snap.yml")
    text = (tmp_path / "snap.yml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    del data["id"]
    (tmp_path / "snap.yml").write_text(yaml.safe_dump(data), encoding="utf-8")

    report = validate_snapshots(tmp_path)
    assert not report.ok
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.code == "schema"


# --- library: duplicate_id finding ----------------------------------------


def test_duplicate_id_across_files_is_finding_and_shadow_excluded(tmp_path: Path) -> None:
    """Two snapshot files with the same ``Snapshot.id`` produce a
    ``duplicate_id`` finding; the shadow file is excluded from
    ``n_valid`` so the count reflects the runner-visible population."""
    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    # Names chosen so sort order matches narrative: a.yml then b.yml.
    save_snapshot(base, tmp_path / "a.yml")
    save_snapshot(base, tmp_path / "b.yml")

    report = validate_snapshots(tmp_path)
    assert not report.ok
    # Two files walked, one valid (first), one flagged.
    assert report.n_files == 2
    assert report.n_valid == 1
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.code == "duplicate_id"
    # The flagged file is the second one (sorted order), and the reason
    # references the first-seen file by name so the operator can find it.
    assert finding.path == "b.yml"
    assert "a.yml" in finding.reason


# --- library: empty directory finding -------------------------------------


def test_empty_directory_surfaces_one_empty_finding(tmp_path: Path) -> None:
    """A directory with no snapshot files produces one ``empty``
    finding (not zero findings + ``ok=False``)."""
    # Drop a non-matching file to ensure rglob doesn't pick up unrelated text.
    (tmp_path / "notes.txt").write_text("ignore me\n", encoding="utf-8")

    report = validate_snapshots(tmp_path)
    assert not report.ok
    assert report.n_files == 0
    assert report.n_valid == 0
    assert len(report.findings) == 1
    assert report.findings[0].code == "empty"


# --- library: missing directory raises ------------------------------------


def test_missing_directory_raises_file_not_found(tmp_path: Path) -> None:
    """The library raises ``FileNotFoundError`` for a missing dir; the
    CLI translates to exit 2. Mirrors ``validate_dataset``'s
    contract."""
    with pytest.raises(FileNotFoundError):
        validate_snapshots(tmp_path / "does_not_exist")


def test_path_pointing_at_file_not_dir_also_raises(tmp_path: Path) -> None:
    """A path that exists as a regular file (not a directory) also
    raises ``FileNotFoundError`` — the contract says directory."""
    f = tmp_path / "single.yml"
    f.write_text("id: x\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        validate_snapshots(f)


# --- library: ValidationReport / Finding shape ----------------------------


def test_report_to_dict_shape_is_stable(tmp_path: Path) -> None:
    """``ValidationReport.to_dict()`` shape is the JSON contract; lock
    it so machine consumers don't break on a stray rename."""
    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    save_snapshot(base, tmp_path / "snap.yml")

    payload = validate_snapshots(tmp_path).to_dict()
    assert set(payload) == {"directory", "ok", "n_files", "n_valid", "findings"}
    assert payload["ok"] is True
    assert payload["n_files"] == 1
    assert payload["findings"] == []


def test_validation_finding_is_hashable_for_set_dedup() -> None:
    """Frozen dataclass → hashable → callers can dedup findings if
    they aggregate across runs."""
    a = ValidationFinding(path="x.yml", reason="bad", code="parse")
    b = ValidationFinding(path="x.yml", reason="bad", code="parse")
    assert {a, b} == {a}


def test_validation_report_is_frozen(tmp_path: Path) -> None:
    """``ValidationReport`` is frozen; once built it's not mutated."""
    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    save_snapshot(base, tmp_path / "snap.yml")
    report = validate_snapshots(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.n_files = 999  # type: ignore[misc]
    assert isinstance(report, ValidationReport)


# --- CLI: end-to-end ------------------------------------------------------


def _run_cli(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "prompt_regression.cli", "validate", *argv],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_clean_examples_dir_exits_zero_with_ok_summary() -> None:
    """Clean examples → exit 0, ``stdout`` starts with ``ok:``."""
    result = _run_cli(str(EXAMPLES_DIR))
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("ok:"), result.stdout


def test_cli_malformed_dir_exits_one_with_findings_on_stderr(tmp_path: Path) -> None:
    """A bad snapshot produces a ``fail:`` stdout summary and per-
    finding stderr lines."""
    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    save_snapshot(base, tmp_path / "good.yml")
    save_snapshot(base, tmp_path / "dup.yml")  # duplicate id

    result = _run_cli(str(tmp_path))
    assert result.returncode == 1, result.stdout
    assert "duplicate_id" in result.stderr
    assert result.stdout.startswith("fail:")


def test_cli_json_flag_emits_report_dict_and_respects_exit_code(tmp_path: Path) -> None:
    """``--json`` emits the ``to_dict`` shape on stdout and the exit
    code still reflects the findings."""
    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    save_snapshot(base, tmp_path / "a.yml")
    save_snapshot(base, tmp_path / "b.yml")  # duplicate id again

    result = _run_cli(str(tmp_path), "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "duplicate_id"


def test_cli_missing_dir_exits_two() -> None:
    """Missing dir → exit 2 (matches ``validate_dataset`` /
    ``audit_phase_a.py``)."""
    result = _run_cli("/this/path/does/not/exist")
    assert result.returncode == 2
    assert "snapshots directory not found" in result.stderr


# --- CLI: --out sink parity (#59) — propagation of llm-eval-harness#66 -----


def test_cli_out_writes_human_summary_to_file_not_stdout(tmp_path: Path) -> None:
    """``--out`` writes the human-readable summary to disk; stdout stays
    silent (parity with llm-eval-harness validate --out #66 and
    chunking-strategies-lab validate --out #45)."""
    out = tmp_path / "report.txt"
    result = _run_cli(str(EXAMPLES_DIR), "--out", str(out))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", f"stdout must be silent when --out is set; got {result.stdout!r}"
    body = out.read_text(encoding="utf-8")
    assert body.startswith("ok:"), body
    assert body.endswith("\n"), "trailing newline required for parity"


def test_cli_out_writes_json_payload_to_file(tmp_path: Path) -> None:
    """``--out`` + ``--json`` writes the report dict as JSON to disk;
    stdout silent; the file parses cleanly and carries the expected shape."""
    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    save_snapshot(base, bad_dir / "a.yml")
    save_snapshot(base, bad_dir / "b.yml")  # duplicate id

    out = tmp_path / "report.json"
    result = _run_cli(str(bad_dir), "--json", "--out", str(out))
    assert result.returncode == 1
    assert result.stdout == ""
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["findings"][0]["code"] == "duplicate_id"


def test_cli_out_creates_parent_dirs(tmp_path: Path) -> None:
    """``atomic_write_text`` does ``parent.mkdir(parents=True)``; confirm
    the validate path inherits that behavior so nested observability
    dirs don't need pre-creation."""
    out = tmp_path / "nested" / "sink" / "report.txt"
    result = _run_cli(str(EXAMPLES_DIR), "--out", str(out))
    assert result.returncode == 0
    assert out.exists()
    assert out.parent.is_dir()


def test_cli_out_overwrites_atomically(tmp_path: Path) -> None:
    """Two successive writes to the same path leave the second payload —
    not the concatenation, not a half-written file. No tempfile leftovers."""
    out = tmp_path / "report.txt"
    _run_cli(str(EXAMPLES_DIR), "--out", str(out))
    body1 = out.read_text(encoding="utf-8")

    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    save_snapshot(base, bad_dir / "a.yml")
    save_snapshot(base, bad_dir / "b.yml")
    _run_cli(str(bad_dir), "--out", str(out))
    body2 = out.read_text(encoding="utf-8")
    assert body1 != body2
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], leftovers
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".report.txt.")]
    assert leftovers == [], leftovers


def test_cli_out_findings_still_print_to_stderr(tmp_path: Path) -> None:
    """``--out`` covers stdout only — stderr stays the operator's
    diagnostic channel so a CI step capturing stdout to a file still sees
    per-finding lines on stderr."""
    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    save_snapshot(base, tmp_path / "a.yml")
    save_snapshot(base, tmp_path / "b.yml")

    out = tmp_path / "report.txt"
    result = _run_cli(str(tmp_path), "--out", str(out))
    assert result.returncode == 1
    assert "duplicate_id" in result.stderr
    assert result.stdout == ""
    body = out.read_text(encoding="utf-8")
    assert body.startswith("fail:"), body


def test_cli_out_not_written_on_missing_dir(tmp_path: Path) -> None:
    """Exit-2 (missing dir) raises before rendering, so ``--out`` must
    NOT touch disk — keeps the failure mode honest (no zero-byte
    sentinel a CI step could mistake for "ran successfully")."""
    out = tmp_path / "report.txt"
    result = _run_cli("/this/path/does/not/exist", "--out", str(out))
    assert result.returncode == 2
    assert not out.exists(), "exit-2 must not create the --out file"
