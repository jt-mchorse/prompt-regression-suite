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
