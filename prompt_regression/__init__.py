"""prompt-regression-suite: snapshot testing for prompts.

Public surface:

    from prompt_regression import Snapshot, Prompt, ResponseShape, CanonicalResponse
    from prompt_regression import load_snapshot, save_snapshot
    # Diff layer (#2):
    from prompt_regression import diff_response, HashEmbedder, DiffResult
    # HTML report layer (#3):
    from prompt_regression import ReportEntry, render_report
"""

from .diff import (
    DEFAULT_THRESHOLD,
    DEFAULT_WARN_BAND,
    DiffResult,
    Embedder,
    EmbedderModelMismatchError,
    EmbeddingDimensionMismatchError,
    HashEmbedder,
    SemanticCategoryScore,
    SlotDelta,
    cosine,
    diff_response,
    diff_slots,
    extract_slots,
    score_semantic_categories,
)
from .html_report import ReportEntry, render_report
from .io import load_snapshot, save_snapshot
from .schema import (
    SCHEMA_VERSION,
    CanonicalResponse,
    Prompt,
    ResponseShape,
    Snapshot,
    SnapshotValidationError,
)
from .stats import (
    HistogramEntry,
    StatsError,
    StatsReport,
    ToleranceDistribution,
    collect_stats,
    render_summary,
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
    "EmbeddingDimensionMismatchError",
    "HashEmbedder",
    "SemanticCategoryScore",
    "SlotDelta",
    "cosine",
    "diff_response",
    "diff_slots",
    "extract_slots",
    "score_semantic_categories",
    # HTML report (#3)
    "ReportEntry",
    "render_report",
    # Stats (#47)
    "HistogramEntry",
    "StatsError",
    "StatsReport",
    "ToleranceDistribution",
    "collect_stats",
    "render_summary",
]
