"""prompt-regression-suite: snapshot testing for prompts.

Public surface:

    from prompt_regression import Snapshot, Prompt, ResponseShape, CanonicalResponse
    from prompt_regression import load_snapshot, save_snapshot
    # Diff layer (#2):
    from prompt_regression import diff_response, HashEmbedder, DiffResult

HTML report layer (#3) and the real-regression-caught README screenshot (#4)
ship in subsequent issues.
"""

from .diff import (
    DEFAULT_THRESHOLD,
    DEFAULT_WARN_BAND,
    DiffResult,
    Embedder,
    EmbedderModelMismatchError,
    HashEmbedder,
    SemanticCategoryScore,
    SlotDelta,
    cosine,
    diff_response,
    diff_slots,
    extract_slots,
    score_semantic_categories,
)
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
    # Schema (#1)
    "SCHEMA_VERSION",
    "CanonicalResponse",
    "Prompt",
    "ResponseShape",
    "Snapshot",
    "SnapshotValidationError",
    "load_snapshot",
    "save_snapshot",
    # Diff layer (#2)
    "DEFAULT_THRESHOLD",
    "DEFAULT_WARN_BAND",
    "DiffResult",
    "Embedder",
    "EmbedderModelMismatchError",
    "HashEmbedder",
    "SemanticCategoryScore",
    "SlotDelta",
    "cosine",
    "diff_response",
    "diff_slots",
    "extract_slots",
    "score_semantic_categories",
]
