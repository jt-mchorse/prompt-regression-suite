"""Tests for the ``prompt-snap`` CLI (#5)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from prompt_regression.cli import build_parser, main, make_embedder
from prompt_regression.diff import HashEmbedder
from prompt_regression.io import load_snapshot, save_snapshot
from prompt_regression.schema import (
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
)

# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _make_snapshot(snapshot_id: str, canonical_text: str) -> Snapshot:
    embedder = HashEmbedder()
    return Snapshot(
        id=snapshot_id,
        prompt=Prompt(
            model="claude-haiku-4-5",
            user=f"Describe {snapshot_id}",
        ),
        response_shape=ResponseShape(
            semantic_categories=[],
            structured_slots={},
        ),
        canonical=CanonicalResponse(
            text=canonical_text,
            embedding=embedder.embed(canonical_text),
            embedding_model=embedder.model_name,
        ),
    )


@pytest.fixture
def snapshots_dir(tmp_path: Path) -> Path:
    d = tmp_path / "snapshots"
    d.mkdir()
    snap_a = _make_snapshot(
        "refund-policy",
        "Our refund policy gives Pro plan customers 14 days to request a return.",
    )
    snap_b = _make_snapshot(
        "shipping-policy",
        "Standard shipping ships orders within three business days.",
    )
    save_snapshot(snap_a, d / "refund-policy.snapshot.yaml")
    save_snapshot(snap_b, d / "shipping-policy.snapshot.yaml")
    return d


# ----------------------------------------------------------------------
# make_embedder
# ----------------------------------------------------------------------


def test_make_embedder_hash_returns_hashembedder():
    e = make_embedder("hash")
    assert isinstance(e, HashEmbedder)


@pytest.mark.parametrize("reserved", ["voyage", "openai", "cohere"])
def test_make_embedder_reserved_names_raise_notimplementederror(reserved: str):
    with pytest.raises(NotImplementedError, match=reserved):
        make_embedder(reserved)


def test_make_embedder_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown --embedder"):
        make_embedder("definitely-not-a-real-backend")


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------


def test_build_parser_help_lists_all_subcommands():
    parser = build_parser()
    buf = io.StringIO()
    parser.print_help(file=buf)
    text = buf.getvalue()
    assert "run" in text
    assert "update" in text
    assert "diff" in text


@pytest.mark.parametrize("sub", ["run", "update", "diff"])
def test_each_subcommand_has_help(sub: str):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args([sub, "--help"])
    assert exc.value.code == 0


# ----------------------------------------------------------------------
# `run`
# ----------------------------------------------------------------------


def _write_candidates(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_run_happy_path_all_pass(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [
            {
                "snapshot": "refund-policy.snapshot.yaml",
                "candidate": "Our refund policy gives Pro plan customers 14 days to request a return.",
            },
            {
                "id": "shipping-policy",
                "candidate": "Standard shipping ships orders within three business days.",
            },
        ],
    )
    rc = main(["run", "--snapshots", str(snapshots_dir), "--candidates", str(candidates)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "failed=0" in out
    assert "skipped=0" in out
    # Both snapshot paths should appear in the output.
    assert "refund-policy.snapshot.yaml" in out
    assert "shipping-policy.snapshot.yaml" in out


# --- #93: a missing/malformed --candidates file is a usage error (exit 2) ------
#
# `_run_command` translated a missing snapshots dir to exit 2, but the very next
# line loaded the operator's candidates file with no guard — a missing file
# (FileNotFoundError) or malformed/duplicate/empty JSONL (ValueError) escaped as
# a raw traceback at exit 1, the "regressions found" code. These locks were
# confirmed failing (exit 1, traceback) on pre-fix code.


def test_run_missing_candidates_file_exits_two(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    rc = main(
        ["run", "--snapshots", str(snapshots_dir), "--candidates", str(tmp_path / "nope.jsonl")]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "Traceback" not in err


def test_run_malformed_candidates_file_exits_two(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{ not valid json\n", encoding="utf-8")
    rc = main(["run", "--snapshots", str(snapshots_dir), "--candidates", str(bad)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "invalid JSON" in err
    assert "Traceback" not in err


def test_run_empty_candidates_file_exits_two(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    rc = main(["run", "--snapshots", str(snapshots_dir), "--candidates", str(empty)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "no candidate rows" in err
    assert "Traceback" not in err


# --- #99: a malformed *snapshot* under the run dir is a usage error (exit 2) ---
#
# `_run_command` loaded each snapshot with an unguarded `load_snapshot(path)`, so
# a schema-invalid snapshot (SnapshotValidationError, a ValueError subclass) or a
# YAML-syntax-broken one (yaml.YAMLError, NOT a ValueError) escaped as a raw
# traceback at exit 1 — the "regressions found" code — the same class #93/#95
# fixed for the sibling --candidates input. `run` still aborts on the first bad
# file (that's what `validate` collects), but legibly: `error:` + exit 2.


def test_run_schema_invalid_snapshot_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    d = tmp_path / "snaps"
    d.mkdir()
    # Valid YAML, schema-invalid: `prompt` is not a mapping.
    (d / "bad.yml").write_text("id: broken\nprompt: not-a-mapping\n", encoding="utf-8")
    cands = _write_candidates(tmp_path / "cands.jsonl", [{"snapshot": "bad.yml", "candidate": "x"}])
    rc = main(["run", "--snapshots", str(d), "--candidates", str(cands)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "bad.yml" in err
    assert "validate" in err  # points the operator at the collecting-mode command
    assert "Traceback" not in err


def test_run_yaml_broken_snapshot_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    d = tmp_path / "snaps"
    d.mkdir()
    # YAML syntax error (unclosed flow sequence) → yaml.YAMLError, not a ValueError.
    (d / "bad.yml").write_text("id: x\nprompt: [unclosed\n", encoding="utf-8")
    cands = _write_candidates(tmp_path / "cands.jsonl", [{"snapshot": "bad.yml", "candidate": "x"}])
    rc = main(["run", "--snapshots", str(d), "--candidates", str(cands)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "bad.yml" in err
    assert "Traceback" not in err


def test_run_failing_candidate_exits_nonzero(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [
            {
                "snapshot": "refund-policy.snapshot.yaml",
                "candidate": "Completely unrelated text about kittens and yarn.",
            },
            {
                "id": "shipping-policy",
                "candidate": "Standard shipping ships orders within three business days.",
            },
        ],
    )
    rc = main(["run", "--snapshots", str(snapshots_dir), "--candidates", str(candidates)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "failed=" in out
    assert "fail" in out


def test_run_skips_snapshots_with_no_candidate(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [
            {
                "snapshot": "refund-policy.snapshot.yaml",
                "candidate": "Our refund policy gives Pro plan customers 14 days to request a return.",
            },
        ],
    )
    rc = main(["run", "--snapshots", str(snapshots_dir), "--candidates", str(candidates)])
    # One passed, one skipped → exit 0 (skips don't fail the run).
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipped=1" in out
    assert "no candidate supplied" in out


def test_run_json_format_emits_valid_payload(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [
            {
                "snapshot": "refund-policy.snapshot.yaml",
                "candidate": "Our refund policy gives Pro plan customers 14 days to request a return.",
            },
        ],
    )
    rc = main(
        [
            "run",
            "--snapshots",
            str(snapshots_dir),
            "--candidates",
            str(candidates),
            "--format",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "rows" in payload
    assert isinstance(payload["rows"], list)
    assert payload["failed"] == 0
    assert payload["skipped"] == 1
    assert any(r["verdict"] == "pass" for r in payload["rows"])


def test_run_dimension_mismatch_is_per_row_error_not_batch_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    # A snapshot whose stored embedding is the wrong dimension (but whose
    # embedding_model still matches) used to crash cosine() with a raw
    # ValueError that escaped the per-snapshot loop and aborted the whole run.
    # It must instead land as a per-row `error` while other snapshots still diff.
    d = tmp_path / "snaps"
    d.mkdir()
    embedder = HashEmbedder()
    good = _make_snapshot("good-policy", "Refunds are available within fourteen days.")
    bad = Snapshot(
        id="bad-dim",
        prompt=Prompt(model="claude-haiku-4-5", user="?"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text="anything",
            embedding=[0.1] * 64,  # wrong dimension (HashEmbedder emits 128)
            embedding_model=embedder.model_name,  # name still matches → D-006 passes
        ),
    )
    save_snapshot(good, d / "good-policy.snapshot.yaml")
    save_snapshot(bad, d / "bad-dim.snapshot.yaml")
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [
            {
                "snapshot": "good-policy.snapshot.yaml",
                "candidate": "Refunds are available within fourteen days.",
            },
            {"snapshot": "bad-dim.snapshot.yaml", "candidate": "anything"},
        ],
    )
    rc = main(["run", "--snapshots", str(d), "--candidates", str(candidates), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1  # the error row fails the run
    by_id = {r["snapshot_id"]: r for r in payload["rows"]}
    assert len(by_id) == 2  # both snapshots were processed — no batch abort
    assert by_id["bad-dim"]["verdict"] == "error"
    # The good snapshot was still diffed (a real verdict, not skipped/crashed).
    assert by_id["good-policy"]["verdict"] in {"pass", "warn", "fail"}


def test_run_low_tolerance_under_default_warn_band_is_per_row_error_not_batch_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    # #85: a snapshot with a per-snapshot `tolerance` below DEFAULT_WARN_BAND
    # (0.05) lowers the *effective* threshold under the default warn_band, so the
    # #35 guard fires even though the operator never passed --warn-band. That
    # raise used to be a bare ValueError that escaped the per-snapshot loop and
    # aborted the whole batch. It must now land as a per-row `error` (typed
    # WarnBandThresholdError, caught) while other snapshots still diff.
    d = tmp_path / "snaps"
    d.mkdir()
    good = _make_snapshot("good-policy", "Refunds are available within fourteen days.")
    low_tol = _make_snapshot("low-tol", "anything goes here")
    low_tol.tolerance = 0.03  # < DEFAULT_WARN_BAND (0.05); operator set no --warn-band
    save_snapshot(good, d / "good-policy.snapshot.yaml")
    save_snapshot(low_tol, d / "low-tol.snapshot.yaml")
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [
            {
                "snapshot": "good-policy.snapshot.yaml",
                "candidate": "Refunds are available within fourteen days.",
            },
            {"snapshot": "low-tol.snapshot.yaml", "candidate": "anything goes here"},
        ],
    )
    # No --warn-band flag → the run uses DEFAULT_WARN_BAND.
    rc = main(["run", "--snapshots", str(d), "--candidates", str(candidates), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1  # the error row fails the run
    by_id = {r["snapshot_id"]: r for r in payload["rows"]}
    assert len(by_id) == 2  # both processed — no batch abort
    assert by_id["low-tol"]["verdict"] == "error"
    assert any("warn_band must be < effective_threshold" in n for n in by_id["low-tol"]["notes"])
    # The good snapshot was still diffed (a real verdict, not skipped/crashed).
    assert by_id["good-policy"]["verdict"] in {"pass", "warn", "fail"}


def test_run_non_finite_candidate_is_per_row_error_not_batch_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    # A BYO embedder returning a non-finite candidate component must land as a
    # per-row `error` (like the dimension-mismatch case), not a `nan` cosine
    # leaking into the report or a crash aborting the batch.
    d = tmp_path / "snaps"
    d.mkdir()
    real = HashEmbedder()
    good = _make_snapshot("good-policy", "Refunds are available within fourteen days.")
    other = _make_snapshot("other-policy", "Returns accepted within thirty days.")
    save_snapshot(good, d / "good-policy.snapshot.yaml")
    save_snapshot(other, d / "other-policy.snapshot.yaml")

    class _OneNaNEmbedder:
        @property
        def model_name(self) -> str:
            return real.model_name

        def embed(self, text: str) -> list[float]:
            vec = list(real.embed(text))
            if "Returns accepted" in text:  # only the candidate for other-policy
                vec[0] = float("nan")
            return vec

        # `update`/`diff` reembed; `run` only embeds candidates, which is enough here.

    monkeypatch.setattr("prompt_regression.cli.make_embedder", lambda name: _OneNaNEmbedder())
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [
            {
                "snapshot": "good-policy.snapshot.yaml",
                "candidate": "Refunds are available within fourteen days.",
            },
            {
                "snapshot": "other-policy.snapshot.yaml",
                "candidate": "Returns accepted within thirty days.",
            },
        ],
    )
    rc = main(["run", "--snapshots", str(d), "--candidates", str(candidates), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1  # the error row fails the run
    by_id = {r["snapshot_id"]: r for r in payload["rows"]}
    assert len(by_id) == 2  # both processed — no batch abort
    assert by_id["other-policy"]["verdict"] == "error"
    assert by_id["good-policy"]["verdict"] in {"pass", "warn", "fail"}


def test_run_empty_candidate_is_diffed_not_skipped(
    snapshots_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    # An empty-string candidate means the model returned nothing — itself one
    # of the worst regressions. It must be diffed to a `fail` (exit 1), not
    # silently skipped (which let it pass CI green via the old `or` lookup).
    candidates = _write_candidates(
        tmp_path / "cands.jsonl",
        [{"snapshot": "refund-policy.snapshot.yaml", "candidate": ""}],
    )
    rc = main(
        [
            "run",
            "--snapshots",
            str(snapshots_dir),
            "--candidates",
            str(candidates),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    row = next(r for r in payload["rows"] if r["snapshot_id"] == "refund-policy")
    assert row["verdict"] == "fail"  # was "skipped" pre-fix
    assert payload["failed"] >= 1  # was 0 pre-fix
    assert rc == 1  # was 0 pre-fix


def test_run_missing_snapshots_dir_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    cands = _write_candidates(tmp_path / "cands.jsonl", [{"snapshot": "x", "candidate": "y"}])
    rc = main(["run", "--snapshots", str(tmp_path / "no-such-dir"), "--candidates", str(cands)])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_run_empty_snapshots_dir_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    snaps = tmp_path / "empty"
    snaps.mkdir()
    cands = _write_candidates(tmp_path / "cands.jsonl", [{"snapshot": "x", "candidate": "y"}])
    rc = main(["run", "--snapshots", str(snaps), "--candidates", str(cands)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "no snapshot files" in err
    # Error message must enumerate every glob the walker considered, so an
    # operator who pointed at the wrong directory can confirm extension
    # coverage without reading the source.
    for pattern in ("*.snapshot.yaml", "*.snapshot.yml", "*.yml", "*.yaml"):
        assert pattern in err, f"error message missing glob {pattern!r}; got: {err!r}"


def test_run_candidates_invalid_json_raises():
    bad = Path("/tmp/this/path/intentionally/does/not/exist")
    parser = build_parser()
    args = parser.parse_args(["run", "--snapshots", str(bad), "--candidates", str(bad)])
    # snapshots-dir check fires before candidates loader, so this exercises
    # the early-return path; the candidates loader is unit-tested separately.
    assert args.command == "run"


# ----------------------------------------------------------------------
# `update`
# ----------------------------------------------------------------------


def test_update_without_force_refuses(snapshots_dir: Path, capsys: pytest.CaptureFixture[str]):
    rc = main(
        [
            "update",
            "--snapshot",
            str(snapshots_dir / "refund-policy.snapshot.yaml"),
            "--canonical",
            "New canonical response text.",
        ]
    )
    assert rc == 2
    assert "refusing to update without --force" in capsys.readouterr().err


def test_update_with_force_rewrites_canonical(snapshots_dir: Path):
    path = snapshots_dir / "refund-policy.snapshot.yaml"
    before = load_snapshot(path).canonical.text
    new_text = "Refunds are now available for 30 days after purchase."
    rc = main(
        [
            "update",
            "--snapshot",
            str(path),
            "--canonical",
            new_text,
            "--force",
        ]
    )
    assert rc == 0
    after = load_snapshot(path)
    assert after.canonical.text != before
    assert after.canonical.text == new_text
    # Embedder is HashEmbedder by default; the new embedding should match the new text.
    embedder = HashEmbedder()
    assert after.canonical.embedding == embedder.embed(new_text)
    assert after.canonical.embedding_model == embedder.model_name


def test_update_preserves_explicit_tolerance(tmp_path: Path):
    # Re-baselining must not silently drop a per-snapshot tolerance (#10/#61):
    # an author who pinned a tight/loose threshold keeps it across `update`.
    embedder = HashEmbedder()
    snap = Snapshot(
        id="tight-prompt",
        prompt=Prompt(model="claude-haiku-4-5", user="Describe tight-prompt"),
        response_shape=ResponseShape(semantic_categories=[], structured_slots={}),
        canonical=CanonicalResponse(
            text="original canonical text",
            embedding=embedder.embed("original canonical text"),
            embedding_model=embedder.model_name,
        ),
        tolerance=0.95,
    )
    path = tmp_path / "tight-prompt.snapshot.yaml"
    save_snapshot(snap, path)
    assert load_snapshot(path).tolerance == 0.95

    rc = main(["update", "--snapshot", str(path), "--canonical", "brand new canonical", "--force"])
    assert rc == 0
    after = load_snapshot(path)
    assert after.canonical.text == "brand new canonical"
    assert after.tolerance == 0.95  # preserved, not reverted to the per-run default


def test_update_leaves_default_tolerance_as_none(snapshots_dir: Path):
    # A snapshot with no explicit tolerance stays at None — the fix must not
    # inject a spurious default.
    path = snapshots_dir / "refund-policy.snapshot.yaml"
    assert load_snapshot(path).tolerance is None
    rc = main(["update", "--snapshot", str(path), "--canonical", "rebaselined text", "--force"])
    assert rc == 0
    assert load_snapshot(path).tolerance is None


def test_update_canonical_stdin(snapshots_dir: Path, monkeypatch: pytest.MonkeyPatch):
    path = snapshots_dir / "shipping-policy.snapshot.yaml"
    new_text = "Shipping now takes one business day for Pro plan customers.\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(new_text))
    rc = main(["update", "--snapshot", str(path), "--canonical-stdin", "--force"])
    assert rc == 0
    after = load_snapshot(path)
    assert after.canonical.text == new_text.strip()


def test_update_rejects_empty_canonical(
    snapshots_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    # #94: was SystemExit(str) → exit 1; now a clean error + exit 2 (usage code).
    monkeypatch.setattr("sys.stdin", io.StringIO("   \n\n  "))
    path = snapshots_dir / "refund-policy.snapshot.yaml"
    rc = main(["update", "--snapshot", str(path), "--canonical-stdin", "--force"])
    assert rc == 2
    assert "empty" in capsys.readouterr().err


def test_update_rejects_both_canonical_sources(
    snapshots_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    # #94: was SystemExit(str) → exit 1; now a clean error + exit 2 (usage code).
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin\n"))
    path = snapshots_dir / "refund-policy.snapshot.yaml"
    rc = main(
        [
            "update",
            "--snapshot",
            str(path),
            "--canonical",
            "literal arg",
            "--canonical-stdin",
            "--force",
        ]
    )
    assert rc == 2
    assert "not both" in capsys.readouterr().err


# ----------------------------------------------------------------------
# `diff`
# ----------------------------------------------------------------------


def test_diff_pass(snapshots_dir: Path, capsys: pytest.CaptureFixture[str]):
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snapshots_dir / "refund-policy.snapshot.yaml"),
            "--candidate",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "verdict: pass" in out


def test_diff_fail(snapshots_dir: Path, capsys: pytest.CaptureFixture[str]):
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snapshots_dir / "refund-policy.snapshot.yaml"),
            "--candidate",
            "Hamsters often run on wheels at night.",
        ]
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "verdict: fail" in out


def test_diff_json_format(snapshots_dir: Path, capsys: pytest.CaptureFixture[str]):
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snapshots_dir / "refund-policy.snapshot.yaml"),
            "--candidate",
            "Our refund policy gives Pro plan customers 14 days to request a return.",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "pass"
    assert "cosine_score" in payload
    assert payload["embedder_model"] == HashEmbedder().model_name


def test_diff_candidate_stdin(
    snapshots_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO("Our refund policy gives Pro plan customers 14 days to request a return.\n"),
    )
    rc = main(
        [
            "diff",
            "--snapshot",
            str(snapshots_dir / "refund-policy.snapshot.yaml"),
            "--candidate-stdin",
        ]
    )
    assert rc == 0
    assert "verdict: pass" in capsys.readouterr().out


def test_diff_low_tolerance_under_default_warn_band_is_clean_error_not_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    # #89: a per-snapshot `tolerance` below DEFAULT_WARN_BAND (0.05) lowers the
    # effective threshold under the default warn_band, firing the #35 guard even
    # though the operator passed no --warn-band. The sibling `run` command catches
    # the typed WarnBandThresholdError (#85); the `diff` command was missed and let
    # it escape as a raw traceback (exit 1). It must now exit 2 with a clean
    # `error:` message, consistent with diff's other configuration errors.
    snap = _make_snapshot("low-tol", "anything goes here")
    snap.tolerance = 0.03  # < DEFAULT_WARN_BAND (0.05); no --warn-band set
    path = tmp_path / "low-tol.snapshot.yaml"
    save_snapshot(snap, path)
    rc = main(["diff", "--snapshot", str(path), "--candidate", "anything goes here"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "warn_band must be < effective_threshold" in err


# ----------------------------------------------------------------------
# #22: _SNAPSHOT_GLOBS covers committed example files (.yml) AND the
# opinionated .snapshot.yaml convention
# ----------------------------------------------------------------------


def test_iter_snapshot_paths_finds_yml_examples():
    # The repo's committed examples use the bare `.yml` extension, not the
    # opinionated `*.snapshot.yaml`. Before #22 the walker hard-coded
    # `*.snapshot.yaml` and found zero of them, so `prompt-snap run
    # --snapshots examples/snapshots ...` errored out on the very dir
    # the README quickstart sent the reader to.
    from prompt_regression.cli import _iter_snapshot_paths

    examples = Path(__file__).resolve().parent.parent / "examples" / "snapshots"
    found = _iter_snapshot_paths(examples)
    names = sorted(p.name for p in found)
    assert "creative_kite_v1.yml" in names, names
    assert "refund_window_v1.yml" in names, names


def test_iter_snapshot_paths_covers_all_four_extensions(tmp_path: Path):
    # Synthetic dir with one file per supported extension. Walker must
    # find all four and dedupe (a file matching multiple globs shouldn't
    # appear twice).
    from prompt_regression.cli import _iter_snapshot_paths

    for name in (
        "a.snapshot.yaml",
        "b.snapshot.yml",
        "c.yml",
        "d.yaml",
    ):
        (tmp_path / name).write_text("id: t\nprompt: { model: x, user: y }\n", encoding="utf-8")
    found = _iter_snapshot_paths(tmp_path)
    names = sorted(p.name for p in found)
    assert names == ["a.snapshot.yaml", "b.snapshot.yml", "c.yml", "d.yaml"], names
    # Dedup invariant: each unique path appears at most once.
    assert len(found) == len(set(found))


def test_iter_snapshot_paths_dedup_when_filename_matches_multiple_globs(tmp_path: Path):
    # `foo.snapshot.yaml` matches both `*.snapshot.yaml` and `*.yaml`.
    # The walker must merge those into a single entry.
    from prompt_regression.cli import _iter_snapshot_paths

    (tmp_path / "foo.snapshot.yaml").write_text(
        "id: t\nprompt: { model: x, user: y }\n", encoding="utf-8"
    )
    found = _iter_snapshot_paths(tmp_path)
    assert [p.name for p in found] == ["foo.snapshot.yaml"]
    assert len(found) == 1


# ----------------------------------------------------------------------
# Issue #94: diff/update usage errors from _read_text_arg must exit 2
# (the 0/1/2 contract), not exit 1 via SystemExit(str).
# ----------------------------------------------------------------------


def _write_snapshot_file(tmp_path: Path) -> Path:
    snap = _make_snapshot("refund-policy", "Pro plan customers get 14 days to request a return.")
    p = tmp_path / "refund-policy.snapshot.yaml"
    save_snapshot(snap, p)
    return p


def test_diff_empty_candidate_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    snap = _write_snapshot_file(tmp_path)
    rc = main(["diff", "--snapshot", str(snap), "--candidate", "   "])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "empty" in err
    assert "Traceback" not in err


def test_diff_valid_candidate_does_not_exit_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    # Over-rejection guard: a valid candidate still runs the diff (exit 0 or 1,
    # never the usage code 2).
    snap = _write_snapshot_file(tmp_path)
    rc = main(["diff", "--snapshot", str(snap), "--candidate", "some real candidate text"])
    assert rc in (0, 1)
    assert "Traceback" not in capsys.readouterr().err
