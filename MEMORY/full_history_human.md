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

## 2026-05-16 — Issue #4 (and #3): HTML report layer + regression demo
**Duration:** ~35 min · **Branch:** `session/2026-05-16-0420-issue-4`

- Scope expansion (deliberate): #4 asks for an HTML diff screenshot, but the HTML report layer is #3 (priority:med, not yet shipped) — the two are tightly coupled. **This PR closes both.**
- `prompt_regression/html_report.py` renders a list of `(snapshot_id, DiffResult, candidate_text, baseline_text)` entries into a self-contained HTML page with embedded CSS, no JS, no external assets (D-007). Each entry gets an HTML anchor (`#snapshot-<id>`) so a CI artifact URL can deep-link to a specific failure. Failing sections render the semantic-category table, slot deltas (with per-status color), and the baseline + candidate responses side-by-side; passing sections collapse to a one-line note so the report stays scannable. Verdict colors mirror the diff layer's vocabulary.
- `scripts/render_regression_demo.py` builds the baseline snapshot in-process via `HashEmbedder.embed(_BASELINE_TEXT)`, runs `diff_response` against an `_UPGRADED_TEXT` that drops the eligibility-caveat slot and rephrases "14 days" as "two weeks", and writes the full report to `docs/regression_demo.html`. Verdict: `fail`, cosine `0.218`. Screenshot via Playwright or `wkhtmltoimage` if either is installed; honest fallback writes just the HTML when neither is available.
- D-008 frames the demo's honesty: the two response strings are synthetic and labeled as such in the snapshot's `notes` field and the README's section title. The path to a real captured regression is documented as "replace the two strings and re-run the same script" — keeps issue #4 shippable without fabricating cross-model claims, which is exactly what the portfolio's no-fabricated-benchmarks rule exists to prevent.
- 16 new tests: 13 in `tests/test_html_report.py` (verdict-class on each section, anchor slugification, summary stats, fail section renders categories/slots/responses, pass section collapses, warn section still renders details, HTML escaping for unsafe inputs, full-document shape, multi-entry distinct anchors + preserved order). 3 in `tests/test_render_regression_demo.py` (the synthetic regression actually fails the diff; the baseline still passes against itself; the eligibility-caveat slot specifically regresses; CLI writes to the requested path). Suite total: 70/70 pass; ruff lint+format clean.

**Why this work, this session:** With #2 (diff layer) shipped and #3 + #4 closing in this PR, prompt-regression-suite hits its v0.1 quality bar: README + architecture + quickstart that works on a fresh clone + a real demo of the suite catching a regression + MEMORY + MIT license. The remaining open work (#5/#6 if filed) is improvement-mode rather than v0.1.

**Open questions / blockers:** None. Real-LLM regression capture is documented as a two-string swap when an operator runs the script against a real API.

**Next session:** Either #5 (whatever lands as the next priority issue) or a fresh repo — prompt-regression-suite is at v0.1.
