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

---
## 2026-06-23 — Issue #65: dimension-mismatched embedding crashed the whole run batch
**Duration:** ~25 min · **Branch:** `session/2026-06-23-0426-issue-65`

- Fixed a batch-abort bug. The D-006 embedder guard compares only the `embedding_model` string and is dimension-blind, so a snapshot whose model name matches but whose stored vector is a different length (older build, hand-edited YAML) reached `cosine()` and raised a raw `ValueError: vector length mismatch`. In `prompt-snap run` that escaped the per-snapshot loop and aborted the whole batch.
- Added a catchable `EmbeddingDimensionMismatchError` raised in `diff_response`, handled per-row in `run` and `diff` like the model-name case. Added diff + CLI tests. Behavioral red pre-fix, green post-fix. Suite 293 → 295, ruff clean.

**Why this work, this session:** found by a different-angle second pass in the night session's Phase A dogfood wave; a real correctness bug on the primary CI entry point where one bad snapshot took down the whole run.

**Open questions / blockers:** none.

**Process note:** I initially staged this on `main` and skipped filing the issue first — caught it before any push, reset `main` to origin, moved the work to a proper branch, filed #65, posted the plan, then recommitted. No push to `main` occurred.

**Next session:** none specific.

---
## 2026-06-24 — Issue #67: non-finite candidate embedding produced a nan cosine_score
**Duration:** ~30 min · **Branch:** `session/2026-06-24-0355-issue-67`

- `diff_response` enforced the stored snapshot embedding's finiteness (schema load) and the candidate's dimension (#65), but not the candidate's finiteness. A BYO embedder (Protocol: Cohere/OpenAI/custom) returning a NaN/±Inf component slipped through `cosine()` into a `nan` cosine_score — collapsing the verdict to a misleading `fail` and leaking `nan` into the HTML/JSON/PR-comment output.
- Added `NonFiniteEmbeddingError` + a candidate-finiteness guard after the dimension check, wired into the two run/diff except tuples so it lands as a per-row `error` and the batch continues. Symmetric to the stored-embedding guard.
- 5 new tests (parametrized NaN/±Inf at diff_response, finite-still-diffs, cli per-row-error). Red (guard disabled) / green. Suite 296 → 301, ruff clean.

**Why this work, this session:** prompt-regression-suite was the earliest non-tier repo in build sequence after the priority tier was exhausted this run; the diff/validate/cli paths were saturated, so a dogfood sweep surfaced the candidate-embedding finiteness asymmetry.

**Open questions / blockers:** none. Process: cut the branch + filed issue/plan before editing this time (corrected from the prior round). Two test gotchas worth remembering: HashEmbedder's model_name is `hash-embedder-128d-ngram2` (not `hash-v1`); and the red-check can't `git stash` just diff.py because the new error symbol is imported elsewhere — neutralize the guard block instead.

**Next session:** stats.py / html_report.py / io.py remain; the html_report `nan`/`inf` rendering is now unreachable from the diff path (guarded upstream) but a defensive `:.3f` formatter check is a small optional follow-up.

---
## 2026-06-24 — Issue #69: semantic-category cosine channel wasn't finiteness-guarded
**Duration:** ~25 min · **Branch:** `session/2026-06-24-1931-issue-69`

- #67 guarded the main `cosine_score` path, but `score_semantic_categories` re-embeds the candidate and each category label and called `cosine()` unguarded. A BYO embedder returning a non-finite component for a *category label* (candidate finite) slipped past the #67 guard, producing a `nan` `cosine_to_response` that leaked into the HTML/JSON/PR-comment output.
- Validated finiteness of the response and each category-label embedding in `score_semantic_categories`, raising the same catchable `NonFiniteEmbeddingError` the `run` batch records per-row. Extracted a shared `_first_non_finite` helper and refactored the #67 check onto it. 7 tests (red→green); existing #67 tests still green; full suite + ruff clean.

**Why this work, this session:** the 4th issue of a multi-issue DAY run; explicitly hinted at by the `llm-cost-optimizer` #88 commit comment ("the sibling prompt-regression-suite"). Completes a cross-repo cosine/embedding finiteness sweep alongside rag-production-kit (#82) and chunking-strategies-lab (#66) this run; all three cosine consumers in this repo are now covered (schema-stored #67-load, main candidate #67, semantic-category #69).

**Open questions / blockers:** none.

**Next session:** all cosine consumers here are now finiteness-guarded; the repo is healthy.

## 2026-06-25 — Issue #71: HTML report silently dropped error verdicts (failure masking)
**Duration:** ~40 min · **Branch:** `session/2026-06-25-0330-issue-71` · **PR:** #72

- The `run --format html` report — documented as the CI artifact operators read to see "which snapshots failed and why" — omitted **error verdicts** (embedder/snapshot model mismatch per D-006, dimension mismatch, non-finite embedding). The CLI counts these in `failed` and exits non-zero, and JSON/text include them, but the `run` except path appended only to `rows`, never to `entries`; HTML renders `render_report(entries)`, so erroring snapshots vanished and the summary `total` undercounted with no error stat. A failing run could read as "all pass" in the human-facing report. Reproduced e2e: exit 1 + JSON `failed: 1` but HTML `total: 1` with the bad snapshot absent.
- Added an `ErrorEntry(snapshot_id, message)` type (error rows have no `DiffResult`; a synthetic one would fabricate numbers), rendered as a red section; `_summarize` now counts `error` and includes it in `total`; the summary header gains an `error` stat shown only when non-zero (clean runs keep the original four-stat header). Wired the CLI error path to append an `ErrorEntry`. Regenerated `docs/regression_demo.html` for the 3 new CSS rules. Full suite 312 passed, ruff clean.

**Why this work, this session:** found via a NIGHT-session parallel dogfood sweep across eight repos — the only repo with a real, reproducible bug (the rest were clean; a chunking "whitespace drop" finding was a false positive, since semantic chunking is offset-recoverable, not exact-concat, by design). A failure-masking bug in a regression tool's primary artifact is high-value to close.

**Open questions / blockers:** none.

**Next session:** `skipped` (no-candidate) rows are still intentionally omitted from HTML (not a failure, exit 0) — if a future run wants them shown for completeness, that's a separate, lower-value follow-up.

---
## 2026-06-25 — Issue #73: reject a non-finite warn_band in diff_response
**Duration:** ~18 min · **Branch:** `session/2026-06-25-2338-issue-73`

- `warn_band` was validated only by sign checks (`warn_band < 0`, `warn_band > effective_threshold`). Both are `False` for `NaN`, so a non-finite `warn_band` slipped past both and reached the cosine warn floor `max(0.0, effective_threshold - warn_band)`, where `max(0.0, NaN)` collapses to `0.0` — demoting every failing cosine (down to a 0.0, off-topic answer) from "fail" to "warn", silently disabling the regression gate. Same fail/warn collapse the #35 guard prevents, reached through a value its `>` comparison can't catch; the sibling `threshold` range check already rejected NaN.
- Fix: a `math.isfinite(warn_band)` guard ahead of the sign checks (one consistent message for NaN/±Inf). Four tests (NaN/±Inf rejected + a pin on the fail→warn demotion). Red-green verified: without the guard the NaN case did not raise (verdict was "warn"). Suite 312 → 316, ruff clean. Continues the repo's finiteness sweep (#68/#69/#70).

**Why this work, this session:** third issue of a multi-issue DAY session. The priority-tier repos' real bugs were exhausted (llm-eval-harness #98, llm-cost-optimizer #93 shipped; the rag/chunking/nextjs leads were all design-choice false positives), so per the loop bias I rotated to a non-tier repo; a strict defensive-gap sweep surfaced the one float param in `diff_response` that NaN slips past.

**Open questions / blockers:** none.

**Next session:** `diff_response`'s float params are now all NaN-safe; future work here is more likely on verdict semantics or reporting than input validation.

## 2026-06-26 — Issue #75: load_snapshot accepts an unquoted-int schema_version
**Duration:** ~25 min · **Branch:** `session/2026-06-26-2033-issue-75`

- `load_snapshot` compared the YAML-parsed `schema_version` directly to the string `"1"`. YAML parses an unquoted `schema_version: 1` as the *int* `1`, so `1 != "1"` rejected the snapshot with a genuinely baffling message — *"schema_version is 1, this reader only supports '1'"* (the values look identical apart from the repr quotes). `save_snapshot` writes the quoted `'1'`, so generated snapshots round-trip fine, but the repo is built around hand-authored, PR-reviewable snapshots (D-003) plus a `validate` linter, and a human naturally omits the quotes. `validate` inherited the bug (it loads via `load_snapshot`).
- Fixed by comparing on the string form (`str(version) != SCHEMA_VERSION`) and normalizing to the canonical string before `from_dict` (whose strict `_require_str` would otherwise re-reject the int). A genuinely-different version (`"2"`, `2`, `"1.5"`) still rejects. 3 new tests (unquoted-int loads + round-trips, different-int still rejects, validate clean on unquoted-int). Suite 316 → 319, ruff clean.

**Why this work, this session:** first non-priority-tier repo of a multi-issue DAY run after the priority tier was largely worked; a Phase A code-read of the loader seam surfaced a real false-rejection on the repo's central hand-authored-snapshot workflow.

**Open questions / blockers:** none.

**Next session:** the loader now tolerates YAML's int/str scalar ambiguity for the version field; the schema dataclasses keep their strict in-memory `_require_str` contract (normalization stays at the IO seam).

## 2026-06-26 — Issue #77: array/object/null slots mislabeled "missing" instead of "type_unknown"
**Duration:** ~20 min · **Branch:** `session/2026-06-26-2356-issue-77`

- `diff_slots` gated the `type_unknown` status on `slot_type not in SLOT_TYPE_PYTHON`, but `SLOT_TYPE_PYTHON` lists `array`/`object`/`null`. Those types are schema-valid (`schema._ALLOWED_SLOT_TYPES`) yet have no extractor in `extract_slots`, so they passed the gate and fell through to the `missing` branch. Reproduced: each of array/object/null reports `missing` while the schema-*illegal* `"blob"` correctly reports `type_unknown` — the valid types got worse (false model-regression) treatment than an invalid one.
- Impact: `missing` is the red "the model failed to produce this slot" status across the HTML report, `diff --json`, and PR comments; any snapshot declaring an array/object/null slot failed every diff permanently regardless of the candidate, blaming the model for a tool limitation. Contradicts the `extract_slots` docstring contract.
- Fixed by adding `_EXTRACTABLE_SLOT_TYPES` (the types the extractor actually handles) and gating `type_unknown` on it, so array/object/null — and any unrecognized type — route to `type_unknown`. 4 regression tests; suite 319 → 323, ruff clean.

**Why this work, this session:** sixth issue of a multi-issue DAY run, the first non-tier repo after completing the priority-tier sweep. prompt-regression-suite had no open backlog, so I dogfooded with an Explore agent and filed #77 from a reproduced finding.

**Open questions / blockers:** a transient `gh` GraphQL 401 hit during issue creation; re-exporting `GH_TOKEN=$(gh auth token)` cleared it. Two runners-up remain unfiled — `count_always_pass` mislabels `tolerance==1.0` (the strictest setting) as always-pass, and the HashEmbedder degenerate single-token false-PASS (same class as llm-cost-optimizer#98).

**Next session:** consider the HashEmbedder degenerate false-PASS — it is a missed-regression (false PASS), the worst harm class for a regression tool.

## 2026-06-27 — Issue #79: slot extraction misread hyphenated tokens as negatives
**Duration:** ~20 min · **Branch:** `session/2026-06-27-0331-issue-79`

- `_INTEGER_RE = r"-?\b\d+\b"` / `_NUMBER_RE = r"-?\b\d+\.?\d*\b"` — the optional leading minus is followed by `\b`, but the boundary between a hyphen and a digit is *always* a `\b`. So a hyphenated token (`W-2`, `ABC-7`, `P-1`) had its hyphen consumed as a unary minus, extracting a spurious negative. That value passed the `isinstance(int)` check and was reported `ok` — and could **mask a real regression**: a model answer that dropped the number but mentioned a hyphenated code (`See section W-2`) yielded a passing integer slot instead of `missing`. Reproduced: `extract_slots("See section W-2 …", integer-slot)` → `{'refund_days': -2}`.
- Fixed with a `(?<![\w-])` lookbehind so `-` is only a sign when not glued to a preceding word char or hyphen. Hyphenated identifiers no longer yield negatives; genuine negatives (`-30`, `-2.5`) and `14-day` → 14 are preserved. Added 3 regression tests. Suite 323 → 326, ruff clean.

**Why this work, this session:** fourth issue of a multi-issue NIGHT run; a high-confidence, clean dogfood find with a one-liner repro and a regex-only fix.

**Open questions / blockers:** none.

**Next session:** numeric slot extraction is robust to hyphenated identifiers; broader numeric parsing (thousands separators, scientific notation) remains out of scope.

## 2026-06-27 — Issue #81: tolerance=1.0 mislabeled "always-pass" (it's the strictest gate)
**Duration:** ~20 min · **Branch:** `session/2026-06-27` (committed on main-tracking session branch via PR)

- The diff gate is `cosine >= tolerance`, so a higher tolerance is *stricter*; `tolerance=1.0` passes only an embedding-identical response. But `ToleranceDistribution.count_always_pass`, the `prompt-snap stats` summary token `always_pass=N`, the docstring, the README, and architecture.md all called `tolerance=1.0` "always-pass — useful for intentionally-drifting prompts" — the exact inverse. The operator-facing stats summary pointed operators at the suite's *strictest* snapshots as if they were the *laxest*.
- This is a labeling/semantics fix (the count is computed correctly). Renamed `count_always_pass` → `count_strictest` (field, `to_dict` key, summary token), corrected the docstring/README/architecture.md, updated the public-surface key-set test, and added a behavioral test pinning `tolerance=1.0` ⇒ identical passes / drift fails (constructed with empty structured_slots so the cosine channel drives the verdict). Suite 323 → 324, ruff clean.

**Why this work, this session:** fifteenth issue of a multi-issue NIGHT run; a second-pass dogfood of prompt-regression-suite surfaced this operator-facing label inversion.

**Open questions / blockers:** none.

**Next session:** the stats output now correctly labels strictest tolerances; the behavioral test guards the semantics.

## 2026-06-27 — Issue #83: type_unknown slots forced verdict=fail
**Duration:** ~25 min · **Branch:** `session/2026-06-27-1536-issue-83`

- Any snapshot declaring an `array`/`object`/`null` slot was permanently red: `SlotDelta.is_failure` was `status != "ok"`, counting `type_unknown` (the #77 status meaning "the tool has no extractor for this schema-valid type — didn't try") as a real failure. Since `diff_response` ANDs the slot channel into the verdict, every diff against such a slot returned `fail` even for a byte-identical, zero-drift response — #77's intent leaked at the verdict level.
- Fixed `is_failure` to `status not in ("ok", "type_unknown")` (`missing`/`type_mismatch` stay failures) and added regression tests: identical candidate with array/object/null slot now passes (parametrized), a genuinely missing extractable slot still fails. Negative-checked the fix is load-bearing.

**Why this work, this session:** third find of a multi-issue DAY run; surfaced by a second Phase A dogfood sweep over the 5 non-tier repos after the priority tier was exhausted.

**Open questions / blockers:** none.

**Next session:** the verdict now honors the type_unknown contract end-to-end; real extractors for array/object/null remain a deliberate non-goal (feature, not a fix).

## 2026-06-28 — Issue #85: low per-snapshot tolerance aborted the whole run batch
**Duration:** ~40 min · **Branch:** `session/2026-06-28-0319-issue-85`

- A snapshot with `tolerance < DEFAULT_WARN_BAND` (0.05) lowered the effective threshold under the default warn_band, firing the #35 guard even when the operator set no `--warn-band`. That guard raised a *bare* `ValueError`, which the `run` loop (catching only the three typed sibling guards) let escape and abort the whole batch — the failure mode the #65/#66/#69 batch-isolation guards exist to prevent.
- Fixed via **Option A (conservative)**: new typed `WarnBandThresholdError(ValueError)`, caught in the run loop so it lands as a per-row `error` verdict; `diff_response` still raises, preserving #35's fail-loud guard (D-006). Added 3 tests; full suite green, ruff check + format clean.
- **Decision-revisit posture:** problem (1), the batch abort, is an unambiguous robustness bug fixed here. Problem (2), the A-vs-B semantics (whether a low tolerance under default warn_band should raise at all vs clamp), is a genuine call **deferred to JT** — Option B silently narrows warn_band and brushes D-006. PR opened ready for review, not auto-merge. Same posture as the mcp-server-cookbook #54/#55 revisits this run.

**Why this work, this session:** the only remaining `priority:high` actionable issue in the portfolio; the conservative half (problem 1) closes cleanly while honoring the deliberate JT-facing semantics question.

**Open questions / blockers:** Option B (operator-friendly clamp) awaits a JT semantics decision.

**Next session:** —

## 2026-06-28 — Issue #87: HTML report showed a type_unknown slot as green/OK
**Duration:** ~20 min · **Branch:** `session/2026-06-28-1611-issue-87`

- `_render_slots` keyed the slot row's CSS class off `is_failure` (`"slot-ok" if not is_failure else f"slot-{status}"`). Issue #83 had redefined `is_failure` to return `False` for `type_unknown` (an unevaluable slot — the tool has no extractor for that schema-valid type — not a regression). So a `type_unknown` row got `class="slot-ok"` and was rendered **green**, while the dedicated amber `.slot-type_unknown` CSS rule sat dead. A slot the tool literally couldn't evaluate looked clean in the report. `html_report.py` predated #77/#83, so it was never updated for the new status — a report-layer regression riding on the diff-layer change.
- Fixed by driving the row class off `status` directly (`klass = f"slot-{html.escape(slot.status)}"`); every status already has a matching CSS rule, so each maps to its intended color and the `is_failure` branch is retired. No CSS change. Added a regression test that parses each slot row's class-to-status mapping (proven to fail pre-fix); suite 335 → 336, ruff clean.

**Why this work, this session:** fifth substantive issue of a multi-issue DAY run, and the third real dogfood find (after llm-eval-harness #114, chunking #84, emb-shootout #69) — a genuine report-correctness bug where the chart's color lies about a slot the tool couldn't evaluate.

**Open questions / blockers:** none.

**Next session:** continue the loop if time remains.

## 2026-06-28 — Issue #89: `diff` command crashed on a low-tolerance snapshot (WarnBandThresholdError uncaught)
**Duration:** ~15 min · **Branch:** `session/2026-06-28-1946-issue-89`

- The `diff` command's `except` tuple caught the embedder config errors but not `WarnBandThresholdError`, so a schema-valid snapshot whose per-snapshot `tolerance` is below the default warn band (0.05) escaped `diff_response` as a raw traceback (exit 1) — indistinguishable from a normal `fail` verdict for a CI consumer. The sibling `run` command was fixed for this exact case in #85; `diff` was the missed sibling. Reproduced firsthand before filing.
- Fixed by adding `WarnBandThresholdError` (already imported) to `diff`'s `except` tuple, so it lands as a clean `error: ...` + exit 2 like the command's other configuration errors. (Unlike `run`, which is a batch and treats it as a per-row error to keep processing; `diff` is single-snapshot, so a clean exit 2 is right.) Added a regression test mirroring the `run` low-tolerance test; suite 336 → 337 passed, ruff clean.

**Why this work, this session:** fifth substantive issue of a multi-issue DAY run. The 4 Python priority-tier repos were worked earlier this run (#116, #104, #96, #86); only the JS/demo nextjs work remained in the tier, so per the D-007 fall-through + D-008 fuller-utilization intent I dropped to the earliest non-tier Python repo in build sequence (prompt-regression-suite) and dogfooded it. One weaker finding deferred (out-of-range `--threshold` raw ValueError escaping both commands).

**Open questions / blockers:** none.

**Next session:** continue the loop if time remains.

## 2026-06-29 — Issue #91: docs said three CLI subcommands, but five ship
**Duration:** ~11 min · **Branch:** `session/2026-06-29-0353-cli-subcommand-count`

- `cli.py`'s module docstring and README:243 said the `prompt-snap` CLI has "three subcommands" (run/update/diff), but `build_parser()` registers five — `stats` (#47) and `validate` (#49) shipped with handlers and dedicated test files. The README feature bullet already listed all five and is test-locked; only the prose count drifted.
- Enumerated all five in the cli docstring + README prose and added the stats/validate bullets. Doc-only; the bullet-lock test still passes.

**Why this work, this session:** seventh issue of the night run, from a parallel doc-contract subagent sweep of the logic-clean repos I'd earlier cleared with a logic-bug lens — the doc-contract lens surfaced drift I'd missed.

**Open questions / blockers:** none.

**Next session:** the CLI subcommand count is now consistent across docstring, README prose, and the test-locked bullet.

## 2026-06-30 — Issue #93: `run` leaked a raw traceback (exit 1) on a missing/malformed `--candidates` file
**Duration:** ~20 min · **Branch:** `session/2026-06-30-1549-issue-93`

- `_run_command` translated a missing snapshots dir / no-snapshot-files to a clean `error:` + exit 2 (`cli.py:157-167`), but the very next line `candidates = _load_candidates(Path(args.candidates))` was unguarded. `_load_candidates` raises `FileNotFoundError` (missing file) and `ValueError` (malformed JSON / non-object row / missing fields / duplicate key / zero rows) — all escaped `main` as a raw traceback at exit 1, the "regressions found" code, breaking the documented `0/1/2` contract. Reproduced all three firsthand.
- Fixed by wrapping the call in `try/except (OSError, ValueError)` → `error: <msg>` + `return 2`, mirroring the adjacent snapshots-dir handling. +3 lock tests (missing/malformed/empty), confirmed failing pre-fix by reverting only the try/except. Suite 337 → 340, ruff clean.

**Why this work, this session:** fifth issue of a DAY multi-issue run, and the first **non-tier** repo — the priority tier was exhausted for actionable code work this run (eval-harness #126, cost-optimizer #114, rag #106, chunking #92 all shipped; nextjs operator-blocked), so per D-009 I rotated to `prompt-regression-suite` (next in build sequence). It had zero open issues, so dogfood-and-file: I cleared stats.py/io.py myself (both robust) while an Explore hunter scanned cli/diff/html_report/schema/validate, surfacing this exit-code gap plus a sibling (`_read_text_arg` `SystemExit(msg)` → exit 1, filed as **#94**).

**Open questions / blockers:** none — ready for review. #94 left for a future session (same-repo MEMORY-conflict avoidance). Also noted but not filed: `load_snapshot` inside the per-snapshot loop (`cli.py:187`) leaks on a corrupt snapshot YAML — a distinct per-row-vs-top-level design question.

**Next session:** continue the loop on another repo.

## 2026-06-30 — Issue #94: diff/update usage errors exited 1 instead of 2
**Duration:** ~15 min · **Branch:** `session/2026-06-30-1951-issue-94`

- `_read_text_arg` signaled usage errors (both `--canonical` and `--canonical-stdin` passed; text empty after stripping) with `raise SystemExit("error: …")`. A `SystemExit` with a *string* argument prints the string but exits with code **1** — the "regressions found" code — for what is a usage error. Used by both `diff` and `update`. Fixed by introducing a typed `_UsageError`; `_diff_command` and `_update_command` (both already return `int`) catch it, print the `error:` line to stderr, and `return 2`, honoring the `0/1/2` contract.
- +2 new diff lock tests (empty `--candidate` → exit 2; a valid-candidate over-rejection guard). Updated the two pre-existing update usage tests (`test_update_rejects_empty_canonical` / `_both_canonical_sources`) from the old `pytest.raises(SystemExit)` assertion to the new exit-2 contract (added `capsys`). Dropped two initially-added redundant update tests since the updated pre-existing pair already covers those paths. Suite 340 → 342, ruff clean.

**Why this work, this session:** sixth issue of a DAY multi-issue run and the second non-tier repo, after the priority tier's clean work was exhausted. Sibling of #93 (same dogfood sweep). This time I followed the order strictly — branch, then plan comment, then code (no code-before-plan slip).

**Open questions / blockers:** none — ready for review.

**Next session:** continue the loop.

## 2026-07-01 — Issue #97: cosine() overflow leaks nan into cosine_score (hole in the NonFiniteEmbeddingError guard)
**Duration:** ~25 min · **Branch:** `session/2026-07-01-1538-issue-97`

- `NonFiniteEmbeddingError` documents a guarantee: a corrupt BYO embedder must raise a catchable per-row error, never leak a `nan` `cosine_score` into the HTML/JSON/PR-comment output. The `_first_non_finite` guard (#67/#69) enforced that only for non-finite *input components* — but `cosine()` can produce `nan` from all-finite inputs: `sum(x*x)` overflows to `+inf` for out-of-range magnitudes, so `dot/(na*nb) = inf/inf = nan` (two identical `1e200` vectors score `nan` instead of `1.0`). That `nan` slipped the input guard and landed in `cosine_score`/`to_dict()` as a misleading `fail`. Reproduced firsthand both directly and end-to-end before fixing.
- Fixed with a symmetric output guard (`_finite_or_raise`) at both BYO-vector call sites (`diff_response` main score + `score_semantic_categories` per-category), raising the same catchable error. Fail-loud, matching the module's posture toward non-normalized/corrupt vectors. +4 tests (both overflow paths raise, direct cosine-nan root cause, finite over-rejection guard); suite 341 → 345, ruff + format clean. Filed `priority:low` — realism is low (needs ~1e153+ magnitude, which no L2-normalizing production embedder emits), but the threat model is identical to #67/#69 and the guard was demonstrably incomplete.

**Why this work, this session:** second issue of the DAY run. The portfolio is deeply saturated — a broad 4-repo parallel dogfood sweep (chunking, embedding-shootout, prompt-regression, python-async) returned NO_BUG on three after exhaustive fuzzing; only this cosine-overflow contract gap held up under firsthand repro.

**Open questions / blockers:** none — ready for review.

**Next session:** continue the loop; portfolio saturation is deep (this run: ~11 hunter/self reads across 7 repos, only 3 real bugs total — 2 in mcp postgres, 1 here).

## 2026-07-03 — Issue #99: prompt-snap run leaked a raw traceback (exit 1) on a malformed snapshot
**Duration:** ~25 min · **Branch:** `session/2026-07-03-1532-issue-99` · **PR:** #101

- `_run_command` loaded each snapshot with an unguarded `load_snapshot(path)`, and `main()` catches nothing, so a schema-invalid snapshot (`SnapshotValidationError`) or a YAML-syntax-broken one (`yaml.YAMLError`) escaped as a raw traceback and Python exited 1 — the "regressions found" code. Reproduced firsthand for both variants. This is the same class #93/#95 fixed for the sibling `--candidates` input on the same command.
- Fixed by wrapping the load in a try/except for `(OSError, SnapshotValidationError, yaml.YAMLError)`, printing a clean `error:` that names the file and points at `prompt-snap validate <dir>` (the collecting-mode command), and returning 2. `run` still aborts on the first bad file by design (validate is the pre-flight); the abort is just legible now. `SnapshotValidationError` subclasses `ValueError` but `yaml.YAMLError` does not, so both are named. +2 regression tests (confirmed failing pre-fix). Full pytest green; ruff check + format clean.

**Why this work, this session:** third issue of the DAY multi-issue loop. Portfolio saturated (zero open issues repo-wide), so I dogfooded `prompt-regression-suite` (stalest repo past the 36h floor). Two parallel Explore hunters: one hit a leading-decimal regex bug (filed #100, working next), one returned two borderline design findings I skipped. This #99 I found firsthand during a CLI review, not from an agent.

**Open questions / blockers:** none — ready for review. Sibling note: this PR and the upcoming #100 PR both append to these MEMORY files; whichever merges second needs a trivial serial rebase (documented pattern).

**Next in this session's loop:** fix #100 (leading-decimal extraction), same repo.

## 2026-07-03 — Issue #100: extract_slots dropped the fraction on a leading-decimal number
**Duration:** ~20 min · **Branch:** `session/2026-07-03-1536-issue-100` · **PR:** #102

- `_NUMBER_RE = -?\d+\.?\d*` required a digit *before* the decimal point, so on a leading-decimal number like `.05` the leading `.` failed to start a match but `\d+` then matched `05` — the extractor captured `5.0`, dropping the fraction. Rate/probability/discount "number" slots commonly use this notation, so `.05` silently recorded `5.0` and could mask a number-loss regression as `ok`. Reproduced firsthand (agent-surfaced finding, verified before fixing).
- Fixed by adding a leading-decimal alternative: `-?(?:\d+\.?\d*|\.\d+)`. `.5`→`0.5`, `.05`→`0.05`, `-.5`→`-0.5`, `$.05`→`0.05`. Every control preserved (`0.5`, `5`, `-2.5`, `3.14`) and the #79 hyphen guards intact (`14-day`→14, `W-2`→none). `_INTEGER_RE` unchanged. +6 regression tests. Full pytest green; ruff clean.

**Why this work, this session:** fourth issue of the DAY loop, second in this repo. One of two parallel dogfood hunters surfaced it; I verified firsthand before fixing per the saturation guidance.

**Open questions / blockers:** none — ready for review. Sibling note: PR #101 (#99) and #102 (#100) both append to these MEMORY files; whichever merges second needs a trivial serial rebase.

**Next in this session's loop:** priority-tier and this repo now worked; rotate to the next repo (ai-app-integration-tests / python-async-llm-pipelines are the remaining >36h repos).

## 2026-07-03 — Issue #103: symbol-resolution doc-lock (propagates portfolio-ops #55) (~25 min)

**What got done.** Added a fifth invariant to `tests/test_architecture_doc.py`: every `<submodule>.<symbol>` ref and multi-word CamelCase public type named in `docs/architecture.md` must resolve against the `prompt_regression` package, its submodules, or the Python builtins. That closes the drift class portfolio-ops #55 catalogued (a doc naming a nonexistent type passes CI). The doc names 8 real types — `CanonicalResponse`, `DiffResult`, `ResponseShape`, `SemanticCategoryScore`, `SlotDelta`, `StatsReport`, `ToleranceDistribution`, and `ValidationFinding` (which lives in the `validate` submodule, not re-exported at package level, so submodule coverage is load-bearing). Single-word capitalized tokens and bare snake_case are excluded to avoid prose/field-name false positives. Baked in an inverse-safety-net test (inject a drifted symbol, assert it's flagged) plus hard-pins for the skip-extension and subpackage sets. Suite +4 tests, ruff clean.

**Why prioritized.** Second worked issue of the DAY run, continuing the #55 propagation after chunking-strategies-lab #104. With all priority-tier repos now carrying the symbol lock and no other actionable unblocked tier work, selection rotated to non-tier repos by build sequence; prompt-regression-suite (build-seq #3) is the earliest among the remaining gap repos.

**Open questions / blockers.** None — ready for review.

**Next in this session's loop:** continue #55 propagation to vector-search-at-scale and python-async-llm-pipelines, one small PR each.

## 2026-07-04 — Issue #105: warn_band == effective_threshold collapses the fail/warn gate
**Duration:** ~30 min · **Branch:** `session/2026-07-04-1922-issue-105` · **PR:** #106

- `diff_response`'s guard (`diff.py:562`) used `warn_band > effective_threshold`, but the collapse it exists to prevent also happens at the exact boundary `warn_band == effective_threshold`: the warn floor `max(0.0, thr - wb)` is already `0.0` there, so `cosine_warn = cosine >= 0.0` is true for every sub-threshold cosine down to maximum drift (0.0). Every regression is demoted `fail` → `warn`, and since `run`/`diff` count only `fail`, a total regression exits 0 and passes CI green — the exact silent degradation the #35 guard was meant to stop. Reachable with no `--warn-band` flag: a snapshot `tolerance == DEFAULT_WARN_BAND` (0.05) hits `warn_band == effective_threshold`. Reproduced live on `main` before fixing.
- Changed the guard to `>=` (the floor is only safe when strictly positive) and the message to `"must be < effective_threshold"`; also fixed the inverted `DEFAULT_WARN_BAND` inline comment (band is `[thr - wb, thr)`, not `[thr, thr + wb)`). An existing test was pinning the bug — it asserted `warn_band == threshold` is *accepted* — so I moved that boundary value to the reject set and added two regression tests (the kwargs boundary and the no-flag `tolerance == DEFAULT_WARN_BAND` reachability). 356 → 359 passing, ruff clean.

**Why this work, this session:** Portfolio is deeply saturated — zero `priority:high`, the two `priority:med` are JT-blocked decision-revisits. Priority-tier dogfood hunts came up empty (llm-eval-harness, llm-cost-optimizer, rag-production-kit + nextjs manual), so I rotated to a non-tier hunt round; of 4 non-tier repos (vector-search, python-async, embedding-shootout, prompt-regression-suite), only this one had a real, reproducible correctness bug.

**Open questions / blockers:** none — ready for review.

**Next in this session's loop:** non-tier round exhausted (3 clean, 1 fixed); portfolio-ops #55 verified and closed earlier this run. Wind down toward the DAY cap.

## 2026-07-05 — Issue #107: colliding snapshot ids emit duplicate HTML `id` anchors
**Duration:** ~30 min · **Branch:** `session/2026-07-05-1521-issue-107` · **PR:** #108

- The HTML report anchors each section as `#snapshot-<id>` (module docstring, line 9) so a CI artifact can deep-link to a specific snapshot. `_safe_anchor` lowercases and collapses every non-alphanumeric run to one `-`, so distinct snapshot ids differing only in case or separator style — `"My Test"`, `"my-test"`, `"my_test"` — all slugified to `snapshot-my-test`. `render_report` then emitted three `<section>`s with the same `id=`: invalid HTML, and every colliding deep-link jumped to the *first* matching section, silently defeating the per-snapshot anchoring the report exists for. Reproduced firsthand on `main` before filing.
- Fixed by assigning anchors once across all entries with GitHub-style disambiguation (`-1`, `-2` on collision), looping against the set of already-assigned anchors so a synthesized suffix can't clash with a snapshot literally named `foo-1`. `_render_entry`/`_render_error_entry` now take the pre-assigned anchor; `_safe_anchor`'s single-name behavior and the public `render_report` signature are unchanged. Added two lock tests (colliding-ids uniqueness + suffix-vs-literal-id). 359 → 361 passing, ruff clean.

**Why this work, this session:** Portfolio is deeply saturated — Phase A found no mergeable PRs (drafts are display-blocked demo captures + JT-gated lco#124), a clean six-fingerprint audit, and eight dogfood hunts across two waves (metric math, escaping/GFM, stats, MCP servers, async concurrency, RRF/citation, retry/approval) all came up empty on Python 3.14-green suites. The one real bug was a lead the prompt-regression hunter under-rated as a "defensible design choice"; duplicate HTML ids are objectively invalid, so I reproduced it firsthand and fixed it.

**Open questions / blockers:** none — ready for review.

**Next in this session's loop:** correctness surface is saturated; remaining open issues are JT-gated decision-revisits (#71 vsas, #97 lco) and display-blocked demo captures. Continue toward the DAY cap only if a further real, reproducible finding surfaces.

## 2026-07-06 — Diff-layer README quickstart crashed (issue #109, ~30 min)

A Phase-A dogfood run-the-shipped-example hunt found the README's Diff-layer quickstart crashes on a fresh clone: it paired a bare `HashEmbedder()` (128-dim) with `refund_window_v1.yml`, which is OpenAI-embedded (8-dim). The snippet failed the D-006 model-name guard, and even `force=True` hit a dimension-mismatch error (128 vs 8) — HashEmbedder can never diff that snapshot. Reproduced firsthand, deterministic.

`refund_window_v1.yml` is the test-locked schema reference (a test asserts its OpenAI model name), so I left it untouched and pointed the example at `creative_kite_v1.yml` — the shipped snapshot that IS HashEmbedder-embedded — with a high-overlap candidate, so it now runs hermetically and returns `pass`. Added a lock test that extracts the snapshot + candidate from the README and runs the example, asserting no crash. Respects D-006 (matching snapshot, not a force override). PR #110, ready.

**Why prioritized:** static issue queue still exhausted; work came from the run-the-shipped-example lens, which yielded two real hits this run (this + llm-eval-harness #144). Encoding, numeric-boundary, and nextjs stream-parse hunts all came up empty, reconfirming saturation on those axes.

## 2026-07-09 — Issue #111: diff/update leak raw traceback on a malformed snapshot
**Duration:** ~20 min · **Branch:** `session/2026-07-09-1604-issue-111` · **PR:** #112

- #99 guarded `_run_command`'s `load_snapshot` (clean `error:` + exit 2), but the sibling `diff`/`update` commands read the snapshot through the same seam unguarded, so a malformed / missing / YAML-broken snapshot escaped as a raw traceback at exit 1. Both commands already honored exit 2 for their other inputs, so the omission was an incomplete port of #99.
- Wrapped `load_snapshot` in both commands in the same `(OSError, SnapshotValidationError, yaml.YAMLError)` → exit-2 guard. 4 regression tests, all failing pre-fix. Full suite 366 pass, ruff clean.

**Why this work, this session:** found via the sibling-branch-incomplete-fix meta-lens — the sixth hit of this run via that lens; reproduced firsthand via the shipped CLI before fixing.

**Open questions / blockers:** none — ready for review.

**Next session:** the exit-2 snapshot-load contract is now uniform across `run`/`diff`/`update`. The `stats`/`validate` subcommands have their own load handling.

## 2026-07-09 (PM) — Issue #113: CLI write-seam exit-code contract (#99/#111 sibling)
**Duration:** ~25 min · **Branch:** `session/2026-07-09-1933-issue-writeseam` · **PR:** #114

**What got done.** The CLI documents a `0 = clean / 1 = regressions|findings / 2 = I/O or usage error` exit contract. #99/#111 translated read/load I/O errors to a clean `error:` line + exit 2 for every subcommand — but the write seam was left bare. `run/diff/validate --out` called `atomic_write_text` directly and `update` called `save_snapshot` directly, so an unwritable destination (a directory, read-only path, unwritable parent) escaped as a raw `OSError` traceback at exit 1. Added a `_write_output` helper translating `OSError` → `error:` + exit 2, routed the three `--out` sites through it, and wrapped `update`'s `save_snapshot` in the same guard. Migrated the two CLI atomicity tests from `pytest.raises(OSError)` (which pinned the propagation mechanism) to `assert rc == 2` + destination-absent — both invariants hold; the two `save_snapshot` *unit* tests correctly still raise (helper layer, not CLI). Added `validate --out` + `update` exit-2 regression tests. Full suite 368 pass, ruff clean.

**Why prioritized.** Found via the exit-code-contract lens — the same class as this run's ems#87 and leh#158, applied to a third repo. Reproduced firsthand on `validate` before filing.

**Open questions / blockers.** None — ready for review.

**Next session:** prs CLI exit-code contract is now complete on both axes (#99/#111 read, #113 write). Don't re-sweep this class in prs.

## 2026-07-10 — Issue #115: prompt-snap stats exit-2 loader parity (~25 min, night)

**What got done.** `prompt-snap stats` was the last snapshot loader-walk that leaked a raw traceback at exit 1 on a malformed snapshot. `_stats_command` only caught `StatsError`; `collect_stats` → `load_snapshot` can raise `SnapshotValidationError` / `yaml.YAMLError` / `OSError`, none of which were caught — while the `run` (#99), `diff`/`update` (#111), and `--out` (#113) seams all translate the same failures to a clean `error:` + exit 2. The stale docstrings justified the bare propagation with "same loud failure `run` would surface" — true when stats shipped (2026-06-01), but #99 (2026-07-03) changed `run` to exit 2 with a validate hint. Verified firsthand: schema-invalid and YAML-syntax-error snapshots both leaked tracebacks at exit 1.

Guarded the `load_snapshot` loop in `collect_stats` to raise `StatsError` (already mapped to exit 2 by `_stats_command`) naming the offending file + the `validate` hint the `run` seam gives, and refreshed both stale docstrings. Added library- and CLI-level tests locking the exit-2/no-traceback contract for both failure modes; all fail pre-fix. Full suite + ruff green.

**Why prioritized.** Static priority:high queue globally exhausted; found via the sibling-incomplete-fix meta-lens. The prs exit-2 loader contract is now complete across all five subcommands.

**Open questions / blockers.** None — PR ready for review.

## 2026-07-10 — Issue #117: exit-2 translation for a bad --embedder (~22 min, night)

**What got done.** `make_embedder(args.embedder)` was called bare (outside any try/except) at all three command entry points (`_run_command`, `_update_command`, `_diff_command`). A reserved-but-unwired name (`voyage`/`openai`/`cohere` → `NotImplementedError`) or an unknown name (→ `ValueError`) escaped `main` as a raw traceback at exit 1 (the "regressions found" code) instead of the documented `error:` + exit 2 operator-input contract that every other input to this CLI honors (#93/#94/#99/#111/#116). A typo in `--embedder` in CI thus read as a failing regression, not a config error. `make_embedder` *raising* is the intended library-level fail-loud contract and is unchanged — only the CLI-level translation was missing.

Added a `_resolve_embedder(name)` helper that translates the `NotImplementedError`/`ValueError` to `error:` + returns `None` (matching the `_write_output` print+return-code precedent); each call site returns 2 on `None`. 10 test cases (reserved + unknown `--embedder` → exit 2/no-traceback across run/diff/update, plus a regression guard that the valid `hash` embedder still works). Full suite (381) + ruff green. Verified the repro firsthand before/after. (Gotcha: `run` loads candidates before the embedder, so the `run` test needs a *valid* candidates file or the candidates exit-2 fires first.)

**Why prioritized.** Static priority:high queue globally exhausted; found via the sibling-incomplete-fix / exit-code-contract lens. The prs exit-code contract is now complete across all operator inputs.

**Open questions / blockers.** None — PR ready for review.

## 2026-07-10 — Issue #119: bad --threshold / --warn-band -> exit 2, not a traceback (~25 min, night)

**What got done.** `diff_response`'s fail-loud range guards raise a **bare `ValueError`** for a `--threshold` outside `(0, 1]` or a non-finite / negative `--warn-band` (`diff.py:540/550/552`). The per-snapshot `except` tuples in `_run_command`/`_diff_command` catch only the *typed* diff errors (`EmbedderModelMismatchError` … `WarnBandThresholdError`, all `ValueError` subclasses), so those bare `ValueError`s escaped `main` as a raw traceback at **exit 1** — the "regressions found" code — instead of the documented `error:` + **exit 2** operator-input contract. A `--threshold 5` typo in CI thus read as a failing regression, not a config error. This is the exact sibling of the just-merged #117/#118 (`--embedder` translation); the control `--warn-band 5` raises the *typed* `WarnBandThresholdError` and correctly exits 2, proving the contract its sibling range-guards violate.

Fix: added a `_validate_thresholds(threshold, warn_band)` CLI-entry helper (mirroring `_resolve_embedder`) that translates a bad value to `error:` + return 2, called in `_run_command`/`_diff_command` before the diff loop. `snapshot.tolerance` is already validated to `(0, 1]` at load, so `args.threshold` is the sole ingress that can push `effective_threshold` out of range — the CLI-arg check fully covers the reachable cases. 9 tests (bad values across run/diff → exit 2; valid still exits 0). Full suite + ruff green. Reproduced firsthand.

**Why prioritized.** Static priority:high queue globally exhausted; found via a sibling-incomplete-fix hunt on the just-merged #118 surface, reproduced firsthand.

**Open questions / blockers.** None — PR ready for review.
## 2026-07-11 — Issue #121: validate slot description is a string in ResponseShape (~20 min, night)

**What got done.** `ResponseShape.__post_init__` validated each structured-slot spec's `type` but not the sibling `description`. `extract_slots` (`diff.py:245`, also `_extract_string`) computes `(spec.get("description") or "").lower()`, so a truthy non-string `description` (int/list/dict from a hand-authored snapshot) passed `validate`/`load_snapshot` but raised a raw `AttributeError` at exit 1 the moment `diff`/`run` reached slot extraction — the "regressions found" code, so a config typo read as a failing regression in CI. Schema-parity lens of #99/#115/#117/#119: validated `type`, unvalidated sibling `description`.

Validate `description` as `str | None` in `__post_init__`, raising `SnapshotValidationError` (surfaced by `load_snapshot`/`validate` as a clean finding → exit 2). Six tests (non-string int/float/list/dict/bool rejected; string + absent round-trip). Full suite + ruff green. Reproduced firsthand before/after: a snapshot with `description: 123` went from validate exit 0 + diff raw AttributeError exit 1 → validate reports the finding + diff clean `error:` exit 2. (Needed `update --force --canonical` to re-embed to 128-dim hash first, to get past the embedder dim guards to slot extraction.)

**Why prioritized.** Static priority:high queue globally exhausted; found via the sibling-incomplete-fix / schema-validation-parity meta-lens (a prs hunt agent surfaced it; verified firsthand).

**Open questions / blockers.** None — PR #122 ready for review.

## 2026-07-13 (Night) — Issue #123: architecture tree omitted stats.py (#47) + validate.py (#49)
**Duration:** ~20 min · **Branch:** `session/2026-07-13-0532-issue-123` · **PR:** #124

- The fenced `prompt_regression/` directory tree listed 6 of the package's 8 modules — `stats.py` (#47) and `validate.py` (#49) were absent, even though the doc's own Stats/Validator prose sections and CLI cheatsheet describe both. The arch-doc lock resolves backtick paths + dotted symbols (so the prose refs passed) but never asserted the tree matches the package.
- Crucially, a "basename appears anywhere in the doc" lock (as used for leh #171 / nextjs #83) would have *passed* here since the names live in prose — so the new lock parses the **tree block specifically** and asserts its `*.py` entries equal the `prompt_regression/*.py` module set (bidirectional: omission and stale-leftover both fail), with an inverse guard exercising the real parser + set-diff. Verified it flags exactly `stats.py`/`validate.py` on the pre-fix doc. Full suite 398 pass; ruff clean (had to split a composite assert for PT018).

**Why this work, this session:** the directory-tree-completeness variant of the "arch-doc drift beyond the lock lens" — 4th repo this night (chunking #122 field-label variant, nextjs #83, llm-eval-harness #171, now prs #123).

**Open questions / blockers:** none — ready for review.

**Next session:** among the Python repos only leh and prs had fenced directory trees (rag/lco/ems/vsas/pyasync/aop have none), so this specific variant is exhausted on the Python side. Still to check: the two JS repos (mcp-server-cookbook, ai-app-integration-tests) both have `docs/architecture.md` — check their trees.

## Session 2026-07-13 (night) — issue #125: non-UTF-8 snapshot exits 2, not a raw traceback

A snapshot file containing a non-UTF-8 byte (e.g. a Latin-1 `é` from a hand-edit in a non-UTF-8 editor) raised `UnicodeDecodeError` at the `yaml.safe_load(open(..., encoding="utf-8"))` read seam. `UnicodeDecodeError` is a subclass of `ValueError` — not `OSError` and not `yaml.YAMLError` — so it slipped past the `(OSError, SnapshotValidationError, yaml.YAMLError)` catch tuples that #99/#115 added for the missing-file / bad-YAML / schema-invalid cases, escaping as a raw traceback at exit 1. For `run` and `diff`, exit 1 is the documented "regressions found" code, so a non-UTF-8 snapshot in CI would read as a *failing regression* rather than a config error — the exact harm #99/#115 were filed to eliminate.

The fix adds `UnicodeDecodeError` to the four load-seam catch tuples (`run`, `update`, `diff` in cli.py and `collect_stats` in stats.py → clean `error:` + exit 2) and to the `validate` pre-read (→ the existing `parse` finding). It's the byte-encoding sibling of the same read seam the syntax/schema/IO failure modes already cover. Reproduced all five subcommands firsthand before and after; added five lock tests, one per seam. Full suite green, ruff clean.

**Why this work, this session:** Third hit of the night run, surfaced by the sibling-incomplete-fix dogfood hunt on prompt-regression-suite and verified firsthand across every subcommand.

**Open questions / blockers:** none — PR #126 ready for review.

**Next session:** Phase A merge PR for #125.

## 2026-07-14 (night) — Issue #127: atomic_write_text overflows NAME_MAX on a long basename
**Duration:** ~10 min · **Branch:** `session/2026-07-14-0754-issue-127` · **PR:** #128

The cross-repo `atomic_write_text` temp-name-overflow bug (rag#128 / mcp#96): a destination basename near `NAME_MAX` (255 bytes) overflowed the temp name and raised `OSError` ENAMETOOLONG, though a plain `write_text` succeeds. Reachable from `save_snapshot` and CLI `--out`. Verified firsthand; ported `_cap_base_for_temp`. Full suite (404) green.

**Why this work, this session:** Eleventh hit — cross-repo atomic-write sweep (now fixed in rag, mcp, leh, chunking, lco, ems, prs; pyasync next; vsas deferred).

**Open questions / blockers:** none — PR #128 ready for review.

**Next session:** Phase A merge PR for #127.

## 2026-07-31 — ruff 0.16.1 started formatting Markdown (#129, PR)

CI installs ruff unpinned through `pip install -e '.[dev]'`, and ruff 0.16.1 —
released since the last green run — extended `ruff format` to Python code
blocks *inside Markdown*. Nothing in this repo changed; the tool's scope did.
Six portfolio repos broke the same way on the same day: rag-production-kit,
llm-eval-harness, chunking-strategies-lab and llm-cost-optimizer went red on the
morning's merges, while prompt-regression-suite and python-async-llm-pipelines
were latent, set to go red on their next push.

The trap is version skew. Local venvs still carry 0.15.13, so `ruff format
--check` passes locally and fails in CI; reproducing it at all meant installing
0.16.1 into a throwaway venv. I only found it because my own in-flight PR went
red on lint and `main` turned out to be red too.

Reformatting the Markdown would have been the wrong fix. The lint contract here
has always been "format Python source", and prose is not Python source. The
sharpest case is chunking-strategies-lab, where the same sweep wanted to rewrite
`data/corpus/05_async_pipelines.md` — a pinned benchmark corpus document.
Editing a code block inside it changes the text the chunkers run over and shifts
every canonical metric. A lint tool must never rewrite a benchmark input.

So: `extend-exclude = ["*.md"]`, which re-states the scope the config always
meant, plus a lock test so a future pyproject cleanup can't silently re-expand
it. The test asserts on the config rather than shelling out to ruff, because the
intent needs to be un-droppable and the assertion has to hold on any ruff
version — including ones predating the Markdown feature, which is the very skew
that let this land unnoticed. Amusingly, the lock test itself tripped a *second*
0.16.1 change: UP036 now flags the `sys.version_info >= (3, 11)` tomllib import
guard at `target-version = "py311"`. Lint rules drift on minor releases too, not
just formatter scope.

Pinning a ruff range in `.[dev]` is the deeper fix, but that is a dependency
policy call across six repos rather than a bug fix, so it is flagged for JT
rather than made unilaterally.

## 2026-08-04 — Issue #131: the extractor broke on the pathology it exists to catch

`_extract_number` turned a regex match into a number with a bare `int(raw)` /
`float(raw)`. Both are total for every number a model plausibly writes, and both
fail on exactly one shape: a very long digit run. That is what a degenerate
repetition loop produces — one of the best-known LLM failure modes — so the
extractor fell over on precisely the output a prompt-regression tool exists to
detect.

The two failures are different, and that asymmetry is the part worth carrying
forward.

`int` fails **loudly**. CPython 3.11+ caps int↔str conversion at 4300 digits, and
past that it raises `ValueError`. Nothing in `diff_slots` or `diff_response`
catches it, so it escaped as a raw traceback at exit 1 — the contract #99, #111,
#113, #115, #117, #119 and #126 have been closing everywhere else.

`float` fails **silently**. `float("9" * 400)` doesn't raise; it returns `inf`.
That passed the `isinstance(actual, float)` check as `status: "ok"`, so the
structural channel *approved* a garbage value, and `to_dict()` carried it into
`--format json` as a bare `Infinity` token — which `jq`, a browser `JSON.parse`
and Go/Rust decoders all reject, taking the whole document with it.

So a try/except around the coercion would have fixed half the bug and left the
worse half. The guard has to check finiteness explicitly. That generalises:
wherever untrusted text is coerced to a number, `int` overflows loudly and
`float` overflows quietly, and only one of those is visible in a traceback.

The fix makes the coercion total. An unrepresentable match is skipped and the
next one tried; if none is representable the slot reports `missing`, which
already carries a failing verdict. No new status, no change to the `--json`
contract.

Skipping rather than bailing also fixes a smaller thing: one bad token near the
hint word used to poison the whole extraction even with a perfectly good number
in the same sentence. There is a real tradeoff there, and I flagged it for JT
rather than burying it — a response containing both a garbage run and a real
number can now report `ok` on the more distant number. I chose that direction
because the stricter reading turns previously-working extractions into failures,
and because a genuine repetition loop has no other number in it, so it still
lands on `missing`.

Behaviour is unchanged for everything representable. `sorted` is stable, so the
head of the distance ordering is exactly the match `min(...)` picked before. The
parametrized tests pin hint proximity, the first-match fallback, the `W-2`
lookbehind guard, the `.5` and `3.` float shapes, a real negative, and a
4299-digit integer that must still extract — the guard rejects only what cannot
be represented, not merely what is big.

One test-writing note worth keeping. Python's `json.loads` accepts bare
`Infinity` and `NaN`, so asserting that the output round-trips through
`json.loads` would have passed on exactly the broken output. The tests parse with
a `parse_constant` that raises instead.

Also deleted `err.txt` and `err2.txt`, untracked debris an earlier session left
at the repo root. Never committed, so nothing to revert.

421 passed. Shipped as PR #132.

## Session 2026-08-06 — `validate`: one unreadable file took the whole report down (#133)

`prompt_regression/validate.py` exists for one reason, and its module
docstring says so in its opening paragraph: `prompt-snap run` aborts on
the first malformed snapshot, "a directory of 30 snapshots with two bad
ones forces the operator into fix-and-retry cycles," and this module
walks the files "in one pass, collect[ing] every problem."

One file that couldn't be *read* defeated that completely. A `chmod 000`
snapshot, a directory whose name ends in `.yaml` (the globs match a
directory just as happily as a file), or a broken symlink raised
`OSError` at the per-file read seam. Nothing in the collecting loop
caught it, so it escaped `validate_snapshots`, landed in the CLI's
*directory-level* `except OSError` arm, and printed a single line:

```
error: failed to walk snapshots directory: [Errno 13] Permission denied: '.../aaa_unreadable.yml'
exit=2
```

The walk had succeeded. One file had failed. And the report the operator
needed — three findings across the other four files in that directory,
including a schema-invalid snapshot and a duplicate-id collision — was
gone. They fix the permission, re-run, and only then learn about the
other two: exactly the fix-and-retry loop the module was written to end.

### The same seam already handled this file's other failure mode

The `path.open(...)` / `yaml.safe_load(...)` block already routed one
read-time failure into a finding, and the comment there reasons about
precisely this spot:

> `UnicodeDecodeError` (a `ValueError` subclass, not a `YAMLError`)
> surfaces **at this same read seam** when the file isn't valid UTF-8 —
> a decode failure is a parse failure, so route it to the same `parse`
> finding rather than letting it escape as a raw traceback at exit 1.

A *decode* failure was brought into collecting mode. Its *read* sibling
was not. That is the whole bug: one seam, two failure classes, one of
them handled.

`unreadable` gets its own code rather than reusing `parse`, because
nothing was parsed, and an operator routing on the code needs to go fix
a filesystem problem, not a snapshot's contents — the same reasoning
that split `schema_version` out of `schema` in the first place.
`load_snapshot(path)` re-opens the file, so that is a genuinely separate
read seam (the file can vanish between the two opens); it gets its own
arm and its own test.

### It also makes an existing promise true

Both sibling walkers, `stats` and `run`, abort on an unreadable file —
which is *correct*, they're aggregators, not collectors — and point the
operator here:

```
hint: run 'prompt-snap validate <dir>' to list every malformed snapshot in one pass.
```

Until now that hint was false for exactly the input that produced it:
`validate` reached the same file and died the same way. It's true now.

### The code list was documented in three places and derived in none

`parse | schema_version | schema | duplicate_id | empty` lived in the
module docstring, in the README's `validate` bullet, and implicitly in
the emit sites — with nothing tying the three together. Adding a sixth
code meant remembering all three by hand. So the list is now a
module-level `FINDING_CODES` tuple with three locks against it: the emit
sites, the docstring bullets, and the README span.

The emit-site lock reads the **AST**, not the file's text. The module
docstring quotes every code in backticks, so a text scan would count the
documentation as an emit site and the lock would pass no matter what —
the same vacuous-lock trap embedding-model-shootout hit in #112.

### Verification

429 tests green. For the anti-vacuous check I reverted *only the two
`except OSError` arms*, not the whole file — dropping `FINDING_CODES`
would break test collection, and a suite that never runs its assertions
proves nothing. On that tree the four behavioural tests fail and the
AST-derived code lock fails; the docstring and README locks correctly
stay green, since they key off `FINDING_CODES`, which the revert didn't
touch.

The `chmod 000` fixture is named `aaa_locked.yml` so it sorts *first* —
pinning that the loop continues past a failure rather than merely
tolerating one at the end. That test skips under root, where permission
bits don't apply; CI runs `ubuntu-latest` as a non-root user, so it
executes there.

### Filed, not fixed

`test_stats_globs_match_run_subcommand_globs` is vacuous: its
`or set(...).issuperset({"*.yml", "*.yaml"})` arm makes the assertion
unfalsifiable, and the source comment claims "the test pins the values
verbatim," which it does not. There's no present harm — `*.yaml` already
matches `foo.snapshot.yaml`, so the two glob sets are equivalent today —
so it's a separate issue rather than scope drift into this one.

## 2026-08-07 — the CI example pointed at a directory that never existed (#136)

The README's flagship CI example — "CI doesn't need the Python detour" —
told readers to run `prompt-snap run --snapshots tests/snapshots
--candidates tests/candidates.jsonl`. Neither path has ever existed here.
There is no `tests/snapshots`, and no `.jsonl` file anywhere in the tree, so
the command exits 2 on a fresh clone. The repo does ship snapshots, under
`examples/snapshots/`, and every other README reference already used that
path. Only this one block invented a `tests/` location.

It was found by porting a lens from llm-eval-harness: a README path lock
that enumerates markdown-link parentheses never looks inside a code fence,
which means it never checks a single path a reader is actually told to type.
Running that probe across all twelve repos produced three candidates, and
two of them turned out to be fine — command *outputs*, annotated `# →
writes ...`, correctly absent until you run the thing. This was the one real
input. One genuine hit per twelve repos is a decent return for a probe that
takes a minute.

My own sweep pattern had a hole worth remembering: it required a dot and an
extension, so it found `tests/candidates.jsonl` but missed `tests/snapshots`
— the *directory*, which is what the command trips over first.

The same section had a second problem. The other `run` example printed
`total=2 failed=0` with cosines of 0.940 and 0.967 against snapshot files
that don't exist. Those numbers were never produced by anything. That's the
no-fabricated-benchmarks rule at documentation scale, and it's now measured
output.

Building the fixture turned up a smaller lesson. My first candidate response
was a copy of the snapshot's canonical text, which scored a perfect 1.000
and therefore demonstrated nothing at all. The committed one is a real
rewording that lands at 0.806 — above that snapshot's own 0.75 tolerance,
below the 0.85 run default — so the per-snapshot override is visibly the
thing that lets it pass. The test asserts that band rather than the digit,
so it encodes the intent without breaking if the embedder is ever tuned.

The judgement call was what to do about the second snapshot, which reports
`error` rather than a verdict. Its stored embedding is the illustrative
eight-dimensional vector, so the default hash embedder refuses to compare
against it. There's a `--force-embedder` flag that would make the example
green. Using it in the flagship CI example would teach exactly the habit
this repo exists to prevent — comparing vectors from two different models —
so the README now explains the error instead. A real error verdict is better
documentation than a fabricated green one.
## 2026-08-07 — a parity lock that had already been broken for months, quietly passing (#135)

Three modules kept their own copy of the snapshot glob tuple, each behind a
comment asking whoever came next to keep them in sync. They had already
fallen out of sync: `stats` carried two patterns where `cli` and `validate`
carried four.

The test that existed to catch exactly this could not fail. Its second `or`
arm compared the stats tuple against the literal `{"*.yml", "*.yaml"}` — and
the stats tuple *was* that literal, so the assertion held no matter what the
runner did.

The sharpest part is the docstring. It said: "if `run` ever extends to
`*.snapshot.yaml`, the stats walker has to follow." But `run` already had
`*.snapshot.yaml`, and `stats` hadn't followed, and the test was green. A
condition written in the future tense turned out to be a claim about the
present that nobody had rechecked. That's worth carrying forward as a lens in
its own right.

The intent was never ambiguous, because the repo locks the same tuple twice:
`test_validate.py` uses strict equality with no escape arm. When one of two
locks over a single constant is strict and the other isn't, the strict one is
the evidence.

No files were actually being missed. `*.yml` and `*.yaml` match everything
`*.snapshot.yml` and `*.snapshot.yaml` match, so the walked set was identical
— by accident, not design, and only for as long as every future pattern
happens to be a subset. What *had* diverged visibly was the operator-facing
text: the three subcommands printed different "patterns considered" lists,
and their `--help` strings had drifted three separate ways, with `run` naming
one pattern, `stats` two, and `validate` none, while all three walked the
same files.

The fix is mechanism instead of a better comment. `io.py` imports only
`schema.py`, and all three modules already import `io` — so it sidesteps the
circular import that `validate.py`'s own comment gives as the reason it needed
a second copy. Each of the three duplicated walkers carried a docstring
explaining why duplication was unavoidable ("importing from cli would pull in
argparse machinery"), and each was correct about `cli` and beside the point.

Replacing an unfalsifiable test carries an obvious trap, so the check that
mattered most was proving the new one *can* fail: I put the old two-pattern
tuple back and confirmed both replacement tests go red on the exact state the
original passed on.

## 2026-08-12 — a dormant bug that fixing its callee would have armed (#140)

`cli._write_output` says in its own docstring why it exists: every `--out` site
called `atomic_write_text` bare, so an unwritable path escaped as a traceback
at exit 1. That sweep enumerated the library CLI's `--out` sites. It never
enumerated `scripts/`, and both files there had the same seam.

The interesting part isn't the seam, it's the interaction.
`capture_demo._run_render_demo_into` raised an uncaught `RuntimeError` whenever
the render script returned non-zero. That was harmless — but only because
`render_regression_demo.main` never returned non-zero for a write failure. It
let the `OSError` escape straight through, so the `rc != 0` branch was dead
code.

Giving the render script its exit-2 guard is exactly what arms that raise. Fix
the render script on its own and the `capture_demo` path is no better off: it
trades an `OSError` traceback for a `RuntimeError` traceback and now also
throws the exit code away. Worse, it would look fixed — any test driving the
render script directly would go green.

Worth carrying forward: **before teaching a callee to return a non-zero code,
grep its callers for `if rc != 0: raise`.** A wrapper that's inert while the
callee only ever returns 0 goes live the moment it doesn't. It's the inverse of
the llm-cost-optimizer case earlier in this run, where the same laundering
shape was already firing.

That's also why the anti-vacuous check was run per file rather than once.
Reverting the render script alone puts 5 tests red; reverting `capture_demo`
alone puts 9 red; and the propagation test is red under *either*. That's the
demonstration, rather than the argument, that neither half closes the path on
its own.

One small design note. The `--out-png` guard fires after the HTML has already
been written and announced. A guard that made the whole run look failed would
have been its own bug, so the test asserts both things at once: exit 2, and the
HTML exists and was reported.
