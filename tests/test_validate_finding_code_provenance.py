"""A finding's code comes from its raise site, not from its message (#155).

`validate_snapshots` used to classify with

    code = "schema_version" if "schema_version" in str(e) else "schema"

directly under a comment saying the code exists "so migration tooling can route
on the code without parsing the prose". It parsed the prose. And because
`SnapshotValidationError` messages embed identifiers taken from the snapshot --
`Prompt.__init__() got an unexpected keyword argument 'x'` -- the file under
validation chose its own code.

Measured before the fix, three otherwise-valid snapshots:

    schema_version: 123                       -> schema_version   (correct)
    unknown field 'colour' in prompt          -> schema           (correct)
    unknown field 'schema_version_note'       -> schema_version   (WRONG)

Same error class, same raise site, different machine-readable code, decided by
a field name. `Prompt.extra` is documented as a "forward-compat bucket ... so
existing snapshots don't break on schema growth", which makes a
`schema_version`-ish key a plausible thing for a real corpus to hold.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prompt_regression.schema import SnapshotValidationError
from prompt_regression.validate import validate_snapshots

_BASE: dict = {
    "id": "s1",
    "prompt": {"model": "m", "user": "hi"},
    "response_shape": {"semantic_categories": ["greeting"]},
    "canonical": {
        "text": "hello",
        "embedding": [0.6, 0.8],
        "embedding_model": "test-embedder",
    },
}


def _write(tmp_path: Path, snapshot: dict) -> Path:
    (tmp_path / "s.snapshot.yaml").write_text(json.dumps(snapshot), encoding="utf-8")
    return tmp_path


def _only_finding(tmp_path: Path, snapshot: dict):
    report = validate_snapshots(_write(tmp_path, snapshot))
    assert len(report.findings) == 1, [f.reason for f in report.findings]
    return report.findings[0]


def test_the_baseline_snapshot_is_valid() -> None:
    """Anti-vacuous for every row below: if the fixture were malformed, each
    case would 'pass' on an unrelated finding."""
    import tempfile

    report = validate_snapshots(_write(Path(tempfile.mkdtemp()), _BASE))
    assert report.findings == ()
    assert report.n_valid == 1


@pytest.mark.parametrize(
    ("label", "mutate", "expected_code"),
    [
        (
            "a real version mismatch",
            lambda s: {**s, "schema_version": "99"},
            "schema_version",
        ),
        (
            "an ordinary unknown field",
            lambda s: {**s, "prompt": {**s["prompt"], "colour": "red"}},
            "schema",
        ),
        (
            "an unknown field whose NAME contains schema_version",
            lambda s: {**s, "prompt": {**s["prompt"], "schema_version_note": "x"}},
            "schema",
        ),
        (
            "an unknown field whose name IS schema_version, in a subsection",
            lambda s: {**s, "canonical": {**s["canonical"], "schema_version": "1"}},
            "schema",
        ),
        (
            "a string VALUE mentioning schema_version",
            lambda s: {**s, "prompt": {**s["prompt"], "user": "explain schema_version to me"}},
            None,  # valid: a value is not a schema problem at all
        ),
    ],
    ids=["real-mismatch", "ordinary", "name-contains", "name-is", "value-mentions"],
)
def test_the_message_does_not_decide_the_code(
    tmp_path: Path, label: str, mutate, expected_code: str | None
) -> None:
    report = validate_snapshots(_write(tmp_path, mutate(_BASE)))
    if expected_code is None:
        assert report.findings == (), f"{label}: expected no finding, got {report.findings}"
        return
    assert len(report.findings) == 1, f"{label}: {[f.reason for f in report.findings]}"
    assert report.findings[0].code == expected_code, label


def test_rewording_a_message_cannot_move_a_code() -> None:
    """The property the change actually buys.

    Under the old rule, editing any message in `schema.py` to mention
    `schema_version` -- or editing `io.py`'s to stop mentioning it -- silently
    moved a finding's routing. Now the code and the text are independent, which
    is asserted directly rather than inferred from the cases above.
    """
    quiet = SnapshotValidationError("nothing notable here")
    loud = SnapshotValidationError("this message mentions schema_version prominently")
    assert quiet.code == "schema"
    assert loud.code == "schema", "a message must not be able to claim the version code"

    tagged = SnapshotValidationError("no marker in this text", code="schema_version")
    assert tagged.code == "schema_version", "the raise site must be able to set it"
    assert "schema_version" not in str(tagged)


def test_an_unknown_code_is_rejected_at_construction() -> None:
    """A typo'd code must fail loudly, not become an unroutable finding.

    The closed set is what lets `test_finding_codes_matches_what_the_module_can_emit`
    treat `CODES` as a trustworthy half of the documented list.
    """
    with pytest.raises(ValueError, match="unknown SnapshotValidationError code"):
        SnapshotValidationError("x", code="schema-version")
    with pytest.raises(ValueError, match="unknown SnapshotValidationError code"):
        SnapshotValidationError("x", code="")


def test_the_version_finding_still_reports_the_original_message(tmp_path: Path) -> None:
    """The reason text is unchanged -- this is a routing fix, not a reword.

    `validate.py`'s comment promises operators get "the same string the loader
    would have raised"; carrying the code separately must not disturb that.
    """
    finding = _only_finding(tmp_path, {**_BASE, "schema_version": "99"})
    assert finding.code == "schema_version"
    assert "snapshot schema_version is '99'" in finding.reason
    assert "this reader only supports" in finding.reason
