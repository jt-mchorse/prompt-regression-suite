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
- ``unreadable`` finding shape (#133): a file matching a snapshot glob
  that can't be *read* — a ``*.yaml`` directory, a ``chmod 000`` file,
  a file that vanishes between the two read seams. Each pinned
  alongside a second finding, because the regression is that the
  unreadable entry used to suppress the whole pass.
- ``empty`` finding shape: directory has zero matching snapshot files.
- Finding-code list derived-lock (#133): ``FINDING_CODES`` vs the emit
  sites (via AST), the module docstring, and the README.
- Missing directory → ``FileNotFoundError`` propagates from the
  library; CLI maps to exit 2.
- ``ValidationReport.to_dict`` shape stability lock.
- CLI: clean dir exits 0 with an ``ok:`` summary; malformed dir exits
  1 with one stderr line per finding; ``--json`` round-trip; missing
  dir exits 2.
- Glob parity: the validator and the runner walk the same file set.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from prompt_regression import load_snapshot, save_snapshot
from prompt_regression import validate as validate_module
from prompt_regression.cli import _SNAPSHOT_GLOBS as RUN_GLOBS
from prompt_regression.validate import (
    _SNAPSHOT_GLOBS as VALIDATE_GLOBS,
)
from prompt_regression.validate import (
    FINDING_CODES,
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


def test_non_utf8_snapshot_is_parse_finding(tmp_path: Path) -> None:
    """#125: a non-UTF-8 snapshot raises UnicodeDecodeError (a ValueError
    subclass, not a YAMLError) at the same read seam. It must route to a
    ``parse`` finding, not escape as a raw traceback."""
    bad = tmp_path / "bad.yml"
    # Latin-1 'é' (0xE9) — an invalid UTF-8 continuation byte.
    bad.write_bytes(b'schema_version: "1"\nprompt_id: t1\nresponse:\n  text: "caf\xe9"\n')
    report = validate_snapshots(tmp_path)
    assert not report.ok
    codes = [f.code for f in report.findings]
    assert codes == ["parse"]


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


def test_unquoted_int_same_version_is_not_a_schema_version_finding(tmp_path: Path) -> None:
    """#75: a hand-authored `schema_version: 1` (unquoted int) is the same
    version as the quoted '1' and must validate clean — not be mis-flagged
    as a schema_version mismatch by the validate path (which loads via
    ``load_snapshot``)."""
    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    save_snapshot(base, tmp_path / "snap.yml")
    data = yaml.safe_load((tmp_path / "snap.yml").read_text(encoding="utf-8"))
    data["schema_version"] = 1  # unquoted int
    (tmp_path / "snap.yml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    report = validate_snapshots(tmp_path)
    assert report.ok
    assert not any(f.code == "schema_version" for f in report.findings)


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


# --- #133: an unreadable file is a finding, not an abort ------------------


def _dup_id_pair(tmp_path: Path) -> None:
    """Two files resolving to the same ``Snapshot.id`` → one ``duplicate_id``
    finding. Used as the *other* finding that must survive alongside an
    unreadable file."""
    base = load_snapshot(EXAMPLES_DIR / "refund_window_v1.yml")
    save_snapshot(base, tmp_path / "good.yml")
    save_snapshot(base, tmp_path / "shadow.yml")


def test_directory_matching_a_snapshot_glob_is_an_unreadable_finding(
    tmp_path: Path,
) -> None:
    """``rglob("*.yaml")`` matches a *directory* whose name ends in
    ``.yaml`` (an exported ``bundle.yaml/`` folder). Opening it raises
    ``IsADirectoryError`` — an ``OSError``, not a ``YAMLError`` — which
    before #133 escaped the collecting loop entirely."""
    _dup_id_pair(tmp_path)
    (tmp_path / "bundle.yaml").mkdir()

    report = validate_snapshots(tmp_path)

    by_code = {f.code: f for f in report.findings}
    assert "unreadable" in by_code, [f.code for f in report.findings]
    assert by_code["unreadable"].path == "bundle.yaml"
    assert "unreadable:" in by_code["unreadable"].reason
    # The regression this test exists for: the *other* finding survives.
    assert "duplicate_id" in by_code, (
        "an unreadable entry must not suppress the rest of the pass; "
        f"got {[f.code for f in report.findings]}"
    )
    assert report.n_files == 3
    assert report.n_valid == 1


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses file permission bits, so chmod 000 stays readable",
)
def test_permission_denied_snapshot_is_an_unreadable_finding(tmp_path: Path) -> None:
    """A ``chmod 000`` snapshot raises ``PermissionError`` at the read
    seam. Sorted first ("aaa_") so the pre-#133 abort happens *before*
    the duplicate-id pair is reached — pinning that the collecting loop
    continues past it rather than merely tolerating a trailing failure."""
    _dup_id_pair(tmp_path)
    locked = tmp_path / "aaa_locked.yml"
    locked.write_text("schema_version: '1'\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        report = validate_snapshots(tmp_path)
    finally:
        locked.chmod(0o644)  # so pytest's tmp_path cleanup can remove it

    codes = sorted(f.code for f in report.findings)
    assert codes == ["duplicate_id", "unreadable"], codes
    assert not report.ok


def test_unreadable_file_deleted_between_the_two_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``load_snapshot`` re-opens the file, so it is a *second* read seam:
    a file that passes ``yaml.safe_load`` can be gone by the time
    ``load_snapshot`` reads it (deleted mid-walk, permissions changed by a
    concurrent sync). That seam routes to ``unreadable`` too."""
    _dup_id_pair(tmp_path)
    victim = tmp_path / "vanishes.yml"
    save_snapshot(load_snapshot(EXAMPLES_DIR / "creative_kite_v1.yml"), victim)

    real_load = validate_module.load_snapshot

    def _load(path: Path):  # type: ignore[no-untyped-def]
        if Path(path).name == "vanishes.yml":
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real_load(path)

    monkeypatch.setattr(validate_module, "load_snapshot", _load)
    report = validate_snapshots(tmp_path)

    by_code = {f.code: f for f in report.findings}
    assert by_code["unreadable"].path == "vanishes.yml"
    assert "duplicate_id" in by_code


def test_cli_unreadable_file_exits_one_with_findings_not_two(tmp_path: Path) -> None:
    """End-to-end: the CLI reports ``unreadable`` as a finding (exit 1)
    instead of collapsing to the directory-level ``failed to walk
    snapshots directory`` abort (exit 2) it used to hit."""
    _dup_id_pair(tmp_path)
    (tmp_path / "bundle.yaml").mkdir()

    result = _run_cli(str(tmp_path))

    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert "failed to walk snapshots directory" not in result.stderr
    assert "[unreadable]" in result.stderr
    assert "[duplicate_id]" in result.stderr
    assert result.stdout.startswith("fail:"), result.stdout


def test_cli_missing_directory_still_exits_two(tmp_path: Path) -> None:
    """The directory-level arm is unchanged: a missing snapshots dir is
    still exit 2, not a finding. Pins that #133 narrowed the ``OSError``
    catch to per-file reads without widening the clean-failure contract."""
    result = _run_cli(str(tmp_path / "nope"))
    assert result.returncode == 2
    assert "snapshots directory not found" in result.stderr


# --- #133: the documented code list is derived, not prose -----------------


def _codes_emitted_by_validate_module() -> set[str]:
    """Every ``ValidationFinding.code`` string literal the module can emit.

    Collected from the AST rather than by grepping prose: the module
    docstring quotes each code in backticks, and a text scan would count
    the documentation as an emit site — making the lock below vacuous.
    """
    src = Path(validate_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    codes: set[str] = set()
    for node in ast.walk(tree):
        # `ValidationFinding(..., code="parse")`
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ValidationFinding"
        ):
            for kw in node.keywords:
                if kw.arg == "code" and isinstance(kw.value, ast.Constant):
                    codes.add(kw.value.value)
        # `code = "schema_version" if ... else "schema"` — assigned, then passed
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "code" for t in node.targets
        ):
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    codes.add(sub.value)
    return codes


def test_finding_codes_matches_what_the_module_can_emit() -> None:
    """``FINDING_CODES`` is the single source of truth, so it must equal
    the set of codes the emit sites actually construct — no documented-but-
    dead code, no emitted-but-undocumented one."""
    assert set(FINDING_CODES) == _codes_emitted_by_validate_module()
    assert len(FINDING_CODES) == len(set(FINDING_CODES)), "duplicate entry"


def test_module_docstring_code_list_is_locked_to_finding_codes() -> None:
    """The docstring's ``- ``code`` — …`` bullet list is derived-locked.
    Before #133 the code list lived in three places (docstring, README,
    emit sites) with nothing tying them together."""
    doc = validate_module.__doc__ or ""
    documented = re.findall(r"^- ``([a-z_]+)``", doc, flags=re.MULTILINE)
    assert documented == list(FINDING_CODES), (documented, FINDING_CODES)


def test_readme_validate_bullet_lists_every_finding_code() -> None:
    """The README's ``codes `a | b | c``` span is the operator-facing copy
    of the same list; lock it to ``FINDING_CODES`` so a new code can't be
    added to the module and documented in only one of the two places."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"codes `([^`]+)`", readme, flags=re.DOTALL)
    assert match is not None, "README no longer documents the validate finding codes"
    listed = [c.strip() for c in match.group(1).split("|")]
    assert listed == list(FINDING_CODES), (listed, FINDING_CODES)
