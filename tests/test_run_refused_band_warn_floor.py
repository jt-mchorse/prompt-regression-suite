"""A row refused for `warn_band >= tolerance` publishes no warn floor (#247).

Measured on `64191f6` with `tolerance: 0.04` added to a copy of the refund
snapshot and the default `--warn-band 0.05`:

    run --format json:  "verdict": "error", "threshold": 0.04, "warn_floor": 0.0,
                        "notes": ["warn_band must be < effective_threshold (0.04); got 0.05"]

`diff_response` refuses that band (#35), so no verdict was decided at any floor.
The `0.0` was `warn_floor()`'s clamp, which is the collapsed band the refusal
exists to reject. `_row_warn_floor` builds the floor for `error` and `skipped`
rows (#203) and checked only `warn_band <= 0`.
"""

from __future__ import annotations

import io
import json
import shutil
from contextlib import redirect_stdout
from pathlib import Path

import pytest
import yaml

from prompt_regression.cli import main

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
_KITE = "creative_kite_v1.yml"


def _snapshots(tmp_path: Path, **kite_changes: object) -> Path:
    d = tmp_path / "snaps"
    shutil.copytree(_EXAMPLES / "snapshots", d)
    if kite_changes:
        data = yaml.safe_load((d / _KITE).read_text(encoding="utf-8"))
        data.update(kite_changes)
        (d / _KITE).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return d


def _variant(snaps: Path, name: str, **changes: object) -> None:
    data = yaml.safe_load((snaps / _KITE).read_text(encoding="utf-8"))
    data.update(changes)
    data["id"] = name
    (snaps / name).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _rows(snaps: Path, *extra: str) -> dict[str, dict]:
    out = io.StringIO()
    with redirect_stdout(out):
        main(
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
    return {Path(r["snapshot_path"]).name: r for r in json.loads(out.getvalue())["rows"]}


@pytest.mark.parametrize(
    ("tolerance", "extra"),
    [
        (0.04, ()),  # the issue row: default band 0.05 above the tolerance
        (0.05, ()),  # the `==` edge: the floor is exactly 0.0, unclamped, and still refused
        (0.4, ("--warn-band", "0.5")),  # an explicit band
    ],
    ids=["below-default-band", "equal-to-band", "explicit-band"],
)
def test_an_error_row_refused_for_its_band_has_no_floor(
    tmp_path: Path, tolerance: float, extra: tuple[str, ...]
) -> None:
    row = _rows(_snapshots(tmp_path, tolerance=tolerance), *extra)[_KITE]
    assert row["verdict"] == "error"
    assert row["notes"][0].startswith("warn_band must be < effective_threshold")
    assert row["threshold"] == tolerance
    assert row["warn_floor"] is None


def test_a_skipped_row_whose_band_would_be_refused_has_no_floor(tmp_path: Path) -> None:
    snaps = _snapshots(tmp_path)
    _variant(snaps, "low.yml", tolerance=0.04)
    row = _rows(snaps)["low.yml"]
    assert row["verdict"] == "skipped"
    assert row["warn_floor"] is None


def test_rows_with_a_usable_band_keep_their_floor(tmp_path: Path) -> None:
    # Control: #203's floor on every other row shape is unchanged.
    snaps = _snapshots(tmp_path)
    _variant(snaps, "ok.yml", tolerance=0.75)
    rows = _rows(snaps)
    assert (rows[_KITE]["verdict"], rows[_KITE]["warn_floor"]) == ("pass", 0.7)
    assert (rows["ok.yml"]["verdict"], rows["ok.yml"]["warn_floor"]) == ("skipped", 0.7)
    # The refund snapshot errors on its embedder, not on its band: the floor it
    # would have been judged at is still published.
    refund = rows["refund_window_v1.yml"]
    assert (refund["verdict"], refund["warn_floor"]) == ("error", 0.8)
