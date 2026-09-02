"""The temp-name byte budget is measured in the bytes the filesystem sees (#159).

`_cap_base_for_temp` exists so a destination basename near NAME_MAX does not
overflow the limit once the temp affixes are prepended. Its comment says the
budget is in bytes because NAME_MAX is a byte limit — true — and the old
implementation counted `str.encode("utf-8")` under the strict error handler,
which is a different set of bytes from the ones the kernel is handed.

The gap is reachable, not pedantic, because POSIX path bytes and `sys.argv`
both decode through `surrogateescape`: a byte that is not valid UTF-8 becomes a
lone surrogate in `U+DC80..U+DCFF`, which strict UTF-8 encoding refuses. So
`validate --out $'report\\xff.json'` made the cap raise `UnicodeEncodeError`
before it ever reached the length question.

`UnicodeEncodeError` is a `ValueError`, so none of the three write-seam guards
caught it — `cli._write_output`, `cli`'s `update` snapshot save, and
`scripts/render_regression_demo.py` all catch `OSError` alone — and the
interpreter's uncaught-exception path exits **1**, the code this CLI's own
read-seam guards keep naming: "the *regressions found* code".

These tests are written so the *host* never decides the verdict. The
`_cap_base_for_temp` cases are pure-function and hold everywhere. The seam cases
assert a property true on both a byte-transparent filesystem (ext4, where the
write succeeds) and a UTF-8-validating one (APFS, which returns `EILSEQ`).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from prompt_regression import (
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
    save_snapshot,
)
from prompt_regression import io as io_mod
from prompt_regression.io import _MAX_TEMP_BASE_BYTES, _cap_base_for_temp, atomic_write_text

# A lone low surrogate is what `surrogateescape` produces for the raw byte
# 0xFF. Built from its codepoint rather than written literally so the character
# cannot be mangled by an editor or a copy-paste round trip.
SURROGATE = chr(0xDCFF)


def _fs_len(text: str) -> int:
    """The byte length the kernel sees. Never raises; that is the whole point."""
    return len(os.fsencode(text))


# ---------------------------------------------------------------------------
# The variant table. Axes: length (fits / overflows) x encoding class
# (pure ASCII / multibyte UTF-8 / surrogate-bearing / mixed).
# ---------------------------------------------------------------------------

NAME_VARIANTS = [
    ("ascii-short", "report.json"),
    ("ascii-at-budget", "a" * _MAX_TEMP_BASE_BYTES),
    ("ascii-long", "a" * 250),
    # "é" is 2 bytes in UTF-8, so 150 of them is 300 bytes: over budget in
    # bytes while well under it in characters.
    ("multibyte-short", "repórt.json"),
    ("multibyte-long", "é" * 150),
    # Each surrogate is exactly one byte under `os.fsencode` — the byte the
    # name actually came from.
    ("surrogate-short", "report" + SURROGATE + ".json"),
    ("surrogate-long", SURROGATE * 250),
    ("mixed-long", "é" * 50 + SURROGATE * 150),
    ("surrogate-only", SURROGATE),
    ("mixed-at-boundary", "a" * (_MAX_TEMP_BASE_BYTES - 1) + SURROGATE),
]


@pytest.mark.parametrize(("label", "base"), NAME_VARIANTS, ids=[v[0] for v in NAME_VARIANTS])
def test_cap_base_for_temp_never_raises_and_stays_within_budget(label: str, base: str) -> None:
    """Every name a `Path` can hold gets a capped answer, not an exception.

    Strict-UTF-8 measurement raised `UnicodeEncodeError` for the surrogate-
    bearing rows before it could answer the length question at all.
    """
    capped = _cap_base_for_temp(base)

    assert _fs_len(capped) <= _MAX_TEMP_BASE_BYTES, f"{label}: over budget"
    assert capped == base[: len(capped)], (
        f"{label}: the capped name must be a character-boundary prefix of the "
        "original — trimming happens by character so no codepoint is split"
    )
    if _fs_len(base) <= _MAX_TEMP_BASE_BYTES:
        assert capped == base, f"{label}: a name within budget must be returned unchanged"
    else:
        # Maximality: one more character would have gone over. Without this the
        # test would also pass for a cap that returns "" for everything.
        assert len(capped) < len(base)
        assert _fs_len(base[: len(capped) + 1]) > _MAX_TEMP_BASE_BYTES, (
            f"{label}: the cap trimmed further than the budget required"
        )


def test_cap_base_for_temp_agrees_with_the_old_measurement_on_encodable_names() -> None:
    """Switching the measurement must not move the budget for names that worked.

    `os.fsencode` and `str.encode("utf-8")` return the same bytes for every
    string that is valid UTF-8, so every previously-passing name is unaffected;
    the change is confined to the names the old call refused outright.
    """
    for _label, base in NAME_VARIANTS:
        try:
            strict = len(base.encode("utf-8"))
        except UnicodeEncodeError:
            continue  # the population the old measurement could not count at all
        assert _fs_len(base) == strict


def test_name_bytes_never_raises_on_a_surrogate() -> None:
    """The measurement helper itself is total over `str`.

    `os.fsencode` uses `surrogateescape` on POSIX and `surrogatepass` on
    Windows, so it round-trips every string a `Path` can carry.
    """
    assert io_mod._name_bytes("out" + SURROGATE + ".json") == len(b"out\xff.json")


# ---------------------------------------------------------------------------
# The seams. The exception *class* is the contract every caller is written
# against, so that is what gets asserted.
# ---------------------------------------------------------------------------


def test_atomic_write_text_unencodable_target_name_fails_as_oserror_if_at_all(
    tmp_path: Path,
) -> None:
    """A destination name the filesystem cannot represent is an OS-level
    problem, and must surface as one.

    Deliberately not asserted as "succeeds" or as "raises": ext4 accepts any
    non-NUL byte in a name and the write goes through, while APFS validates
    UTF-8 and returns `EILSEQ`. Both are correct, and both are `OSError` or
    nothing — which is what a plain `Path.write_text` of the same target does,
    and the only class the three write-seam guards catch.
    """
    target = tmp_path / ("report" + SURROGATE + ".json")

    try:
        atomic_write_text(target, "{}\n")
    except UnicodeEncodeError as e:  # pragma: no cover - the bug this closes
        pytest.fail(
            "atomic_write_text raised UnicodeEncodeError for an unencodable "
            f"destination *name*: {e!r}. The content was pure ASCII."
        )
    except OSError:
        # The filesystem refused the name. Nothing was left behind.
        assert list(tmp_path.iterdir()) == []
        return

    assert target.read_text(encoding="utf-8") == "{}\n"
    assert [p.name for p in tmp_path.iterdir()] == [target.name]


def test_atomic_write_text_long_unencodable_target_name_is_capped_not_refused(
    tmp_path: Path,
) -> None:
    """The long-name and the unencodable-name axes compose.

    This is the row that needs both halves of the fix: the fast-path check has
    to survive the surrogate to discover the name is over budget, and the trim
    loop has to survive it on every iteration.
    """
    target = tmp_path / (SURROGATE * 250)

    try:
        atomic_write_text(target, "x")
    except UnicodeEncodeError as e:  # pragma: no cover - the bug this closes
        pytest.fail(f"cap raised on a long unencodable name: {e!r}")
    except OSError:
        assert list(tmp_path.iterdir()) == []


def _clean_snapshot() -> Snapshot:
    """The same shape `tests/test_atomic_write.py::_sample_snapshot` uses.

    Built with the hash embedder's own model name so `validate` has nothing to
    complain about — the point of the test below is that the *only* thing that
    can produce a non-zero exit is the write.
    """
    from prompt_regression.diff import HashEmbedder

    embedder = HashEmbedder()
    text = "The Pro plan has a 14-day refund window from purchase."
    return Snapshot(
        id="refund-window-pro-v1",
        prompt=Prompt(
            model="claude-haiku-4-5-20251001",
            user="What's the refund window for the Pro plan?",
            system="You are a polite support agent.",
            temperature=0.0,
            max_tokens=256,
        ),
        response_shape=ResponseShape(
            semantic_categories=["refund-window", "plan-tier"],
            structured_slots={
                "refund_days": {"type": "integer"},
                "plan_name": {"type": "string"},
            },
        ),
        canonical=CanonicalResponse(
            text=text,
            embedding=list(embedder.embed(text)),
            embedding_model=embedder.model_name,
        ),
    )


def test_validate_out_with_unencodable_name_never_exits_one(tmp_path: Path) -> None:
    """The exit code must stay a statement about the *snapshots*.

    `validate --help` documents `0 clean / 1 findings / 2 missing directory`,
    and the read-seam guards in `cli.py` call 1 "the regressions found code"
    every time they explain themselves. This directory holds one well-formed
    snapshot, so a 1 here cannot be a finding — it can only be the write crash
    wearing the content code.

    That is the whole cost of the wrong measurement in this repo:
    `UnicodeEncodeError` is a `ValueError`, all three write seams catch
    `OSError`, and the interpreter's uncaught-exception path exits 1.

    Run in a subprocess rather than in-process, and not for the argv road:
    `capsys` replaces `sys.stderr` with a strict-encoding buffer, while the
    real `sys.stderr` CPython hands a process uses `errors="backslashreplace"`.
    Under `capsys` the guard's own `print(f"... {path} ...")` raises on the
    unencodable path and the test would report a failure the shipped CLI does
    not have. A subprocess gets the real stream, so this asserts the behaviour
    an operator sees.

    Asserted as "never 1, and if nothing was written it is 2" rather than a
    fixed code, because whether the write succeeds is the filesystem's call:
    ext4 accepts the name (exit 0, file written) and APFS refuses it (exit 2
    through the existing guard). Both are correct answers about the snapshots.
    """
    snap_dir = tmp_path / "snaps"
    snap_dir.mkdir()
    save_snapshot(_clean_snapshot(), snap_dir / "refund.snapshot.yaml")
    out_path = tmp_path / ("report" + SURROGATE + ".json")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "prompt_regression.cli",
            "validate",
            str(snap_dir),
            "--json",
            "--out",
            str(out_path),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        check=False,
    )

    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.returncode != 1, (
        "exit 1 means 'findings'; this snapshots dir is clean, so a 1 here is "
        f"the write crash wearing the content code. stderr:\n{proc.stderr}"
    )
    if out_path.exists():
        assert proc.returncode == 0
    else:
        assert proc.returncode == 2
        assert "error: failed to write" in proc.stderr
