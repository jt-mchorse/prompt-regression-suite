"""prompt-regression-suite: snapshot testing for prompts.

The public surface for issue #1 is the snapshot schema and YAML round-trip:

    from prompt_regression import Snapshot, Prompt, ResponseShape, CanonicalResponse
    from prompt_regression import load_snapshot, save_snapshot

Diff/HTML-report layers ship in subsequent issues (#2, #3).
"""

from .io import load_snapshot, save_snapshot
from .schema import (
    SCHEMA_VERSION,
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
    SnapshotValidationError,
)

__all__ = [
    "SCHEMA_VERSION",
    "CanonicalResponse",
    "Prompt",
    "ResponseShape",
    "Snapshot",
    "SnapshotValidationError",
    "load_snapshot",
    "save_snapshot",
]
