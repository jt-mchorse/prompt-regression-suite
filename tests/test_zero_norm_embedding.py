"""A zero-norm stored embedding is a schema error, not a permanent `fail` (#251).

`cosine()` returns 0.0 when either norm is zero, before its identical-vector
check, so a snapshot stored with such a vector failed every diff -- its own
canonical text included -- at cosine 0.0000 and exit 1, while `validate`
reported the file clean. The NaN/Inf component rule's stated reason ("verdict
falls to fail with no diagnostic about the malformed vector") covers it.

The other end of the same norm is here too (#267): finite components whose
squares sum past the float range made `cosine()` score a finite 0.0 against an
ordinary vector, so the file failed its own text while `validate` passed it.

And the range between them (#272): a nonzero sum of squares below the smallest
normal float keeps only a few significant bits, so the file scored ~0.71
against its own text while `validate` passed it.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest
import yaml

from prompt_regression.cli import main
from prompt_regression.diff import HASH_EMBEDDING_DIM, HashEmbedder
from prompt_regression.io import save_snapshot
from prompt_regression.schema import (
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
    SnapshotValidationError,
)
from prompt_regression.validate import validate_snapshots

TEXT = "Pro plan customers get a 14-day refund window from the purchase date."

ZERO = [0.0] * HASH_EMBEDDING_DIM
# Nonzero, but every square underflows to 0.0, so `cosine()` sees a zero norm.
UNDERFLOW = [1e-200] * HASH_EMBEDDING_DIM
# Every component finite, but the squares sum past the float range, so
# `cosine()` sees an infinite norm (#267). Same direction as the real vector.
OVERFLOW = [x * 1e160 for x in HashEmbedder().embed(TEXT)]


def _write(directory: Path, embedding: list[float] | None) -> Path:
    """Save a valid HashEmbedder snapshot, then swap its stored vector on disk."""
    embedder = HashEmbedder()
    snap = Snapshot(
        id="refund",
        prompt=Prompt(model="m", user="u"),
        response_shape=ResponseShape(),
        canonical=CanonicalResponse(
            text=TEXT, embedding=embedder.embed(TEXT), embedding_model=embedder.model_name
        ),
    )
    path = directory / "refund.snapshot.yaml"
    save_snapshot(snap, path)
    if embedding is not None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["canonical"]["embedding"] = embedding
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("embedding", [ZERO, UNDERFLOW], ids=["all-zero", "underflow"])
def test_construction_refuses_a_zero_norm_embedding(embedding: list[float]) -> None:
    with pytest.raises(SnapshotValidationError, match="zero norm"):
        CanonicalResponse(text=TEXT, embedding=embedding, embedding_model="e")


def test_a_tiny_but_representable_vector_still_loads() -> None:
    # Control: 1e-150 squares to 1e-300, a normal float, so the norm is nonzero.
    vec = [0.0] * HASH_EMBEDDING_DIM
    vec[3] = 1e-150
    assert CanonicalResponse(text=TEXT, embedding=vec, embedding_model="e").embedding == vec


@pytest.mark.parametrize("embedding", [ZERO, UNDERFLOW], ids=["all-zero", "underflow"])
def test_validate_reports_a_schema_finding(tmp_path: Path, embedding: list[float]) -> None:
    _write(tmp_path, embedding)
    report = validate_snapshots(tmp_path)
    assert [(f.path, f.code) for f in report.findings] == [("refund.snapshot.yaml", "schema")]
    assert "zero norm" in report.findings[0].reason


def test_diff_against_a_zero_norm_snapshot_is_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, ZERO)
    rc = main(["diff", "--snapshot", str(path), "--candidate", TEXT])
    captured = capsys.readouterr()
    assert rc == 2
    assert "zero norm" in captured.err
    assert "verdict" not in captured.out


def test_run_over_a_zero_norm_snapshot_is_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    _write(snaps, ZERO)
    candidates = tmp_path / "c.jsonl"
    candidates.write_text(json.dumps({"snapshot": "refund", "candidate": TEXT}) + "\n")
    rc = main(["run", "--snapshots", str(snaps), "--candidates", str(candidates)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "zero norm" in captured.err


def test_the_real_vector_still_passes_its_own_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Control: the same file with the embedder's own vector is a clean pass.
    path = _write(tmp_path, None)
    assert main(["diff", "--snapshot", str(path), "--candidate", TEXT]) == 0
    assert "verdict: pass" in capsys.readouterr().out


# ----------------------------------------------------------------------
# The other end of the norm (#267): a sum of squares that overflows.
# ----------------------------------------------------------------------


def test_construction_refuses_an_overflowing_norm() -> None:
    with pytest.raises(SnapshotValidationError, match="norm overflows"):
        CanonicalResponse(text=TEXT, embedding=OVERFLOW, embedding_model="e")


def test_validate_reports_an_overflowing_norm_as_a_schema_finding(tmp_path: Path) -> None:
    _write(tmp_path, OVERFLOW)
    report = validate_snapshots(tmp_path)
    assert [(f.path, f.code) for f in report.findings] == [("refund.snapshot.yaml", "schema")]
    assert "norm overflows" in report.findings[0].reason


def test_diff_against_an_overflowing_norm_snapshot_is_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # It used to be `verdict: fail` at cosine 0.0000 and exit 1 against its own text.
    path = _write(tmp_path, OVERFLOW)
    rc = main(["diff", "--snapshot", str(path), "--candidate", TEXT])
    captured = capsys.readouterr()
    assert rc == 2
    assert "norm overflows" in captured.err
    assert "verdict" not in captured.out


def test_a_large_but_representable_vector_still_passes_its_own_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Control: 1e150 scaling squares to ~1e300, a finite norm, so the file loads
    # and its own text passes before and after #267.
    big = [x * 1e150 for x in HashEmbedder().embed(TEXT)]
    path = _write(tmp_path, big)
    assert main(["diff", "--snapshot", str(path), "--candidate", TEXT]) == 0
    assert "verdict: pass" in capsys.readouterr().out


# ----------------------------------------------------------------------
# Between the two (#272): a sum of squares in the subnormal range.
# ----------------------------------------------------------------------

# Same direction as the real vector; the squares sum to 5.4e-323, nonzero but
# subnormal, and `cosine()` scores it 0.7071 against TEXT's own embedding.
SUBNORMAL = [x * 5.2129e-162 for x in HashEmbedder().embed(TEXT)]


def _one_slot(value: float) -> list[float]:
    vec = [0.0] * HASH_EMBEDDING_DIM
    vec[3] = value
    return vec


def test_the_subnormal_vector_is_the_case_under_test() -> None:
    # Anti-vacuity: the sum is nonzero (so #251's branch does not fire) and
    # finite (so #267's does not), yet below the smallest normal float.
    sum_sq = sum(v * v for v in SUBNORMAL)
    assert 0.0 < sum_sq < sys.float_info.min


def test_construction_refuses_a_subnormal_norm() -> None:
    with pytest.raises(SnapshotValidationError, match="norm underflows"):
        CanonicalResponse(text=TEXT, embedding=SUBNORMAL, embedding_model="e")


def test_construction_refuses_a_norm_one_step_below_the_smallest_normal() -> None:
    # 2**-511 squares to exactly sys.float_info.min; one ulp lower is subnormal.
    below = _one_slot(math.nextafter(2.0**-511, 0.0))
    with pytest.raises(SnapshotValidationError, match="norm underflows"):
        CanonicalResponse(text=TEXT, embedding=below, embedding_model="e")


def test_a_norm_of_exactly_the_smallest_normal_still_loads() -> None:
    # Control: the boundary itself is a normal float, so the file loads.
    at = _one_slot(2.0**-511)
    assert sum(v * v for v in at) == sys.float_info.min
    assert CanonicalResponse(text=TEXT, embedding=at, embedding_model="e").embedding == at


def test_validate_reports_a_subnormal_norm_as_a_schema_finding(tmp_path: Path) -> None:
    _write(tmp_path, SUBNORMAL)
    report = validate_snapshots(tmp_path)
    assert [(f.path, f.code) for f in report.findings] == [("refund.snapshot.yaml", "schema")]
    assert "norm underflows" in report.findings[0].reason


def test_diff_against_a_subnormal_norm_snapshot_is_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # It used to be `verdict: fail` at cosine 0.7071 and exit 1 against its own text.
    path = _write(tmp_path, SUBNORMAL)
    rc = main(["diff", "--snapshot", str(path), "--candidate", TEXT])
    captured = capsys.readouterr()
    assert rc == 2
    assert "norm underflows" in captured.err
    assert "verdict" not in captured.out


def test_a_small_but_normal_norm_still_passes_its_own_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Control: 1e-150 scaling squares to ~1e-300, a normal float, so the file
    # loads and its own text passes before and after #272.
    small = [x * 1e-150 for x in HashEmbedder().embed(TEXT)]
    path = _write(tmp_path, small)
    assert main(["diff", "--snapshot", str(path), "--candidate", TEXT]) == 0
    assert "verdict: pass" in capsys.readouterr().out
