# Core Decisions

Strategic decisions for this repo, with reasoning. Append-only — superseded decisions are marked, not removed.

## D-001 — Scope locked to portfolio handoff §2 (2026-05-10)
**Decision:** Scope of this repo is fixed by the portfolio handoff document, section 2.

**Why:** The handoff spec was deliberated; ad-hoc scope expansion within a session is the failure mode this prevents.

**Alternatives considered:** None — this is a baseline.

**Reversibility:** Expensive. Scope changes require a deliberate revisit and a new decision entry.

**Related issues:** —

## D-002 — Schema uses dataclasses + manual validation, not pydantic (2026-05-14)
**Decision:** The snapshot schema is implemented as plain dataclasses with hand-written validation in `__post_init__`. PyYAML is the only runtime dep beyond stdlib.

**Why:** This package is meant to be imported from other portfolio repos (notably `llm-eval-harness` consumers and `rag-production-kit`'s eval suite). Pulling pydantic into every downstream environment buys very little — the schema is small, the validation rules are clear, and the dataclass approach matches the precedent set by `llm-eval-harness` D-002. Keeping the dep surface minimal also makes the package fast to import inside CI.

**Alternatives considered:**
- pydantic v2 models — rejected; too heavy a dep for a small schema.
- Plain dicts with no validation — rejected; the diff layer (#2) and the report layer (#3) both need structural guarantees, and pushing validation into every reader is worse than centralizing it.

**Reversibility:** Cheap. Migrating to pydantic later is a mechanical refactor and the YAML on disk doesn't change.

**Related issues:** #1, #2.

## D-003 — Canonical-response embedding stored inline in snapshot YAML (2026-05-14)
**Decision:** The canonical response's embedding is stored inline as a list of floats inside the snapshot YAML file, not in a sidecar `.npy` file.

**Why:** Snapshots are checked into git alongside the prompts they cover, and the whole value proposition is that changes show up in pull request diffs. A sidecar `.npy` is opaque in PR review and adds a second file the reader has to chase. The inline-floats representation is verbose at high embedding dimensions but stays diff-reviewable; for typical small embedding models (384–768 dims) the file size stays well under any reasonable limit.

**Alternatives considered:**
- Sidecar `.npy` file per snapshot — rejected; opaque in PR diffs, second file to manage.
- Base64-encoded float32 blob inline — rejected; compact but opaque, defeats the diff-reviewability goal.

**Reversibility:** Cheap. The loader can grow a fallback path for sidecar `.npy` or base64 blobs later without breaking existing inline-floats snapshots.

**Related issues:** #1, #2.

## D-004 — Diff layer is two channels (cosine + slot) AND-ed into one verdict (2026-05-15)
**Decision:** `diff_response()` returns a `DiffResult` with a cosine similarity score, a list of per-slot deltas, optional semantic-category scores, and a single `verdict ∈ {pass, warn, fail}` that's the AND of both channels. A high cosine score with a missing structured slot is a `fail`, not a `pass`. A `warn` is reserved for cosine in the configurable warn-band just below threshold with all slots passing.

**Why:** Cosine similarity catches *topical* drift — the response changed subject. Structured-slot extraction catches *structural* drift — the response still talks about the right thing but stopped naming the plan, or stopped quoting a number. They're orthogonal failure modes; collapsing them into one weighted score hides which one regressed. AND-ing them at the verdict layer keeps each channel's signal visible while still producing the single pass/fail bit CI needs.

**Alternatives considered:**
- Cosine only — rejected: misses structural drift.
- Slots only — rejected: misses topical drift.
- Weighted blend into one combined score — rejected: hides which channel regressed.

**Reversibility:** Cheap.

**Related issues:** #2, #3

## D-005 — `Embedder` is a single-method Protocol (2026-05-15)
**Decision:** `prompt_regression.diff.Embedder` is a Protocol with `model_name: str` and `embed(text) -> list[float]`. Tests use the dep-free `HashEmbedder` reference; production callers BYO via the Protocol.

**Why:** The portfolio is using single-method Protocol as the standard test-substitution seam (`rag-production-kit` Embedder + Reranker, `llm-eval-harness` Backend, `llm-cost-optimizer` Embedder + Storage). Consistent shape across repos.

**Alternatives considered:**
- Hard-coded OpenAI embedder — rejected: vendor lock-in, SDK install on tests.
- Abstract base class — rejected: ceremony for a one-method seam.
- sklearn-style `BaseEstimator` — rejected: no `fit`.

**Reversibility:** Cheap.

**Related issues:** #2, #4

## D-006 — Diff refuses on embedder/snapshot model mismatch (2026-05-15)
**Decision:** `diff_response()` raises `EmbedderModelMismatchError` if the embedder's `model_name` doesn't match the snapshot's recorded `canonical.embedding_model`. `force=True` overrides.

**Why:** A silently re-embedded comparison produces false PASSes that look like the suite is working — every snapshot passes, but the cosine numbers don't mean what the operator thinks. Default refusal forces deliberate re-snapshot with the new model.

**Alternatives considered:**
- Warn only — rejected: warnings get ignored.
- Silent re-embed on mismatch — rejected: this is the failure mode.
- Require an explicit `re-snapshot` CLI before any diff — rejected: too heavy for in-process use.

**Reversibility:** Cheap. `force=True` is the operator's safety valve.

**Related issues:** #2
