# Session History (human-readable)

Chronological log of work sessions. Most recent first below the divider.

---

## 2026-05-19 — Issue #17: snapshot lock README numeric/identifier defaults to source constants
**Duration:** ~28 min · **Branch:** `session/2026-05-19-1921-issue-17` · **PR:** [#18](https://github.com/jt-mchorse/prompt-regression-suite/pull/18) (ready)

- Added `tests/test_readme_defaults_snapshot.py` (4 tests) closing the orthogonal axis the existing demo-HTML + CLI tests don't cover: README claims that quote source constants (`threshold=0.85` ↔ `DEFAULT_THRESHOLD`, pip extras), the console-script name (`prompt-snap` ↔ pyproject `[project.scripts]`), and the "What this is" subcommand bullet (`prompt-snap run | update | diff` ↔ live argparse).
- Source is the truth — every failure message tells the operator to update the README to match the new live value. The threshold test asserts the README's two threshold mentions agree with each other *before* comparing to source (so a half-updated README fails loudly with a "pick one and align both anchors" message rather than silently picking one over the other). The subcommand-surface test discovers live names via `build_parser()._actions` choices rather than parsing `--help` text, so it's robust to argparse formatting changes.
- Tamper-verified 3 of 4 (`DEFAULT_THRESHOLD` 0.85→0.75, pyproject `prompt-snap → prompt-snap-renamed`, README dropping the `diff` subcommand) — each fires with the source symbol referenced in the failure message; revert restores green. Full suite 125/125 (was 121); ruff check + format clean.

**Why this work, this session:** Phase A repo selection ran with `priority:high` empty across the portfolio and the existing `priority:med`/`priority:low` issues either had open PRs against them or required screen capture (demo issues). Filing #17 + working it kept the portfolio's snapshot wave honest by closing the orthogonal source-constants gap — sister to the same pattern landed in llm-eval-harness (#22→#23) and llm-cost-optimizer (#20→#21) earlier in the same session.

**Open questions / blockers:** None.

**Next session:** Continues with whichever repo Phase A selection picks; remaining defaults-snapshot candidates in the portfolio are `agent-orchestration-platform` (model IDs, eval extras) and any repo that still quotes source constants in its README without a snapshot lock.

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

## 2026-05-19 — Issue #19: Public-surface snapshot test
**Duration:** ~20 min · **Branch:** `session/2026-05-19-2336-issue-19` · **PR:** [#20](https://github.com/jt-mchorse/prompt-regression-suite/pull/20) (ready, CI green, merging)

- Issue filed in-session as the third instance of the public-surface snapshot pattern in today's portfolio loop (after `llm-eval-harness` #25 and `llm-cost-optimizer` #23, both merged earlier). Same risk class: the README quotes three `from prompt_regression import …` library-use snippets but no test locked the shape, so a future submodule rename would silently drop names.
- Adapted the pattern for *relative* imports: `__init__.py` uses `from .diff import …` rather than absolute `from prompt_regression.diff import …`, so the AST walk filters on `ImportFrom.level >= 1` instead of a module-name prefix. Otherwise the same four axes: `__all__` round-trip, all-bound-non-none, README-regex auto-discovery + guard, one anchor per submodule (diff / html_report / io / schema).
- Tamper-verified 3-of-4. Full suite 135/135 (+10 new). Lint and format clean.

**Why this work, this session:** Three-strikes confirms the pattern. Going forward the snapshot can land in the remaining six Python repos (embedding-model-shootout, chunking-strategies-lab, vector-search-at-scale, python-async-llm-pipelines, rag-production-kit, mcp-server-cookbook's Python example) without further decision overhead — same four axes, swap the package name and the submodule anchors.

**Open questions / blockers:** None.

**Next session:** Loop to a fresh repo or wrap up the session.

## 2026-05-22 — Broaden `prompt-snap run` glob to find committed examples (#22)

**Duration:** ~25 min. **Issue:** [#22](https://github.com/jt-mchorse/prompt-regression-suite/issues/22). **PR:** TBD.

`prompt-snap run --snapshots ./examples/snapshots` exited 2 with `error: no *.snapshot.yaml files under ...` — but the directory the README quickstart sends a reader to contains two committed examples (`refund_window_v1.yml`, `creative_kite_v1.yml`). The CLI's `_SNAPSHOT_GLOB = "*.snapshot.yaml"` hard-coded one opinionated convention; the committed examples followed a different one. The README's Python API section uses the `.yml` files happily; the CLI section's example output uses `.snapshot.yaml`. Inconsistency between (a) what the README shows, (b) what's committed, and (c) what the CLI accepts.

The fix broadens `_SNAPSHOT_GLOBS` to a tuple of four patterns (`*.snapshot.yaml`, `*.snapshot.yml`, `*.yml`, `*.yaml`) — `_iter_snapshot_paths` rglob's each, dedupes via a seen-set, and sorts. The opinionated `*.snapshot.yaml` convention is still preferred for fresh projects (clearly distinguishes snapshot files from other yaml), but the bare extensions now just work for pre-existing conventions and for the committed examples. The zero-find error message now lists every glob the walker considered, so a pointed-at-the-wrong-dir caller can verify extension coverage without reading the source. Three new tests in `tests/test_cli.py` lock the surface: the walker finds both committed examples in `examples/snapshots/`, all four patterns are individually covered on a synthetic fixture, and `foo.snapshot.yaml` (which matches both `*.snapshot.yaml` and `*.yaml`) deduplicates to a single entry. The pre-existing `test_run_empty_snapshots_dir_exits_2` is tightened to assert every glob name appears in the error message.

Why prioritized: this is the sixth post-v0.1 drift fix today across the portfolio (after embedding-model-shootout #17, chunking-strategies-lab #19, vector-search-at-scale #19, python-async-llm-pipelines #21, agent-orchestration-platform #21). All six different shapes, same family — README/docs/contracts that drift from code behavior; promote to runtime + source locks so they can't drift again. Open questions / followups: none. The new globs cover both old and new naming conventions; operators choose.

## 2026-05-22 — Issue #24: architecture doc reflects all six shipped surfaces, not the snapshot-PR-only pre-shipping state

**Duration:** ~25 min. **Issue:** [#24](https://github.com/jt-mchorse/prompt-regression-suite/issues/24). **PR:** [#25](https://github.com/jt-mchorse/prompt-regression-suite/pull/25).

`docs/architecture.md` was committed alongside the snapshot-schema PR (issue #1) and never reframed when issues #2 (semantic similarity diff), #3 (HTML report), #4 (caught regression demo), #5 (CLI), and #10 (per-snapshot tolerance override) shipped. The mermaid diagram had four `:::pending` nodes (NewResp / Diff / Report / Reviewer) all describing surfaces that had been on disk and exercised by CI for months. The L17 section header said "Shipped (this PR — issue #1)" and a bottom-of-doc "Pending" section listed #2 / #3 / #4 as future work. The root README and the `docs/regression_demo.html` worked example were already correct (locked by `tests/test_readme_defaults_snapshot.py` and `tests/test_regression_demo_snapshot.py`); only `docs/architecture.md` lagged.

Rewrote the diagram so every node is `:::shipped`; the unused `classDef pending` is dropped. Each diagram node carries its origin issue annotation. Added per-layer sections for the snapshot schema (#1), the diff layer (#2 + #10 per-snapshot tolerance override), the HTML report (#3), and the CLI (#5). Added a "Cross-cutting surfaces" section listing the hygiene patterns (#12 HTML demo snapshot, #14 README pivot, #17 README defaults, #19 public surface, #22 CLI glob fix) — each is locked elsewhere but should still appear in the architecture doc as a reference for where the locks live. Replaced "Pending" with a "Where to look next" footer parallel to the rest of the portfolio.

Lock-against-drift: `tests/test_architecture_doc.py` is the fourth Python architecture-doc lock to land this session (after `embedding-model-shootout` PR #20, `vector-search-at-scale` PR #22, `llm-eval-harness` PR #30). Three invariants: path-token reachability with `<...>` / `{...}` / `*` placeholder skipping; closed-feature-issue coverage for `KNOWN_SHIPPED_ISSUES = (1, 2, 3, 4, 5, 10)` (hygiene-only #12 / #14 / #15 / #17 / #19 / #22 excluded, each locked elsewhere); banned phrases (`this pr`, `(unfiled)`, `to-be-filed`) absent. Three belt-and-braces hard-pin tests lock `BANNED_PHRASES`, `KNOWN_SHIPPED_ISSUES`, `RESOLVABLE_PREFIXES`. Tamper-verified three ways. Full suite 145/145 (was 138; +7 new). `ruff check . && ruff format --check .` clean.

Fifteenth post-v0.1 drift fix in the portfolio pattern, sixth architecture-doc lock in this session. The portfolio now has nine repos with an architecture-doc lock test. The remaining three repos with `docs/architecture.md` files (`rag-production-kit`, `agent-orchestration-platform`, `chunking-strategies-lab`, `python-async-llm-pipelines`, `llm-cost-optimizer`) are already in clean steady-state — verified earlier this session — and don't have drift to fix.

**Why this work, this session:** Loop iteration in a day session. Five architecture-doc fixes already landed today across other repos with the same shape; `prompt-regression-suite` was the last repo with verified drift. Issue #24 was filed mid-session as `priority:med` then closed in the same session per the session prompt's loop protocol.

**Open questions / blockers:** None — PR opened ready for review.

**Next session:** No remaining architecture-doc drift in the portfolio. Loop forward into another hygiene pattern or wrap session within the cap.
