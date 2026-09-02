"""Both of `validate_snapshots`' read seams answer identically (#157).

`validate_snapshots` reads each snapshot file **twice**: once inline with
`yaml.safe_load`, then again through `load_snapshot`, which re-opens it. The
second guard's own comment already said why that is not redundant --

    `load_snapshot` re-opens the file, so this is a second read seam, not a
    redundant guard: the file can become unreadable between the two opens
    (deleted mid-walk, permissions changed by a concurrent sync).

-- and that reason covers every way a read can fail, while the guard under it
caught `OSError` alone. The first seam handled all three modes. Measured: a file
rewritten between the two opens escaped `validate_snapshots` entirely::

    control    -> 1 valid, no findings
    bad-utf8   -> ESCAPED as UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff
    bad-yaml   -> ESCAPED as ParserError: while parsing a flow sequence

That matters more here than at the four `load_snapshot` sites in `cli.py`, which
all catch the full tuple and abort at exit 2 -- aborting is *their* contract.
`validate` is the collecting command, the one whose docstring promises "one
`ValidationFinding` per malformed file" and which `stats` points operators at by
name. `_validate_command` catches only `FileNotFoundError`/`OSError`, so the
escape reached `main()` unhandled: a traceback, at exit 1, which this command
documents as *findings*.

The tests below drive **both seams through one table**, because two seams that
must agree are exactly what a per-seam test suite stops noticing. The
second-seam cases reproduce the concurrent writer the guard's comment names:
the file is rewritten between the two opens and the **real** `load_snapshot`
reads the **real** corrupted bytes, so only the writer's timing is simulated.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

import prompt_regression.validate as validate_module
from prompt_regression.io import load_snapshot as real_load_snapshot
from prompt_regression.validate import READ_FAILURE_CODES, READ_FAILURES, validate_snapshots

_EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "snapshots"


def _valid_snapshot_source() -> Path:
    candidates = sorted(_EXAMPLES.glob("*.y*ml"))
    assert candidates, f"no example snapshot under {_EXAMPLES}"
    return candidates[0]


@pytest.fixture
def snapshot_dir(tmp_path: Path) -> Path:
    """A directory holding exactly one snapshot that validates clean."""
    src = _valid_snapshot_source()
    shutil.copy(src, tmp_path / src.name)
    report = validate_snapshots(tmp_path)
    assert report.findings == (), f"control snapshot is not clean: {report.findings}"
    assert report.n_valid == 1
    return tmp_path


# (label, corrupt(path) -> None, expected finding code). One table, applied at
# both seams. A fourth read-failure mode belongs here once, not twice.
def _write_bad_utf8(path: Path) -> None:
    path.write_bytes(b"id: \xff\xfe not utf-8\n")


def _write_bad_yaml(path: Path) -> None:
    path.write_text("id: [unclosed\n", encoding="utf-8")


def _make_unreadable(path: Path) -> None:
    path.unlink()
    path.mkdir()  # the globs match a directory; opening one is an OSError


READ_FAILURE_CASES: list[tuple[str, Callable[[Path], None], str]] = [
    ("invalid utf-8", _write_bad_utf8, "parse"),
    ("invalid yaml", _write_bad_yaml, "parse"),
    ("unreadable", _make_unreadable, "unreadable"),
]

_IDS = [label for label, _, _ in READ_FAILURE_CASES]


@pytest.mark.parametrize(("label", "corrupt", "code"), READ_FAILURE_CASES, ids=_IDS)
def test_first_seam_collects(
    snapshot_dir: Path, label: str, corrupt: Callable[[Path], None], code: str
) -> None:
    """The file is already broken when the walk reaches it."""
    target = next(iter(snapshot_dir.iterdir()))
    corrupt(target)
    report = validate_snapshots(snapshot_dir)
    assert [f.code for f in report.findings] == [code], report.findings
    assert report.n_valid == 0


@pytest.mark.parametrize(("label", "corrupt", "code"), READ_FAILURE_CASES, ids=_IDS)
def test_second_seam_collects_the_same(
    snapshot_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    corrupt: Callable[[Path], None],
    code: str,
) -> None:
    """The file breaks *between* the two opens — the case the guard names.

    The wrapper only supplies the concurrent writer's timing: it corrupts the
    file on disk and then calls the genuine `load_snapshot`, which does a real
    read of the real bytes and raises for real.
    """

    def corrupting_load(path: Any) -> Any:
        corrupt(Path(path))
        return real_load_snapshot(path)

    monkeypatch.setattr(validate_module, "load_snapshot", corrupting_load)
    report = validate_snapshots(snapshot_dir)
    assert [f.code for f in report.findings] == [code], report.findings
    assert report.n_valid == 0


@pytest.mark.parametrize(("label", "corrupt", "code"), READ_FAILURE_CASES, ids=_IDS)
def test_the_two_seams_agree_on_the_reason_text_too(
    snapshot_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    corrupt: Callable[[Path], None],
    code: str,
) -> None:
    """Not just the code: the prose prefix an operator reads must match.

    Codes agreeing while one seam says "invalid YAML" and the other says
    "unreadable" for the same failure would be a subtler version of the same
    divergence.
    """
    target = next(iter(snapshot_dir.iterdir()))
    corrupt(target)
    first = validate_snapshots(snapshot_dir).findings[0]

    src = _valid_snapshot_source()
    shutil.rmtree(snapshot_dir)
    snapshot_dir.mkdir()
    shutil.copy(src, snapshot_dir / src.name)

    def corrupting_load(path: Any) -> Any:
        corrupt(Path(path))
        return real_load_snapshot(path)

    monkeypatch.setattr(validate_module, "load_snapshot", corrupting_load)
    second = validate_snapshots(snapshot_dir).findings[0]

    prefix = lambda reason: reason.split(":", 1)[0]  # noqa: E731
    assert prefix(first.reason) == prefix(second.reason), (first.reason, second.reason)
    assert first.path == second.path


def test_the_case_table_covers_every_declared_read_failure() -> None:
    """Anti-vacuous, and the reason the table is shared.

    Every exception class in `READ_FAILURE_CODES` must have a case here, or the
    parity above is asserted over a subset — which is the shape #157 was. Stated
    against the module's own table rather than a literal count, so adding a
    fourth mode to the table without a case fails here.
    """
    covered_codes = {code for _, _, code in READ_FAILURE_CASES}
    declared_codes = {code for _, code, _ in READ_FAILURE_CODES}
    assert covered_codes == declared_codes, (covered_codes, declared_codes)
    # And one case per declared exception class, not merely per code — `parse`
    # is produced by two different classes and both must be exercised.
    assert len(READ_FAILURE_CASES) >= len(READ_FAILURE_CODES)


def test_the_declared_classes_are_what_the_seams_actually_except() -> None:
    """`READ_FAILURES` is derived from `READ_FAILURE_CODES`, not restated."""
    assert tuple(exc for exc, _, _ in READ_FAILURE_CODES) == READ_FAILURES
    # `UnicodeDecodeError` is a `ValueError`, not an `OSError`. If that ever
    # stops being true the classifier's ordering becomes load-bearing, and this
    # is where that shows up.
    assert not issubclass(UnicodeDecodeError, OSError)
    assert issubclass(UnicodeDecodeError, ValueError)
    assert not issubclass(yaml.YAMLError, OSError)


def test_schema_validation_error_is_not_treated_as_a_read_failure(
    snapshot_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The #155 routing is untouched: schema errors carry their own code.

    `SnapshotValidationError` is deliberately absent from `READ_FAILURE_CODES` —
    it is not a read failure, it only arises at the second seam, and its code
    comes off the exception rather than from the class. A schema-version
    mismatch must still land as `schema_version`, not as `parse`.
    """
    target = next(iter(snapshot_dir.iterdir()))
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    data["schema_version"] = "999"
    target.write_text(yaml.safe_dump(data), encoding="utf-8")

    report = validate_snapshots(snapshot_dir)
    assert [f.code for f in report.findings] == ["schema_version"], report.findings


@pytest.mark.parametrize(("label", "corrupt", "code"), READ_FAILURE_CASES, ids=_IDS)
def test_the_cli_reports_findings_rather_than_raising(
    snapshot_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    label: str,
    corrupt: Callable[[Path], None],
    code: str,
) -> None:
    """End to end: exit 1 *with* findings, not exit 1 with a traceback.

    `_validate_command` catches only `FileNotFoundError` and `OSError`, so an
    escaping `UnicodeDecodeError`/`YAMLError` reached `main()` unhandled — a
    traceback, and an exit code this command documents as "findings". A CI
    consumer chaining validators reads exit 1 as "problems found" and gets a
    stack trace and zero findings.
    """
    from prompt_regression.cli import main

    def corrupting_load(path: Any) -> Any:
        corrupt(Path(path))
        return real_load_snapshot(path)

    monkeypatch.setattr(validate_module, "load_snapshot", corrupting_load)
    rc = main(["validate", str(snapshot_dir)])
    captured = capsys.readouterr()
    assert rc == 1, captured
    assert code in captured.err, captured.err
