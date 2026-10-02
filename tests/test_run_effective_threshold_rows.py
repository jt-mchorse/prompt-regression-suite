"""`run` publishes the threshold in force on every row, and refuses a warn band
no snapshot can pass (#187).

Measured on `9b6346e` against copies of `examples/snapshots`:

    run --warn-band 5   -> one `error` row per snapshot, exit 1 ("regressions found")
    diff --warn-band 0.9 -> error: ..., exit 2

    run --format json:  kite-skip  skipped  threshold 0.85   (its own tolerance: 0.75)
                        refund-..  error    threshold 0.85

The README says `threshold` carries "the *effective* threshold so HTML reports
and PR comments always show the number that was actually applied". Pass/fail
rows did; the three hand-built row dicts in `run` used `args.threshold`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from prompt_regression.cli import main

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _snapshots(tmp_path: Path) -> Path:
    d = tmp_path / "snaps"
    shutil.copytree(_EXAMPLES / "snapshots", d)
    return d


def _variant(snaps: Path, name: str, **changes: object) -> None:
    data = yaml.safe_load((snaps / "creative_kite_v1.yml").read_text(encoding="utf-8"))
    data.update(changes)
    (snaps / name).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _run_json(snaps: Path, *extra: str) -> tuple[int, list[dict]]:
    import io
    from contextlib import redirect_stdout

    out = io.StringIO()
    with redirect_stdout(out):
        rc = main(
            [
                "run",
                "--snapshots",
                str(snaps),
                "--candidates",
                str(_EXAMPLES / "candidates.jsonl"),
                "--format",
                "json",
                *extra,
            ]
        )
    return rc, json.loads(out.getvalue())["rows"]


# ----------------------------------------------------------------------
# 1. A warn band at or above 1 is an operator error, in both commands
# ----------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1.0", "1", "5", "1e9"])
def test_run_refuses_a_warn_band_no_snapshot_can_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    rc = main(
        [
            "run",
            "--snapshots",
            str(_snapshots(tmp_path)),
            "--candidates",
            str(_EXAMPLES / "candidates.jsonl"),
            "--warn-band",
            value,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err.startswith("error:")
    assert "warn_band must be < 1.0" in captured.err
    assert captured.out == ""  # refused before any snapshot was diffed


@pytest.mark.parametrize("value", ["1.0", "5"])
def test_diff_refuses_it_the_same_way(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    snap = _snapshots(tmp_path) / "refund_window_v1.yml"
    rc = main(["diff", "--snapshot", str(snap), "--candidate", "hi", "--warn-band", value])
    assert rc == 2
    assert "warn_band must be < 1.0" in capsys.readouterr().err


def test_a_warn_band_below_one_keeps_the_per_snapshot_handling(tmp_path: Path) -> None:
    """Below 1 a snapshot whose effective threshold is above the band can still
    be diffed, so the #85 per-row error stays: the kite snapshot (tolerance
    0.75) errors, an identical one on the run threshold (0.85) does not, and
    `run` is not refused wholesale."""
    snaps = _snapshots(tmp_path)
    (snaps / "refund_window_v1.yml").unlink()  # embedded with another model
    data = yaml.safe_load((snaps / "creative_kite_v1.yml").read_text(encoding="utf-8"))
    data.pop("tolerance", None)
    data["id"] = "kite-plain"
    (snaps / "kite_plain.yml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    first = json.loads((_EXAMPLES / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])
    cands = tmp_path / "cands.jsonl"
    cands.write_text(
        "".join(
            json.dumps({"snapshot": name, "candidate": first["candidate"]}) + "\n"
            for name in ("creative_kite_v1.yml", "kite_plain.yml")
        ),
        encoding="utf-8",
    )
    import io
    from contextlib import redirect_stdout

    out = io.StringIO()
    with redirect_stdout(out):
        rc = main(
            [
                "run",
                "--snapshots",
                str(snaps),
                "--candidates",
                str(cands),
                "--format",
                "json",
                "--warn-band",
                "0.8",
            ]
        )
    rows = json.loads(out.getvalue())["rows"]
    assert rc != 2
    verdicts = {r["snapshot_id"]: r["verdict"] for r in rows}
    assert verdicts["creative-kite-poem-v1"] == "error"
    assert verdicts["kite-plain"] != "error"


# ----------------------------------------------------------------------
# 2. Every row's threshold is the effective one
# ----------------------------------------------------------------------


def test_a_skipped_row_publishes_its_own_tolerance(tmp_path: Path) -> None:
    snaps = _snapshots(tmp_path)
    _variant(snaps, "kite_skip.yml", id="kite-skip", tolerance=0.75)
    _, rows = _run_json(snaps)
    (row,) = [r for r in rows if r["snapshot_id"] == "kite-skip"]
    assert row["verdict"] == "skipped"
    assert row["threshold"] == 0.75


def test_an_error_row_publishes_the_threshold_its_note_names(tmp_path: Path) -> None:
    """The #85 case: a tolerance below the default warn band is a per-row
    error whose note says `effective_threshold (0.03)`; the row said 0.85."""
    snaps = _snapshots(tmp_path)
    _variant(snaps, "kite_low.yml", id="kite-low", tolerance=0.03)
    (snaps / "creative_kite_v1.yml").unlink()
    # Give the variant a candidate under its own file name.
    cands = tmp_path / "cands.jsonl"
    first = json.loads((_EXAMPLES / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])
    cands.write_text(
        json.dumps({"snapshot": "kite_low.yml", "candidate": first["candidate"]}) + "\n"
    )
    import io
    from contextlib import redirect_stdout

    out = io.StringIO()
    with redirect_stdout(out):
        main(["run", "--snapshots", str(snaps), "--candidates", str(cands), "--format", "json"])
    rows = json.loads(out.getvalue())["rows"]
    (row,) = [r for r in rows if r["snapshot_id"] == "kite-low"]
    assert row["verdict"] == "error"
    assert "effective_threshold (0.03)" in row["notes"][0]
    assert row["threshold"] == 0.03


def test_pass_rows_are_unchanged(tmp_path: Path) -> None:
    _, rows = _run_json(_snapshots(tmp_path))
    by_id = {r["snapshot_id"]: r for r in rows}
    assert by_id["creative-kite-poem-v1"]["threshold"] == 0.75
