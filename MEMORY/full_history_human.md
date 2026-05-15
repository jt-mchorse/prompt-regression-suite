# Session History (human-readable)

Chronological log of work sessions. Most recent first below the divider.

---

## 2026-05-14 — Issue #1: snapshot YAML schema + loader/saver
**Duration:** ~55 min · **Branch:** `session/2026-05-14-1408-issue-01`

- Shipped the v1 snapshot schema as four dataclasses (`Prompt`,
  `ResponseShape`, `CanonicalResponse`, `Snapshot`) with manual
  validation in `__post_init__` — no pydantic dep (D-002).
- Shipped `load_snapshot` / `save_snapshot` with YAML round-trip
  identity and a strict `schema_version` check on read.
- Committed `examples/snapshots/refund_window_v1.yml` as the working
  reference snapshot — issue #2's diff layer will use it as its
  day-one input.
- Real CI replaces the stub echos: `ruff` + `pytest --cov` matrix on
  py3.11 and py3.12. 29 tests pass locally with 95% coverage on the
  package.
- README "What this is" and "Quickstart" replaced with real content;
  `docs/schema.md` added.

**Why this work, this session:** Issue #1 is the foundation for #2/#3/#4
— every later layer reads the schema. The repo had been at bare
scaffolding since bootstrap (2026-05-10).

**Open questions / blockers:** None.

**Next session:** Issue #2 (semantic similarity diff with tunable
threshold). Inputs are now in place: load the sample snapshot, compute
cosine vs. a new response's embedding, enforce slot extraction.

## 2026-05-15 — Issue #2: Semantic similarity diff with tunable threshold
**Duration:** ~55 min · **Branch:** `session/2026-05-15-1659-issue-02`

- Shipped `prompt_regression/diff.py`: `diff_response()` end-to-end with two channels AND-ed into one verdict (D-004). Cosine channel + structured-slot extraction channel + optional semantic-category scoring. `DiffResult` carries each channel's raw signal so callers can see *which* one regressed.
- `Embedder` Protocol parallel to the rest of the portfolio (D-005); `HashEmbedder` reference for hermetic CI.
- `EmbedderModelMismatchError` refusal by default (D-006) with `force=True` escape hatch — silently re-embedded comparisons are the failure mode where the suite looks like it's working but the cosine numbers don't mean what the operator thinks.
- Slot extraction heuristics: integer/number with hint-anchored disambiguation, quoted-string preferred over keyword-fallback, boolean keyword detection with negative-pattern-first ordering. `type_unknown` reported for unrecognized types so callers can see we didn't try.
- 25 new hermetic tests (5 cosine/embedder + 7 slot extraction + 8 diff_response end-to-end + 2 model-mismatch refusal + 3 result-shape contract). Acceptance criteria from #2 all exercised: identical → 1.0, paraphrase → high pass, off-topic → fail, default threshold 0.85.
- Backfilled README "Diff layer (#2 · this PR)" section with snippets and the model-mismatch refusal rationale.

**Why this work, this session:** The diff layer is what makes the snapshot schema useful — without it the snapshots are just YAML files. Locking the `DiffResult` shape and the two-channel verdict logic now lets the HTML report (#3) and the real-regression demo (#4) consume a stable interface.

**Open questions / blockers:** None. Real-embedder integration is BYO via the Protocol; the operator picks Cohere/Voyage/sentence-transformers. The "real regression caught" screenshot is issue #4.

**Next session:** Issue #3 (HTML diff report) is the natural sibling — consumes `DiffResult` from this PR and renders it via jinja2 for PR review.
