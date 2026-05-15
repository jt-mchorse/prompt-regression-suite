"""Snapshot schema for prompt-regression-suite (issue #1).

A snapshot is the union of:

  - the inputs that produced a response (prompt + model + sampling params),
  - the structural expectations a future response must continue to satisfy
    (semantic categories + structured slots),
  - a stored canonical response (text + inline embedding + embedding model),

all under a single immutable schema version so the diff layer (#2) and the
report layer (#3) can read snapshots without sniffing.

The schema is dataclass-based by deliberate choice (D-002): no pydantic
runtime dep, so this package stays cheap to import from any downstream
portfolio repo. Validation is manual and lives in __post_init__.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "1"
"""Snapshot schema version. Bump on breaking changes; readers must check this."""

_ALLOWED_SLOT_TYPES = ("string", "number", "integer", "boolean", "array", "object", "null")


class SnapshotValidationError(ValueError):
    """Raised when a snapshot's structure is invalid.

    All schema-validation failures funnel through this class so callers can
    catch one type instead of distinguishing TypeError from ValueError.
    """


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SnapshotValidationError(f"{field_name} must be a string, got {type(value).__name__}")
    if not value:
        raise SnapshotValidationError(f"{field_name} must be non-empty")
    return value


def _require_optional_str(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SnapshotValidationError(f"{field_name} must be a string or None")
    return value


@dataclass
class Prompt:
    """The inputs that produced the canonical response.

    Captures everything that, if changed, could legitimately change the
    response — so the diff layer can attribute drift to either model change
    or prompt change.
    """

    model: str
    user: str
    system: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    """Forward-compat bucket for anything not yet first-class (top_p, tools, etc.).
    Round-trips through YAML so existing snapshots don't break on schema growth."""

    def __post_init__(self) -> None:
        _require_str(self.model, "Prompt.model")
        _require_str(self.user, "Prompt.user")
        self.system = _require_optional_str(self.system, "Prompt.system")
        if self.temperature is not None:
            if not isinstance(self.temperature, (int, float)) or isinstance(self.temperature, bool):
                raise SnapshotValidationError("Prompt.temperature must be a number or None")
            if not 0.0 <= float(self.temperature) <= 2.0:
                raise SnapshotValidationError("Prompt.temperature must be in [0.0, 2.0]")
            self.temperature = float(self.temperature)
        if self.max_tokens is not None:
            if not isinstance(self.max_tokens, int) or isinstance(self.max_tokens, bool):
                raise SnapshotValidationError("Prompt.max_tokens must be an int or None")
            if self.max_tokens <= 0:
                raise SnapshotValidationError("Prompt.max_tokens must be positive")
        if not isinstance(self.extra, Mapping):
            raise SnapshotValidationError("Prompt.extra must be a mapping")
        self.extra = dict(self.extra)


@dataclass
class ResponseShape:
    """Structural expectations a future response must continue to satisfy.

    Two channels:

    - ``semantic_categories``: free-form topical labels the response is
      expected to cover (e.g., ``["refund-eligibility", "delivery-eta"]``).
      The diff layer (#2) treats these as soft assertions scored by the
      embedding similarity of the new response against each category.

    - ``structured_slots``: typed key/value extraction expectations
      (e.g., ``{"customer_id": {"type": "string"}}``). The diff layer
      enforces these as hard assertions: a missing slot is a fail, a
      type-mismatch is a fail.
    """

    semantic_categories: list[str] = field(default_factory=list)
    structured_slots: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.semantic_categories, Sequence) or isinstance(
            self.semantic_categories, str
        ):
            raise SnapshotValidationError("ResponseShape.semantic_categories must be a list")
        clean_cats: list[str] = []
        seen: set[str] = set()
        for i, cat in enumerate(self.semantic_categories):
            c = _require_str(cat, f"ResponseShape.semantic_categories[{i}]")
            if c in seen:
                raise SnapshotValidationError(
                    f"ResponseShape.semantic_categories has duplicate entry: {c!r}"
                )
            seen.add(c)
            clean_cats.append(c)
        self.semantic_categories = clean_cats

        if not isinstance(self.structured_slots, Mapping):
            raise SnapshotValidationError("ResponseShape.structured_slots must be a mapping")
        clean_slots: dict[str, dict[str, Any]] = {}
        for name, spec in self.structured_slots.items():
            _require_str(name, "ResponseShape.structured_slots key")
            if not isinstance(spec, Mapping):
                raise SnapshotValidationError(
                    f"ResponseShape.structured_slots[{name!r}] must be a mapping"
                )
            spec = dict(spec)
            slot_type = spec.get("type")
            if slot_type is None:
                raise SnapshotValidationError(
                    f"ResponseShape.structured_slots[{name!r}] missing required 'type' key"
                )
            if slot_type not in _ALLOWED_SLOT_TYPES:
                raise SnapshotValidationError(
                    f"ResponseShape.structured_slots[{name!r}].type "
                    f"must be one of {_ALLOWED_SLOT_TYPES}, got {slot_type!r}"
                )
            clean_slots[name] = spec
        self.structured_slots = clean_slots


@dataclass
class CanonicalResponse:
    """The response that defined the baseline for this snapshot.

    The embedding is stored inline as a list of floats (D-003): snapshots
    stay diff-reviewable in PRs, and the loader stays sidecar-file-free.
    The embedding model is recorded so the diff layer can refuse to compare
    against a re-embedded response taken from a different model.
    """

    text: str
    embedding: list[float]
    embedding_model: str

    def __post_init__(self) -> None:
        _require_str(self.text, "CanonicalResponse.text")
        _require_str(self.embedding_model, "CanonicalResponse.embedding_model")
        if not isinstance(self.embedding, Sequence) or isinstance(self.embedding, str):
            raise SnapshotValidationError(
                "CanonicalResponse.embedding must be a sequence of floats"
            )
        if len(self.embedding) == 0:
            raise SnapshotValidationError("CanonicalResponse.embedding must be non-empty")
        clean: list[float] = []
        for i, v in enumerate(self.embedding):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise SnapshotValidationError(
                    f"CanonicalResponse.embedding[{i}] must be a number, got {type(v).__name__}"
                )
            clean.append(float(v))
        self.embedding = clean


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Snapshot:
    """A single regression snapshot for one prompt.

    The ``id`` is the stable key the diff layer uses to find a baseline when
    a new response comes in — it should be unique within a repo's snapshot
    directory and not encode date or model info (those have their own fields).
    """

    id: str
    prompt: Prompt
    response_shape: ResponseShape
    canonical: CanonicalResponse
    schema_version: str = SCHEMA_VERSION
    created_at: str = field(default_factory=_utcnow_iso)
    notes: str | None = None

    def __post_init__(self) -> None:
        _require_str(self.id, "Snapshot.id")
        if not isinstance(self.prompt, Prompt):
            raise SnapshotValidationError("Snapshot.prompt must be a Prompt instance")
        if not isinstance(self.response_shape, ResponseShape):
            raise SnapshotValidationError(
                "Snapshot.response_shape must be a ResponseShape instance"
            )
        if not isinstance(self.canonical, CanonicalResponse):
            raise SnapshotValidationError("Snapshot.canonical must be a CanonicalResponse instance")
        _require_str(self.schema_version, "Snapshot.schema_version")
        _require_str(self.created_at, "Snapshot.created_at")
        self.notes = _require_optional_str(self.notes, "Snapshot.notes")

    def to_dict(self) -> dict[str, Any]:
        """Render the snapshot as a plain dict suitable for YAML/JSON dump.

        Round-trip identity: ``Snapshot.from_dict(s.to_dict()) == s``.
        """
        data = asdict(self)
        # Drop None notes so YAML stays tidy on snapshots that don't use it.
        if data.get("notes") is None:
            data.pop("notes", None)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Snapshot:
        """Build a Snapshot from a plain dict (loader entry point).

        Raises ``SnapshotValidationError`` for any structural problem.
        """
        if not isinstance(data, Mapping):
            raise SnapshotValidationError(
                f"Snapshot payload must be a mapping, got {type(data).__name__}"
            )
        try:
            prompt = Prompt(**data["prompt"])
            response_shape = ResponseShape(**data["response_shape"])
            canonical = CanonicalResponse(**data["canonical"])
        except KeyError as e:
            raise SnapshotValidationError(
                f"Snapshot missing required section: {e.args[0]!r}"
            ) from e
        except TypeError as e:
            raise SnapshotValidationError(f"Snapshot section has unexpected fields: {e}") from e

        return cls(
            id=data["id"],
            prompt=prompt,
            response_shape=response_shape,
            canonical=canonical,
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            created_at=data.get("created_at", _utcnow_iso()),
            notes=data.get("notes"),
        )
