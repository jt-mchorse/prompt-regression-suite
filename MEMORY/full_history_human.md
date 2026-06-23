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

## 2026-05-23 — Architecture-doc active-decision-range axis + 7-decision backfill (#26)

**Duration:** ~18 min. **Issue:** [#26](https://github.com/jt-mchorse/prompt-regression-suite/issues/26). **PR:** [#27](https://github.com/jt-mchorse/prompt-regression-suite/pull/27).

Eighth of twelve repos to ship the active-decision-range upper-bound axis. `docs/architecture.md` had **zero** D-NNN citations before this PR — all 7 active non-baseline decisions were governing real shipped surfaces (dataclasses-not-pydantic, inline embedding in YAML, two-channel ANDed diff, Embedder Protocol, embedder model-name refusal, single-file no-JS HTML, honestly-labeled synthetic demo) but none were cited inline. Backfilled. Tamper-verified three axes.

**Why this work, this session:** Fourth issue in today's multi-issue loop. Pattern is rolling cleanly across the Python half of the portfolio — three of the four backfilled-on-first-run repos this session (vector-search-at-scale, prompt-regression-suite, plus partial backfill in llm-eval-harness) caught real omissions the first time the test ran.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Apply same pattern to `agent-orchestration-platform` (last remaining arch-doc test lacking the D-axis).

## 2026-05-23 — 60-second demo capture script (#15, AC3 of 3)

**Duration:** ~25 min. **Issue:** [#15](https://github.com/jt-mchorse/prompt-regression-suite/issues/15). **PR:** [#28](https://github.com/jt-mchorse/prompt-regression-suite/pull/28).

Third issue in the day-session multi-issue loop, after [`llm-eval-harness#33`](https://github.com/jt-mchorse/llm-eval-harness/pull/33) and [`llm-cost-optimizer#29`](https://github.com/jt-mchorse/llm-cost-optimizer/pull/29). Three stages match the three sub-flows the issue specified:

- **STAGE 1 (auto, hermetic).** `scripts/capture_demo.py` calls `render_regression_demo.main(["--out-html", <tmp>, "--no-screenshot"])` in-process so the recording shows the synthetic regression report being regenerated under controllable conditions. The committed `docs/regression_demo.html` is **not** clobbered — a separate test (`test_capture_demo_does_not_clobber_committed_html`) asserts the committed file's bytes are unchanged after running.

- **STAGE 2 (browser).** `webbrowser.open()` on the fresh HTML so the rendered side-by-side diff + slot delta table appears in the operator's pre-positioned tab. `--no-open` suppresses for CI.

- **STAGE 3 (auto, hermetic).** Subprocess `python -m prompt_regression.cli diff --snapshot examples/snapshots/creative_kite_v1.yml --candidate <divergent-text> --threshold 0.9 --format text`. The **kite** snapshot is used (not refund-window) because it ships embedded with `hash-embedder-128d-ngram2`, matching the CLI's default `--embedder hash`. The refund-window snapshot was embedded with `text-embedding-3-small-truncated-8d`, which trips the D-006 embedder-model-vs-snapshot guard and demands a `--force-embedder` override — that would have made the stage non-hermetic-by-default. The kite-snapshot path keeps the recording reproducible with no override flags. The CLI exits **1** on the failing diff; the capture script treats that as the visible demo outcome.

`tests/test_capture_demo_smoke.py` adds three tests under the same hermetic contract as `tests/test_render_regression_demo.py`. Pass count: 151 → 154.

**Why this work, this session:** Third loop iteration. AC3 is the only Claude-actionable row across the seven `[demo]` issues in the portfolio; this PR moves issue #15 from 0/3 to 1/3 and gives the remaining two demo issues (rag-production-kit #25 and mcp-server-cookbook #16) a third worked example to mirror.

**Open questions / blockers:** AC1 + AC2 are operator-only (screen recorder + README embed). The PR is ready for review on AC3 standalone — issue #15 stays open until JT records.

**Next session:** Two remaining repos with AC3 still open — `rag-production-kit` #25 (build-sequence pos 4) and `mcp-server-cookbook` #16 (pos 10). Build-sequence picks rag-production-kit next.

## 2026-05-24 — Issue #29: `prompt-snap run --format html --out` for direct CI HTML artifacts

**Duration:** ~30 min. **Issue:** [#29](https://github.com/jt-mchorse/prompt-regression-suite/issues/29). **Branch:** `session/2026-05-24-0324-issue-29`.

`prompt-snap run` supported `--format text|json` only, even though `render_report()` was a public surface (#3) and the HTML report is the repo's headline deliverable. CI that wanted an HTML artifact had to detour through the Python API — reconstruct a `ReportEntry` list, call `render_report`, write to file — instead of running the CLI as one shell line.

Added `html` to `--format` and a generic `--out <path>` flag (which now works for every format, not just HTML). The HTML path reuses the library-level `render_report` directly, so the CLI is dispatch only. A guard refuses `--format html` without `--out` and exits 2 with a clear stderr message — mirrors the `update --force` loud-failure pattern; dumping a multi-KB HTML payload into a terminal is a UX bug we'd rather refuse than commit. Renamed `_print_text_table` to `_format_text_table` so it returns a string instead of printing — that lets the dispatch to stdout-vs-file be uniform across all three formats.

Skipped entries (no candidate supplied) don't have a `DiffResult` and are intentionally omitted from the HTML report; one of the five new tests pins that behavior. The other four cover the html-without-out error path, HTML written to a nested tmpdir asserting `<!doctype html>` + inline styles + per-snapshot anchors, and `--out` parity for text and json.

The README's HTML-report section gains a one-line CLI alternative directly under the existing Python snippet — the Python stays as the library entry point.

**Why this work, this session:** Third issue in the night-session multi-issue loop after `llm-eval-harness` #34 and `llm-cost-optimizer` #30. All three are surface-parity CLI fixes — same shape of work, different repos. The pattern surfaces by reading each repo's CLI source for "advertised in README but missing as a flag" gaps.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the loop to build-sequence #4 (`rag-production-kit`). Survey its CLI / scripts surface for similar gaps.

## 2026-05-24 — Issue #31: `diff` gains `--format html` and `--out` for parity with `run`

**Duration:** ~15 min. **Issue:** [#31](https://github.com/jt-mchorse/prompt-regression-suite/issues/31). **Branch:** `session/2026-05-24-1519-issue-31`.

`prompt-snap diff` had `--format text|json` and stdout-only output, while sibling `run` (post-#29) already supported `text|json|html` with a generic `--out PATH` and a loud-failure stance for `--format html` without `--out`. A user wanting a one-snapshot HTML report had to glue `render_report` together by hand or fabricate a one-row candidates JSONL to detour through `run`. This PR finishes the parity.

`_diff_command` refactored from inline `print()` calls to a string-builder + shared `--out`-or-stdout sink, mirroring `_run_command`. The HTML branch constructs a single-entry `ReportEntry` list and calls `render_report()` — the same call `_run_command` uses. The loud-failure guard for `--format html` without `--out` is the same stderr message shape #29 introduced for `run` (reused verbatim, not a new policy). Inline text rendering extracted into `_format_diff_text` so the sink decision lives in one place and the text shape is exercisable from tests without `capsys`.

New `tests/test_cli_diff_html.py` (5 tests): html-without-out exit-2 with stderr message; html `--out` happy path against a nested tmpdir (asserts doctype + snapshot anchor); text `--out` with stdout silent; json `--out` with parseable JSON body; stdout-only regression guard for the no-`--out` text path. Tail: 161 / 161 pass, ruff clean.

**Why this work, this session:** Second Phase B+C target of a 180-min day session, after `llm-eval-harness` #37 brought `list` in line on the `--out` axis. This is the same shape of fix but for a `--format html` axis on this repo. After both: every public CLI subcommand on `llm-eval-harness` and `prompt-regression-suite` accepts `--out` and the full set of advertised formats, with no surprise terminal dumps and no shell-redirect detours.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the day-session loop. Build-sequence position #5 (`embedding-model-shootout`), #6 (`chunking-strategies-lab`), or #10 (`mcp-server-cookbook`) are good next pick-ups. Survey their CLIs for the same parity shape; if nothing surfaces, drop to the per-script defaults-bug audit pattern that landed `llm-cost-optimizer` #31 this morning.

## 2026-05-24 — Issue #33: Snapshot.from_dict raises SnapshotValidationError for missing id
**Duration:** ~20 min · **Branch:** `session/2026-05-24-issue-33`

- `Snapshot.from_dict` at `schema.py:255` documents itself as raising `SnapshotValidationError` for any structural problem, and `load_snapshot` in `io.py` propagates that contract upward. The implementation wrapped only the nested-section constructors inside `try / except KeyError`; the top-level `data["id"]` read at line 276 sat outside. A snapshot YAML missing `id` surfaced as a raw `KeyError("id")`, breaking the docstring contract and any loader that catches only the canonical exception type.
- Hoisted `snapshot_id = data["id"]` inside the existing try block so the same `except KeyError as e: raise SnapshotValidationError(...)` arm catches the missing-id case with the same `Snapshot missing required section: 'id'` message shape. Inline comment documents why all required top-level reads must stay inside the try.
- Converted the missing-section test coverage into a `@pytest.mark.parametrize` lock over `("id", "prompt", "response_shape", "canonical")` — every required top-level key now provably surfaces the same exception type, and any future required field gets the same lock for free. The original `_missing_section` test stays as a focused regression pin on `canonical`.

**Why this work, this session:** Asymmetric existing coverage (only `canonical` tested for missing-top-level-key) hid the bug. Sister to today's `llm-cost-optimizer` #32 (`UncertaintyRouter` signal-name uniqueness) and `llm-eval-harness` #38 (`diff_runs` negative-threshold-drop). Three repos in a row in the same day-session, same family — "the public boundary's contract isn't enforced uniformly across all inputs."

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the day-session loop. With three iterations behind, time check before picking the next. `rag-production-kit` (build sequence #4) is the next reasonable target.

## 2026-05-25 — Issue #35: diff_response validates warn_band upper bound at effective_threshold
**Duration:** ~25 min · **Branch:** `session/2026-05-24-issue-35`

- `diff_response` at `prompt_regression/diff.py:362-363` validated `warn_band` only as `>= 0`. The cosine warn-band logic at `:387` is `cosine_score >= max(0.0, effective_threshold - warn_band)` — so when `warn_band > effective_threshold`, the warn floor silently clamps to `0.0` and every sub-threshold cosine becomes `"warn"` indistinguishably. The fail/warn distinction on the cosine channel collapses without any signal. Same harm class as D-006's "suite looks fine but a class of regressions can no longer trip the verdict."
- Added an upper-bound guard immediately after the existing `warn_band < 0` check: `warn_band > effective_threshold` raises `ValueError("warn_band must be <= effective_threshold ({effective_threshold}); got {warn_band}")`. Inclusive at the boundary — `warn_band == effective_threshold` is accepted (warn floor exactly `0.0`, which is meaningful). The guard validates against the *effective* threshold (snapshot.tolerance override per #10), not the kwarg, so a tight-tolerance snapshot with a loose default `warn_band` fails loud rather than slipping by.
- Nine new tests in `tests/test_diff.py` under a `#35` comment header: parametrized rejection over `[0.51, 0.6, 0.9, 1.01, 5.0]` with `threshold=0.5`; parametrized acceptance over `[0.0, 0.25, 0.5]` (strict, mid, equal-to-threshold); one tolerance-override test that pins the "effective, not kwarg" semantics. Full suite 174/174 (was 165 after #33).

**Why this work, this session:** First Phase B+C target in the 360-min night session. Continues the contract-tightening sweep that landed across the portfolio on 2026-05-24 in PRs #35 (cost-optimizer), #37 (rag-kit), #41 (eval-harness), #28 (chunking-lab), #30 (emb-shootout), #28 (vector-search). Same harm shape (silent degeneracy from operator-supplied numeric input out of contract range), same fix shape (validate at construction/entry, loud error).

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the loop. `agent-orchestration-platform` (build seq #9) and `mcp-server-cookbook` (build seq #10) are the natural next pickups — both have zero open issues and haven't been touched in the contract-tightening sweep yet.

## 2026-05-26 — Issue #37: HashEmbedder.ngram + CanonicalResponse.embedding finiteness extension
**Duration:** ~30 min · **Branch:** `session/2026-05-25-2100-issue-37`

- `HashEmbedder.__init__(ngram)` at `prompt_regression/diff.py:61` upgraded from sign-only `ngram < 1` to the portfolio positive-int contract (`not isinstance(int) or isinstance(bool) or <= 0`). Closes three silent failure modes — `ngram=True` silently bound and made `model_name="hash-embedder-128d-ngramTrue"` which tripped the D-006 model-name-mismatch refusal at diff time *far* from the construction bug; `ngram=1.5/2.0` silently bound, then `range(len - ngram + 1)` raised `TypeError` deep in `embed()`; `ngram=NaN/Inf` silently bound (NaN < 1 is False), surfaced as range() errors at embed time. New error shape `"ngram must be a positive integer; got {ngram!r}"` is uniform with the rag-production-kit #43 and embedding-model-shootout #36 sweeps.
- `CanonicalResponse.embedding` element loop at `prompt_regression/schema.py:178-183` extended with `math.isnan(v)` / `math.isinf(v)` rejection per element, kept *below* the existing `bool` / non-numeric reject so the upstream diagnostic shape stays stable. Index-bearing error `"CanonicalResponse.embedding[{i}] must be a finite number; got {v!r}"`. Closes the silent failure where a YAML snapshot with `embedding: [.nan, ...]` (which YAML parses as `math.nan`) loaded successfully, propagated NaN through `cosine()` (dot, na, nb all NaN), and surfaced as verdict `"fail"` with no diagnostic about the malformed source — same harm class as D-006.
- 33 new parametrize tests in `tests/test_deferred_validation_sweep.py`: HashEmbedder.ngram 15-value reject matrix plus 5-value acceptance plus default-ngram pin; CanonicalResponse.embedding parametrized over `(bad ∈ {NaN, +Inf, -Inf}) × (position ∈ {head, middle, tail})` plus index-in-error pin plus bool-precedes-finiteness pin plus a finiteness-NOT-non-negativity pin (negative components in a unit vector remain accepted). Full suite 174 → 207. Ruff clean.

**Why this work, this session:** Second Phase B+C target in the 360-min night session. Direct continuation of today's portfolio-wide validation sweep — Phase A rescued and merged four format-failing PRs (`rag-production-kit#43`, `embedding-model-shootout#36`, `llm-eval-harness#45`, `llm-eval-harness#47`) earlier in this session; the prompt-regression-suite gaps were the unexamined symmetric sites in this repo. Picked via build-sequence order (#3) among repos not yet targeted in this night's sweep.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Continue the multi-issue loop. `chunking-strategies-lab` (build seq #6) and `vector-search-at-scale` (build seq #7) are the natural next pickups — both had only one PR earlier today and may have un-swept construction sites in the same shape.

## 2026-05-26 — Issue #39: Atomic snapshot saves and --out writes (the load-bearing repo for this arc)
**Duration:** ~30 min · **Branch:** `session/2026-05-26-1523-issue-39`

- `save_snapshot` is the load-bearing helper for the entire repo — round-trip identity (`load_snapshot(save_snapshot(s)) == s`) is the documented contract that the diff layer relies on. Pre-fix it used `p.open("w") + yaml.safe_dump(stream=f)`, which is non-atomic: SIGINT during a long-running `prompt-snap update --force` invocation (the very command meant to be safe to re-run) could leave the snapshot YAML zero-length or partial.
- Added `atomic_write_text(path, text)` to `prompt_regression/io.py` — natural home, since the module already owns snapshot file IO. Same shape as the helpers in `llm-eval-harness/eval_harness/cli.py` (#48) and `llm-cost-optimizer/scripts/_io.py` (#42), filed and merged earlier this session.
- `save_snapshot` now renders YAML to a string via `yaml.safe_dump(payload, None, ...)` (yaml returns a string when stream is None) and routes through the helper, preserving `sort_keys=False` / `default_flow_style=False` / `allow_unicode=True` flags. The three other call sites — `cli.py:246` (`prompt-snap run --out`), `cli.py:373` (`prompt-snap diff --out`), `scripts/render_regression_demo.py:183` (`docs/regression_demo.html`) — also route through it.
- 10 new tests in `tests/test_atomic_write.py`: six unit tests on the helper (happy path / parent-dir create / overwrite / `os.replace`-raises destination-absent / temp-cleanup-on-failure / overwrite-fails destination-unchanged) plus four integration tests. The load-bearing integration test is `test_save_snapshot_overwrite_failure_preserves_existing_snapshot`: save a snapshot, capture bytes, mutate the in-memory snapshot, simulate `os.replace` failure on second save, assert disk bytes are bitwise identical to the pre-failure save **and** `load_snapshot` still returns the original (not the mutated copy). The other three integration tests cover `save_snapshot` first-write failure (destination absent), `prompt-snap run --out` failure, and `prompt-snap diff --out` failure. Full suite 217 → 227. Lint + format green.

**Why this work, this session:** Third Phase B+C target in today's 180-min DAY session, third PR in the portfolio-wide atomicity arc. `llm-eval-harness#48` opened the arc; `llm-cost-optimizer#42` propagated the pattern to a second repo; this repo's load-bearing surface is the YAML snapshot itself, so the harm class lands at the most consequential layer of the repo (corruption breaks the round-trip-identity contract the entire diff layer rests on).

**Open questions / blockers:** none — PR ready for review.

**Next session:** `rag-production-kit` cost-telemetry rollup is the natural fourth — same pattern, fourth repo. Or pivot to a different harm class on a TypeScript repo. Three consecutive same-shape PRs in one session is plenty of compounding evidence that the helper shape is settled.

## 2026-05-26 — Issue #41: README decision-range upper-bound lock
**Duration:** ~7 min · **Branch:** `session/2026-05-26-2324-issue-41`

- Added `tests/test_readme_decision_range.py` with the active-decision-range upper-bound invariant.
- Bumped README's architecture-section to cite `D-002…D-008`.

**Why this work, this session:** Propagation 3 of 10 of the cross-portfolio drift class authored in chunking-strategies-lab.

**Open questions / blockers:** none.

**Next session:** Continue propagation to rag-production-kit (next per build sequence).

## 2026-05-27 — Issue #43: drop stale "· this PR" from four README section headers + banned-phrase lock
**Duration:** ~15 min · **Branch:** `session/2026-05-27-0321-issue-43`

- Four section headers in `README.md` still carried pre-shipping framing ("· this PR") for surface that's been shipped for weeks: `Diff layer (#2 · this PR)`, `HTML report (#3 · this PR)`, `Regression demo (#4 · this PR)`, `CLI: prompt-snap (#5 · this PR)`. Same drift class `docs/architecture.md` had at issue #24, which seeded that file's `BANNED_PHRASES` lock at `tests/test_architecture_doc.py:63`.
- Rewrote the four headers to steady-state form (drop the suffix).
- New lock: `tests/test_readme_banned_phrases.py` with `BANNED_PHRASES = ("this pr",)` — pytest-parametrized case-insensitive substring match against `README.md`, plus a hard-pin test asserting the tuple is exactly what got committed (prevents a future loose edit from silently weakening the guard). Mirrors the architecture-doc lock's tuple-pin shape but applies it to README rather than `docs/architecture.md`.
- Tuple intentionally minimal — only `"this pr"` because that's the only drift this README actually had; speculative additions would be premature.
- Verified: lock fires loudly on a synthetic reintroduction of one suffix (single failure with the assertion's "rewrite to steady-state form" message); restored README passes; full suite **221/221** pass.

**Why this work, this session:** Iteration 3 of an autonomous NIGHT session. Validation arc is saturated; per-repo doc-hygiene gaps are now where the high-ROI quick wins live.

**Open questions / blockers:** none — PR ready for review.

**Next session:** Loop continues across portfolio repos this NIGHT session.

## 2026-05-27 — Issue #45: CONTRIBUTING.md cadence-wording propagation
**Duration:** ~3 min · **PR:** #46

- Replaced pre-D-008 `~60-minute session cap` line with D-008 (180/360 min, multi-issue loop) and D-004 (Phase A PR auto-merge) wording, matching the bootstrap template post-portfolio-ops#3.

**Why this work, this session:** Iteration in the autonomous NIGHT session propagation arc for portfolio-ops#3.

**Open questions / blockers:** none.

**Next session:** continue portfolio propagation.

## 2026-06-01 — Issue #47: `prompt-snap stats` directory-wide summary
**Duration:** ~45 min · **Branch:** `session/2026-06-01-1533-issue-47`

- Added `prompt_regression/stats.py`: `collect_stats(directory) -> StatsReport` walks the same `*.yml` / `*.yaml` glob `prompt-snap run` uses, returns a frozen `StatsReport` with per-`prompt.model` / per-`canonical.embedding_model` / per-`schema_version` / per-`structured_slots`-count `HistogramEntry` tuples (descending by count, alphabetical tiebreak so the JSON is deterministic across Python builds), plus a `ToleranceDistribution` summary (count_default + count_explicit + count_always_pass + min/median/max over explicit values, `None` when no explicit tolerance is present so the dict shape is well-defined on directories that don't use the per-snapshot override).
- Wired `prompt-snap stats DIRECTORY [--json]` in `prompt_regression/cli.py`. Exit 0 / 2 matches the `run` / `diff` / `update` convention. `StatsError` carries the two failure modes (missing directory, empty directory) so the CLI can render a clear `error:` line on stderr and exit cleanly.
- Re-exported `StatsReport`, `StatsError`, `ToleranceDistribution`, `HistogramEntry`, `collect_stats`, `render_summary` from `prompt_regression/__init__.py` so external consumers can build their own surfaces without the CLI module dep.
- 11 new tests in `tests/test_stats.py` cover the committed-examples happy path, mixed-tolerance distribution math (synthetic directory: default + 0.7 + 1.0 → min=0.7 / max=1.0 / median=0.85 / always_pass=1), histogram descending-then-alphabetical ordering (model-a×2, model-b, model-c → [(a,2),(b,1),(c,1)]), missing- and empty-directory error paths, `to_dict` shape lock, `render_summary` surface, CLI text + json + missing-dir end-to-end, and a glob-parity lock between the stats walker and `prompt-snap run`'s globs.
- README CLI bullet (#5) extended; `docs/architecture.md` Layer 4 CLI block + cross-cutting surface section name the new shape. `test_architecture_doc.py::KNOWN_SHIPPED_ISSUES` + its hard-pin assertion both bumped to include 47. The `test_readme_defaults_snapshot.py` lock caught the README drift on first pytest run — validation arc is doing its job.

**Why this work, this session:** Third DAY-session iteration of 2026-06-01. Build sequence selected `prompt-regression-suite` next after `llm-cost-optimizer`. All 12 portfolio repos sit at zero open priority:high; the right pattern when there's no actionable backlog is the build-sequence "file a real feature issue per §2 spec" fallback. The CLI's `run/update/diff` covers per-snapshot regression signal but nothing surfaced aggregate population shape — useful for any team running a regression suite over dozens of snapshots before a model upgrade.

**Open questions / blockers:** none — pytest 256 pass, ruff clean, live CLI smoke (`prompt-snap stats examples/snapshots`) returns the expected 2-snapshot summary with the 0.75 explicit tolerance from `refund_window_v1.yml` visible in the tolerance line.

**Next session:** a natural follow-up would be `prompt-snap stats --since DAYS` so an operator can isolate snapshots created in the last week (the `created_at` field is already on every snapshot). Out of scope for #47; would be a clean follow-up.

## 2026-06-01 — Issue #49: `prompt-snap validate` subcommand
**Duration:** ~40 min · **Branch:** `session/2026-06-01-1926-issue-49`

- New module `prompt_regression/validate.py` with `validate_snapshots(directory) -> ValidationReport`. Walks every snapshot file under the dir (same globs the runner uses) in *collecting* mode and returns one `ValidationFinding` per malformed file plus one per duplicate-id collision. Finding codes `parse | schema_version | schema | duplicate_id | empty`. The `schema_version` code is split out from the general `schema` bucket so migration tooling can route on the code without parsing prose, and `duplicate_id` catches the silent key-collision that the runner's `_load_candidates` lookup would otherwise swallow.
- `prompt-snap validate <dir>` CLI subcommand wired into `cli.py`: per-finding stderr lines with the relative file path, a one-line totals row on stdout, `--json` toggle to emit `to_dict()`. Exit codes 0/1/2 (clean / findings / missing-dir-or-IO) matching `eval-harness validate` and `scripts/audit_phase_a.py` so CI consumers can chain validators uniformly.
- 17 new tests in `tests/test_validate.py`: glob parity lock (validator must see the same files the runner sees), happy path against `examples/snapshots/`, each finding code (non-mapping top-level YAML, decode error, schema_version mismatch, schema missing-required-field, duplicate_id with shadow-row exclusion locked, empty dir), missing-dir and file-not-dir both raising `FileNotFoundError`, `ValidationReport.to_dict` shape lock + frozen-instance check, CLI end-to-end across clean / fail / `--json` / missing-dir.
- README "What this is" CLI bullet (#5) extended to `prompt-snap run | update | diff | stats | validate` with an inline description of the use case (caught by the `test_readme_subcommand_bullet_matches_live_argparse` snapshot test on first pytest run — validation arc keeps catching drift). `docs/architecture.md` gains a CLI shape line and a Cross-cutting Surfaces entry pairing the validator with `stats` and `run`. `tests/test_architecture_doc.py::KNOWN_SHIPPED_ISSUES` extends to `(..., 47, 49)`.

**Why this work, this session:** Iteration 2 of today's DAY session. Iteration 1 closed llm-eval-harness#58 (`validate --calibration`). The natural Phase B follow-on in this repo is the same pattern: `prompt-snap run` aborts on the first bad snapshot inside its loop, `stats` silently swallows load errors, no dedicated pre-flight existed. Filing #49 and shipping it inside the day session keeps the validation arc landing across the portfolio.

**Open questions / blockers:** none — full pytest pass, ruff check + format clean, live CLI smoke against `examples/snapshots`, missing path, and `--json` all behave as expected.

**Next session:** the validator currently treats embedding vectors as opaque lists in the schema check. A future hardening could cross-check dimensionality consistency across the dir (e.g., flag a snapshot whose canonical vector has a different length than its siblings under the same embedder). Out of scope here; would be a clean follow-up if embedding-shape drift ever surfaces in practice.

## 2026-06-02 — Issue #51: explicit .to_dict() field contracts
**Duration:** ~30 min · **Branch:** `session/2026-06-02-0348-issue-51`

- Replaced `dataclasses.asdict`-based JSON shapes with explicit field-by-field `.to_dict()` methods on **seven** dataclasses across `diff.py` and `schema.py`:
  - `SlotDelta` (4-field), `SemanticCategoryScore` (2-field), `DiffResult` (8-field, nests `slot_deltas` / `semantic_category_scores`).
  - `Prompt` (6-field), `ResponseShape` (2-field), `CanonicalResponse` (3-field), `Snapshot` (8-field, nests `prompt` / `response_shape` / `canonical`).
- `cli.py` `_serialize_diff` collapses to `result.to_dict()` — the field-by-field contract now lives on `DiffResult` itself. Dropped the `asdict` import; no `dataclasses.asdict` reference remains in `diff.py`, `schema.py`, or `cli.py`.
- Shallow-copy safety: `extra` mapping in `Prompt`, embedding list in `CanonicalResponse`, lists/mappings in `ResponseShape` — all copied so caller mutation of the returned dict can't bleed back into the frozen dataclass. Three guard tests pin this.
- `Snapshot.to_dict` preserves the existing `None`-drop tidy-up for `notes`/`tolerance` so committed `snapshots/*.yaml` stay clean (no explicit `notes: null` lines on snapshots that don't use them). The round-trip identity test `Snapshot.from_dict(s.to_dict()) == s` is preserved.
- 21 new tests (10 in `test_diff.py`, 11 in `test_schema.py`) covering per-class field-set pins, nested-shape ownership, shallow-copy safety, and the CLI acceptance regression `cli._serialize_diff(result) == result.to_dict()`. Full suite 268/268 pass (was 258). Ruff check + format clean.
- `docs/architecture.md` Layer 2 section gains a paragraph citing #51 alongside the four sister-repo PRs in the same observability-parity arc. `KNOWN_SHIPPED_ISSUES` arch-doc pin extended from `(1,2,3,4,5,10,47,49)` to include `51`.

**Why this work, this session:** Iteration 5 of the night session loop. Audit of the recently-touched Python repos surfaced `prompt-regression-suite` as the only one in the observability-parity arc (closed across `python-async-llm-pipelines`, `rag-production-kit`, `llm-cost-optimizer` ×2, and `vector-search-at-scale` earlier tonight) with remaining `asdict` reliance — both in `cli.py`'s `_serialize_diff` and `schema.py`'s `Snapshot.to_dict`. Closing both saturates the Python side of the arc at five repos.

**Open questions / blockers:** none — ready for review.

**Next session:** Future iterations should pivot to either operator-blocked items (demo-capture issues, trending workflow secrets) or look for novel parity opportunities outside the observability-parity arc, which is now saturated across all Python JSON-emitting repos.

## 2026-06-17 — Issue #53: Workflow YAML-parseability lock
**Duration:** ~8 min · **Branch:** `session/2026-06-17-1921-issue-53`

Added `tests/test_workflows_yaml_parseable.py` (3 tests for `ci.yml`).
`pyyaml` is already a runtime dep, so no `pyproject.toml` change
needed.

**Why this work, this session:** Sixth hop of the `portfolio-ops#30`
propagation arc.

**Open questions / blockers:** none — PR #54 open.

**Next session:** continue propagation to the remaining 6 repos.

## 2026-06-17 — Issue #55: timeout-minutes guard for ci.yml
**Duration:** ~12 min · **Branch:** `session/2026-06-17-2326-issue-55`

- `timeout-minutes: 15` on each ci.yml job.
- `tests/test_workflows_timeout_minutes.py` — 10 new tests, same shape as the canonical lock.

**Why this work, this session:** third propagation of `llm-eval-harness#62` in the multi-issue day-session loop, after llm-cost-optimizer#58.

**Open questions / blockers:** none.

**Next session:** continue propagation across remaining 9 repos.

## 2026-06-18 — Issue #57: concurrency guard + lock test
**Duration:** ~9 min · **Branch:** `session/2026-06-18-1528-issue-57`

- Added top-level `concurrency:` to `ci.yml`.
- Copied lock test from llm-eval-harness; docstring origin updated.

**Why this work, this session:** sixth per-repo hop in the
concurrency-lock arc; first non-tier repo after the priority tier
completed 5/5 this session.

**Open questions / blockers:** none. Test count 278 → 285.

**Next session:** continue propagation to remaining 6 repos.

## 2026-06-19 — Issue #59: prompt-snap validate --out for sink-parity
**Duration:** ~22 min · **Branch:** `session/2026-06-19-0327-issue-59`

- Added `--out PATH` to `prompt-snap validate` so its output (human
  summary or `--json` payload) atomic-writes to disk instead of stdout.
  Third hop in the validate-CLI sink-parity propagation arc (after
  llm-eval-harness#66 and chunking-strategies-lab#45).
- `_validate_command` builds the rendered string once, then routes
  through `prompt_regression/io.atomic_write_text` when `--out` is set,
  else `print(rendered, end="")`. Findings continue to print to stderr
  in human-readable mode regardless of `--out`.
- 6 new tests; README unchanged.

**Why this work, this session:** sibling-of-#66 / sibling-of-#45 propagation.
After this PR, three of the four Python validate CLIs in the portfolio
share one shape; one more hop remains (embedding-model-shootout
`emb_shootout.validate.validate_corpus`).

**Open questions / blockers:** none. 285 → 291 pytest passes. PR #60
open and ready.

**Next session:** continue the arc into embedding-model-shootout to
close it out across all four repos.

## 2026-06-22 — Issue #61: CLI — preserve per-snapshot tolerance across update
**Duration:** ~20 min · **Branch:** `session/2026-06-22-1135-issue-61`

- Found during Phase A (Explore subagent over cli/schema/validate/io/html_report after I'd cleared diff.py and stats.py): `_update_command` rebuilt the `Snapshot` on re-baseline copying every field forward except `tolerance`. Since the field defaults to `None`, `prompt-snap update --force` silently reverted an author's tuned per-snapshot threshold (issue #10) to the per-run default, quietly changing the diff verdict on subsequent runs. Reproduced 0.75 → None.
- Fix: one line — `tolerance=snap.tolerance` in the rebuild, mirroring the existing `notes` preservation.
- 2 new tests (explicit tolerance preserved; None stays None). Verified the first fails pre-fix. Suite 291 → 293, ruff clean. PR #62 ready.

**Why this work, this session:** the repo had no open priority issues (saturated); this was a real, high-confidence data-loss bug in a user-facing CLI command, found by reading the update path. Higher value than a synthetic fill.

**Open questions / blockers:** none.

**Next session:** no specific lead — diff/stats/cli/schema are well-hardened, and the other Snapshot fields are all verified to be copied on update. If a future session needs work here, the HTML report escaping path and the validate module are the remaining surfaces to audit.

## 2026-06-23 — Issue #63: empty candidate silently skipped (missed regression)
**Duration:** ~20 min · **Branch:** `session/2026-06-23-0336-issue-63`

- Fixed a silent-regression-escape in `prompt-snap run`. The candidate lookup used `candidates.get(rel) or candidates.get(snap.id)`; an empty-string candidate (the model returned nothing — itself a severe regression) is falsy, so the `or` fell through and the snapshot was counted "skipped", the run exited 0, and CI went green on the exact failure the suite exists to catch. The loader already stored `""`, so the value was present — the `or`-chain discarded it.
- Switched to explicit key-membership (rel precedence preserved) so a present empty candidate is diffed to a `fail`. Added a `--format json` CLI test (verdict fail, exit 1). Red pre-fix, green post-fix. Suite 293 → 294, ruff clean.

**Why this work, this session:** found by the night session's Phase A dogfood wave; a real correctness/safety bug on the primary CI entry point, where the most severe regression was passing silently.

**Open questions / blockers:** none.

**Next session:** the sibling `or` in `_load_candidates`'s key resolution is safe (keys are non-empty by validation) and was left out of scope.
