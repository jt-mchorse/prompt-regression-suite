# Session History (human-readable)

Chronological log of work sessions. Most recent first below the divider.

---

## 2026-05-19 — Issue #14: drop "Issue [#N] ships" framing + drift lock
**Duration:** ~25 min · **Branch:** `session/2026-05-19-issue-14`

- Rewrote "What this is" paragraph 2 from "Issue [#1] ships the schema and the loader/saver; issue [#2] adds the embedding-similarity..." to a six-bullet past-tense list covering every shipped issue (#1 schema, #2 similarity diff, #3 HTML report, #4 caught regression, #5 CLI, #10 per-snapshot tolerance).
- Demo section: replaced "A 60-second video pending; the static HTML demo is runnable today." with today's two-command path (`scripts/render_regression_demo.py` + opening the HTML) plus the captured-asset follow-up filed as #15.
- Extended `tests/test_regression_demo_snapshot.py` with three drift-lock tests (5 total): all six (#N) refs appear in "What this is", no `Issue [#N] ships|adds|documents` framing remains, Demo section names a follow-up + references the renderer script.

**Why this work, this session:** Sister to the portfolio-wide drift-lock pattern; prompt-regression-suite still carried the present-tense issue-N-ships framing.

**Open questions / blockers:** None.

**Next session:** Continues with Phase A; #15 is priority:low demo capture.

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

## 2026-05-16 — Issue #5: `prompt-snap` CLI (run / update / diff)
**Duration:** ~40 min · **Branch:** `session/2026-05-16-2001-issue-5`

- Shipped `prompt_regression/cli.py` plus a `prompt-snap` console script registered via `[project.scripts]` in `pyproject.toml`. Three subcommands, pure glue over existing types (`diff_response`, `load_snapshot`, `save_snapshot`, `HashEmbedder`); no new core decisions.
- `prompt-snap run` walks a directory of `*.snapshot.yaml` files recursively, loads candidates from a JSONL keyed by either the snapshot path relative to the snapshots dir or by `snapshot.id`, runs `diff_response` per pair, prints a per-snapshot status table (or JSON via `--format json`), and exits non-zero on any `fail` verdict. Snapshots without a candidate are surfaced as `skipped` and do not fail the run. `EmbedderModelMismatchError` becomes an `error` row that counts as a failure.
- `prompt-snap update` re-baselines one snapshot's canonical response (re-embeds via the configured embedder) and writes back via `save_snapshot`. **Requires `--force`** — without it exits 2 with a clear "refusing to update without --force (prevents accidental re-baselining of a failing snapshot)" message. New text via `--canonical` or `--canonical-stdin`; mixing both is rejected, an empty/whitespace value is rejected.
- `prompt-snap diff` is the ad-hoc single-snapshot version. Candidate from `--candidate` or stdin; output text or JSON; exits 1 on `fail`. Honors `--force-embedder` to skip the D-006 mismatch guard.
- `make_embedder("hash")` returns `HashEmbedder`; reserved names `voyage`/`openai`/`cohere` raise `NotImplementedError` with a clear "implement the Embedder protocol locally" message so misconfigured runs fail loud at startup instead of silently against a stale stub.
- 25 new hermetic tests in `tests/test_cli.py` covering embedder resolution, parser help across subcommands, `run` happy/fail/skip/JSON/missing-dir/empty-dir paths, `update` without-force/with-force/stdin/empty/both-sources-conflict, `diff` pass/fail/JSON/stdin. Full suite 95/95 pass; ruff clean.
- README "CLI: `prompt-snap` (#5 · this PR)" subsection with the three subcommands, sample output, and the candidates JSONL row shape.

**Why this work, this session:** #5 was the last open issue in this repo (low priority); closing it brings prompt-regression-suite from v0.1 to v0.1+CLI. Picking a new repo here also keeps the multi-issue session prompt's "spread across repos" intent honest after four PRs concentrated in `rag-production-kit`, `mcp-server-cookbook`, `llm-eval-harness`, and `llm-cost-optimizer`.

**Open questions / blockers:** None. Real-embedder backends (Voyage, OpenAI, Cohere) are intentionally reserved-but-not-wired; an operator implements the `Embedder` protocol locally and passes their own instance via the library API until those integrations land.

**Next session:** prompt-regression-suite has zero open issues. Loop to a different portfolio repo, or schedule operator follow-ups for Voyage/OpenAI/Cohere embedder integrations.

## 2026-05-18 — Issue #10: Per-snapshot tolerance override
**Duration:** ~30 min · **Branch:** `session/2026-05-18-1607-issue-10` · **PR:** [#11](https://github.com/jt-mchorse/prompt-regression-suite/pull/11) (ready)

- Added an optional `Snapshot.tolerance: float | None` field that pins the cosine threshold for a single snapshot, overriding the per-run `--threshold` flag. When unset, the per-run default applies — every existing fixture round-trips byte-stably.
- `diff_response` now resolves the effective threshold from the snapshot first, falling back to the kwarg; `DiffResult.threshold` carries the value actually applied so HTML reports and PR-comment surfaces never lie about which bar a verdict was computed against. A note is appended to `DiffResult.notes` whenever the snapshot's tolerance differs from the run-level threshold, so the audit trail is explicit.
- Shipped `examples/snapshots/creative_kite_v1.yml` with `tolerance: 0.75` and an explanatory `notes:` line as a worked example of when to lower the bar (creative-writing prompt + high-temperature sampler).

**Why this work, this session:** Every original `priority:high` issue is closed. The remaining cluster of operator pain is the "real suites mix tight extraction prompts with loose creative prompts" case where one global threshold is wrong for at least one cluster — and the schema already supports the field naturally via the D-002 dataclass pattern. Low-risk, high-leverage extension.

**Open questions / blockers:** None — PR ready for review.

**Next session:** Move to next zero-open-issue repo in build sequence (rag-production-kit per §8 dependency order).

## 2026-05-18 — Issue #12: snapshot test for `docs/regression_demo.html`
**Duration:** ~20 min · **Branch:** `session/2026-05-18-1927-issue-12`

- Added `tests/test_regression_demo_snapshot.py` (2 tests). The first runs `render_regression_demo.main(... --no-screenshot)` against a `tmp_path` and asserts byte equality with the committed `docs/regression_demo.html`. The second checks the synthetic-disclosure framing ("across model versions") survives — a light belt-and-braces test against a future refactor that drops the disclosure language.
- The existing `test_render_regression_demo.py` covered the diff math and the structural shape of the HTML, but didn't lock the committed file. A tweak to a constant or title would have passed every test while quietly desyncing the README's Demo link from the live script.
- Verified the failure path by tampering the title string in `scripts/render_regression_demo.py`; the snapshot fired with the regen hint visible. Restored the file.

**Why this work, this session:** Same hygiene pattern landed today in `llm-cost-optimizer` (lock the committed `docs/savings.{json,md}` and README table to bench output). The handoff §10 commits the portfolio to "no fabricated benchmarks" / "no fabricated demo"; snapshot tests are the enforcement mechanism for both.

**Open questions / blockers:** None — PR ready for review.

**Next session:** Continue the multi-issue loop; next build-sequence repo is `rag-production-kit`.
