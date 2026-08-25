# Architecture

`prompt_regression/` is a small Python package: one snapshot schema +
one diff function + one HTML renderer + one CLI binding them
together. Six shipped feature issues map to today's surface; the
hygiene surfaces (#12, #14, #17, #19, #22) are snapshot tests that
keep the README, the demo HTML, the public surface, and the CLI
glob behavior honest as the package evolves.

```
prompt_regression/
├── schema.py        ← #1: Snapshot / Prompt / ResponseShape / CanonicalResponse
├── io.py            ← #1: YAML load/save with round-trip identity
├── diff.py          ← #2, #10: semantic similarity + structured slot-shape diff
├── html_report.py   ← #3: single-file HTML with inline SVG
├── cli.py           ← #5: prompt-snap run | update | diff
├── stats.py         ← #47: population-level directory summary (collect_stats)
├── validate.py      ← #49: collecting-mode directory lint (validate_snapshots)
└── __init__.py      ← public surface (#19)
```

Tests in `tests/`; supporting docs and the committed worked-regression
HTML in `docs/`; the demo's regen script in `scripts/`.

## Integrated comparison flow

```mermaid
flowchart LR
    classDef shipped fill:#dcffe4,stroke:#22863a,color:#000

    AuthorPrompt["Author a prompt"]:::shipped --> Capture["Capture canonical response<br/>(model + text + embedding)"]:::shipped
    Capture --> SnapYAML["snapshot.yml<br/>(prompt + shape + canonical)<br/>(#1)"]:::shipped

    NewResp["New response<br/>(after model change)"]:::shipped --> Diff["Diff layer<br/>(#2, #10)<br/>· structured slot enforcement<br/>· embedding cosine<br/>· per-snapshot tolerance"]:::shipped
    SnapYAML --> Diff
    Diff --> Report["HTML diff report<br/>(#3)"]:::shipped
    Report --> Reviewer["Reviewer reads<br/>regression"]:::shipped

    Diff -- "exit 1 if drift > threshold" --> CLI["prompt-snap CLI<br/>(#5)"]:::shipped
    CLI --> CI["CI status"]:::shipped
```

## Layer 1 — Snapshot schema (#1)

`Snapshot` / `Prompt` / `ResponseShape` / `CanonicalResponse`
dataclasses with strict YAML load/save semantics (D-002 — stdlib
`dataclasses` plus a manual validation pass, deliberately not
pydantic; the schema is small enough that a runtime dep buys
nothing and complicates the optional-extras story). The canonical
response embedding is stored inline in the snapshot YAML as a
list of floats (D-003 — one file is the whole snapshot, no
sidecar `.npy` blob to forget to commit). Round-trip identity
guaranteed by `tests/test_io.py`. The schema captures everything the
diff layer needs at runtime:

- **`prompt`** — model id, user/system messages, sampling params.
  Input side of the regression: if any of these change, drift is
  *expected*, not a bug.
- **`response_shape`** — what a future response must continue to
  satisfy. Split into `semantic_categories` (soft, scored by
  similarity) and `structured_slots` (hard, enforced by typed
  extraction).
- **`canonical`** — the reference response (text + inline embedding +
  embedding model name).
- **`tolerance`** — optional per-snapshot override (#10).
  Defaults to the global threshold; bumped to `1.0` for snapshots
  intentionally allowed to drift, lowered for stricter cases.

See [`docs/schema.md`](schema.md) for the field-by-field spec.

## Layer 2 — Diff (#2, #10)

`diff.py` consumes a Snapshot + a new response and returns
`{score, slot_deltas, verdict}`. Two axes, ANDed for the final
verdict (D-004 — both channels must pass; a slot mismatch fails
the verdict even when cosine looks fine, and a soft-similarity
drop fails it even when slots happen to align):

- **Structured slot diff** — typed extraction against
  `structured_slots`. A slot mismatch is *hard*: any slot diff fails
  the verdict regardless of similarity.
- **Semantic similarity** — embedding cosine between the canonical
  text and the new response. The `Embedder` is a single-method
  Protocol (D-005 — `embed(text) -> list[float]`, parallel to the
  portfolio-wide one-seam-one-method pattern). The diff refuses
  to compare when `canonical.embedding_model` doesn't match the
  current embedder's model name (D-006 — silent model mismatch
  produces meaningless cosine scores; better to fail loud with the
  two names quoted than to ship a green verdict on apples-vs-oranges
  vectors). Default global threshold 0.85; per-snapshot tolerance
  override (#10) lets you tighten or relax per case.

The diff is pure-function: no IO, no global state. Tests in
`tests/test_diff.py` and `tests/test_tolerance.py`.

`DiffResult` / `SlotDelta` / `SemanticCategoryScore` each carry an
explicit `.to_dict()` (#51) with a field-by-field contract — no
`dataclasses.asdict` reliance — so a future internal-only field on
any of them can't silently leak into the `prompt-snap diff --json`
or `prompt-snap run --json` output that CI annotators and ad-hoc
scripts bind to. Same observability-parity shape shipped in
`llm-cost-optimizer`, `rag-production-kit`, `python-async-llm-pipelines`,
and `vector-search-at-scale`.

`Snapshot.to_dict()` is also explicit-field (#51): preserves the
existing None-drop tidy-up for `notes` / `tolerance` (kept absent
in YAML when unused) while pinning the eight-field surface that
committed `snapshots/*.yaml` consumers depend on. Nested sections
(`prompt`, `response_shape`, `canonical`) delegate to their own
`to_dict` so the nested shapes are pinned by the nested classes'
contracts.

## Layer 3 — HTML report (#3)

`html_report.py` renders a `DiffResult` into a single self-contained
HTML file: inline SVG sparklines, inline styles, no CDN, no JS
(D-007 — one file an operator can drop into a PR comment, email,
or static-site bucket; no asset pipeline to maintain). The
committed worked regression at `docs/regression_demo.html` (#4)
demonstrates a synthetic-but-realistic drift surfacing through the
toolchain (D-008 — responses are synthetic and the demo HTML
labels them as such; an operator swaps the two strings in
`scripts/render_regression_demo.py` for a real captured
before/after when a real model upgrade lands, no other change
required).

`tests/test_html_report.py` covers the renderer. The committed HTML
itself is locked to the renderer output by
`tests/test_regression_demo_snapshot.py` (#12) — so a future tweak to
the renderer can't silently desync the committed file from what the
script would produce.

## Layer 4 — CLI (#5)

`cli.py` is the single argparse entry point binding the schema, diff,
and renderer:

```
prompt-snap run    [SNAPSHOT]...    # run snapshots, exit non-zero on regression
prompt-snap update [SNAPSHOT]...    # re-baseline (requires --force)
prompt-snap diff   SNAPSHOT INPUT   # one-off diff against a candidate text
prompt-snap stats  DIRECTORY        # population-level summary (#47)
prompt-snap validate DIRECTORY      # collecting-mode lint (#49)
```

`update --force` is the accidental-rebaseline guard: `update` without
`--force` exits with a clear "did you mean to overwrite?" message.
`prompt-snap run`'s glob expansion was tightened by #22 so the
committed example snapshots are findable from any working directory;
locked by the matching test in `tests/test_cli.py`.

## Cross-cutting surfaces

- **Public surface lock (#19).** `tests/test_public_surface.py`
  pins `prompt_regression.__version__` and asserts every name in
  `__init__.py`'s `__all__` resolves.
- **README defaults snapshot (#17).**
  `tests/test_readme_defaults_snapshot.py` locks the README's quoted
  defaults / identifier claims to the source.
- **HTML demo snapshot (#12).**
  `tests/test_regression_demo_snapshot.py` locks the committed
  `docs/regression_demo.html` to the renderer output.
- **README session-framing pivot (#14).** Drove the previous round
  of README rewrites; the snapshot tests above are the lock against
  reverting.
- **CLI glob fix (#22).** Tightened `prompt-snap run`'s default
  glob so committed example snapshots are findable from any
  working directory; locked by `tests/test_cli.py`.
- **Stats (#47).** `prompt_regression.stats.collect_stats(directory)`
  walks a snapshots dir (same globs `run` uses) and returns a
  `StatsReport` with per-`prompt.model` / per-`canonical.embedding_model`
  / per-`schema_version` / per-`structured_slots`-count histograms plus
  a `ToleranceDistribution` summary (count_default + count_explicit +
  count_strictest + min/median/max). Exposed as `prompt-snap stats`;
  locked by `tests/test_stats.py`.
- **Validator (#49).** `prompt_regression.validate.validate_snapshots(directory)`
  walks the same globs in *collecting* mode and surfaces every
  malformed file as a `ValidationFinding` (codes `parse |
  schema_version | schema | duplicate_id | empty`). Unlike `stats`,
  which silently skips load failures, the validator anchors the
  per-file errors `prompt-snap run` would abort on, so an operator
  can fix all of them before the next run. Exposed as `prompt-snap
  validate`; exit codes 0/1/2 (clean / findings / missing-dir); JSON
  contract via `ValidationReport.to_dict`. Pairs with `stats` (audit
  the healthy population) and `run` (consume it). Locked by
  `tests/test_validate.py`.

## Type checking (D-009)

A non-strict `mypy` gate runs over `prompt_regression` in the CI lint
job and again as `tests/test_mypy_clean.py`, both invoking a **bare**
`mypy` so they read exactly the `[tool.mypy]` block in
`pyproject.toml` — the test, the CI step and a developer's local run
therefore cannot drift to different scopes.

The rationale differs from two of the three sibling repos that already
have one. `llm-eval-harness` (D-016) and `llm-cost-optimizer` (D-014)
justify theirs by shipping a `py.typed` marker, so their annotations
are a downstream contract. This package ships no marker; the case here
is **latent green** rot, and #146 is the evidence rather than the
hypothesis — six errors sat on a green `main` until someone ran `mypy`
by hand while working an unrelated issue.

Four of those six were `Library stubs not installed for "yaml"`, which
is a *dependency* gap and not a code defect: the import is real and
resolvable, only its types were missing. `types-PyYAML` in the `dev`
extra is the honest fix, so no blanket `ignore_missing_imports` and no
per-module override are needed — either would have silenced a genuine
typo just as effectively. The other two were annotation slips in
`diff.py` (a name rebound across a branch chain, and a dict whose mixed
`type` / `tuple[type, ...]` values widened to `object` and made an
`isinstance` call uncheckable). Neither masked a defect — but a real
one was found in the same file while checking, and is tracked as #147.

Scoped to the package, matching all three siblings. `mypy
prompt_regression scripts tests` reports 17 further errors across 12
files; note that `mypy` *starts* here, unlike
`chunking-strategies-lab`, where a module-name collision stopped it
before checking anything — so widening the scope is real separate work
rather than blocked work.

## What's deliberately not in the suite

- **Replacing `llm-eval-harness`.** That repo does dataset-style
  scoring; this one does snapshot-style testing. The boundary is
  documented in the README's "What this is" section.
- **A web UI.** Per handoff §2, "CLI + CI is enough." Single-file
  HTML reports are the user surface.
- **Online embedding for the diff.** The embedding model is named in
  `canonical.embedding_model` and applied locally; the diff itself
  doesn't make network calls.

## Unmatched candidates are an input error (D-010)

`prompt-snap run` derives its exit code from `failed`, so a candidate
row whose key matched no snapshot used to be dropped silently and the
run exited 0 having verified nothing. Measured on the shipped
`examples/`, changing only the two keys:

| candidates file | summary | exit |
|---|---|---|
| correct (control) | `total=2 failed=1 skipped=0` | 1 |
| zero rows | `error: no candidate rows loaded` | 2 |
| 2 rows, neither key matches | `total=2 failed=0 skipped=2` | **0** |
| 2 rows, one key matches | `total=2 failed=0 skipped=1` | **0** |

`_load_candidates` already refused the zero-row file — a run with
nothing to check is meaningless — and the all-orphan file reaches the
same state by a quieter road. An unmatched key is now reported by name
(`unmatched=N` in the summary, `unmatched_candidates` in `--format
json`) and exits 2, the repo's code for an operator input error.

There is deliberately **no** separate `skipped == total` rule. A
partial candidates file has `skipped > 0` and zero orphans — a
legitimate workflow that stays green — and the only other route to
`skipped == total` is a zero-row file, already handled. A second rule
could only fire where this one does, while risking a false positive on
the partial run.

`--allow-unmatched-candidates` covers the one legitimate case: a single
candidates file shared across several snapshot directories. It turns
off the failure, not the report.

## Where to look next

- **Layer code** — `prompt_regression/<module>.py` per the directory
  diagram above.
- **Per-layer tests** — `tests/test_<layer>.py`.
- **Demo regen** — `scripts/render_regression_demo.py`,
  `docs/regression_demo.html`,
  `tests/test_render_regression_demo.py`,
  `tests/test_regression_demo_snapshot.py`.
- **Design decisions** — `MEMORY/core_decisions_human.md` for prose,
  `MEMORY/core_decisions_ai.md` for the structured log.
