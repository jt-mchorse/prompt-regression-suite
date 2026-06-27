# prompt-regression-suite
> Snapshot testing for prompts. Catches semantic drift on model upgrades using embedding-similarity diffs with configurable tolerances and HTML reports.

![CI](https://github.com/jt-mchorse/prompt-regression-suite/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

## What this is

A model upgrade is a silent refactor of every prompt in your app. The output
still looks plausible, the tests still pass, and yet a thing you depended on
— the format of the answer, the slot it filled, the topic it stayed on — has
quietly shifted. `prompt-regression-suite` is the dedicated layer that
catches that drift. You record a snapshot of a prompt's canonical response
once, and from then on every model change is checked against the snapshot's
structural expectations and the embedding similarity of the new response to
the original.

The snapshot itself is a plain YAML file checked into your repo
alongside the prompt it covers, so diffs to expected behavior show up
in pull requests the same way diffs to code do. Six closed issues map
to today's surface:

- **Snapshot schema + loader** (#1) — YAML `Snapshot` / `Prompt` /
  `ResponseShape` / `CanonicalResponse`, round-trip identity guaranteed.
- **Semantic similarity diff** (#2) — embedding-similarity + structured
  slot-shape diff with a configurable per-snapshot tolerance.
- **HTML report** (#3) — single-file HTML with inline SVG so the
  report ships as one artifact and renders without a CDN.
- **Caught regression** (#4) — `docs/regression_demo.html` is a real
  before/after pair demonstrating a synthetic-but-realistic drift
  surfacing through the toolchain. An operator-recorded real
  regression swaps the two strings in
  `scripts/render_regression_demo.py` and re-runs the same script.
- **CLI** (#5) — `prompt-snap run | update | diff | stats | validate`,
  with `--force` on `update` to defend against accidental re-baselining.
  `stats` (#47) walks a snapshots dir and emits a population-level
  summary (per-model / per-embedder / per-tolerance histograms) so an
  operator can audit the snapshot population before a big upgrade.
  `validate` (#49) walks the same dir in *collecting* mode and surfaces
  every malformed file in one pass (codes `parse | schema_version |
  schema | duplicate_id | empty`); pre-flight before `run` so a bad
  snapshot doesn't abort the run partway through.
- **Per-snapshot tolerance** (#10) — `Snapshot.tolerance` overrides
  the global default. It's the required cosine floor (`cosine >=
  tolerance` passes), so **lower** it (e.g. `0.6`) for snapshots
  intentionally allowed to drift, and **raise** it toward `1.0` for the
  ones you want strict (`1.0` passes only an identical response).

Everything in this repo is narrow on purpose: it does *not* replace
[`llm-eval-harness`](https://github.com/jt-mchorse/llm-eval-harness) —
that covers golden datasets and LLM-as-judge evals. This one is
snapshot-style only.

[#1]: https://github.com/jt-mchorse/prompt-regression-suite/issues/1
[#2]: https://github.com/jt-mchorse/prompt-regression-suite/issues/2
[#3]: https://github.com/jt-mchorse/prompt-regression-suite/issues/3
[#4]: https://github.com/jt-mchorse/prompt-regression-suite/issues/4
[#5]: https://github.com/jt-mchorse/prompt-regression-suite/issues/5
[#10]: https://github.com/jt-mchorse/prompt-regression-suite/issues/10
[#49]: https://github.com/jt-mchorse/prompt-regression-suite/issues/49

## Architecture

```
your repo/
└── snapshots/
    └── refund_window_v1.yml   ← snapshot lives next to the prompt
                                  it covers; PRs to expected behavior
                                  are visible in the file's diff

prompt_regression/
├── schema.py   ← Snapshot / Prompt / ResponseShape / CanonicalResponse
└── io.py       ← load_snapshot / save_snapshot (YAML, round-trip identity)
```

See [`docs/schema.md`](docs/schema.md) for the full field reference and
[`docs/architecture.md`](docs/architecture.md) for how the diff and report
layers plug in, plus the design decisions behind each layer (D-002…D-008).

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# Tests, lint, format check
pytest
ruff check .
ruff format --check .
```

Load and save snapshots from Python:

```python
from prompt_regression import (
    Snapshot, Prompt, ResponseShape, CanonicalResponse,
    load_snapshot, save_snapshot,
)

s = load_snapshot("examples/snapshots/refund_window_v1.yml")
print(s.prompt.model, s.response_shape.structured_slots)
save_snapshot(s, "out/refund_window_v1.yml")
```

The committed example at `examples/snapshots/refund_window_v1.yml` is the
working reference for the schema — see [`docs/schema.md`](docs/schema.md)
for the field-by-field spec.

## Diff layer (#2)

`diff_response(snapshot, candidate, *, embedder, threshold=0.85)` compares
a new response against a stored snapshot along two channels:

- **Cosine similarity** between the candidate's embedding and the snapshot's
  stored canonical embedding.
- **Structured-slot extraction** against the snapshot's `structured_slots`
  declarations — every slot must be present and type-correct in the
  candidate.

The verdict is the AND of both channels. Cosine alone (which "passed" but
the slot extraction failed) is not enough — the snapshot's structural
assertions are hard requirements.

```python
from prompt_regression import HashEmbedder, diff_response, load_snapshot

snap = load_snapshot("examples/snapshots/refund_window_v1.yml")
candidate = "The Pro plan has a 14-day refund window from purchase."

result = diff_response(snap, candidate, embedder=HashEmbedder())
print(result.verdict)            # "pass" | "warn" | "fail"
print(result.cosine_score)
print(result.slot_deltas)        # per-slot extraction verdicts
```

The embedder is a pluggable Protocol — same single-method shape adopted
across the portfolio. `HashEmbedder` is the dep-free fallback that lets
CI exercise the diff flow hermetically; production callers BYO via the
Protocol (Cohere, Voyage, OpenAI, sentence-transformers all conform).

The diff layer **refuses** to compare against a snapshot whose
`embedding_model` differs from the current embedder's name (D-006) — pass
`force=True` to override. The default refusal is a deliberate
footgun-prevention guard: a silently re-embedded comparison is the kind
of bug that produces false PASSes that look like the suite is working.

### Per-snapshot tolerance (#10)

The run-level `threshold` is the right default for *most* snapshots, but
real suites mix tight extraction prompts (where 0.85 is sometimes too
lenient) with loose creative prompts (where 0.85 fails on legitimate
paraphrases). Pin a per-snapshot value on the snapshot itself rather
than running two passes with different `--threshold` values:

```yaml
id: creative-kite-poem-v1
prompt: { model: claude-haiku-4-5-20251001, user: "Write a brief, evocative poem..." }
# ...
tolerance: 0.75    # cosine bar for this snapshot only
notes: |
  Tolerance lowered to 0.75 — creative-writing prompt with high-temp
  sampler; legitimate paraphrases would false-fail at the default 0.85.
```

When `tolerance` is set, `diff_response` ignores the per-run `threshold`
kwarg for *that snapshot* and uses the pinned value instead. The
`DiffResult.threshold` field carries the *effective* threshold so HTML
reports and PR comments always show the number that was actually
applied. Absent / `null` means "use the run-level default."

`examples/snapshots/creative_kite_v1.yml` ships as a worked example.

## HTML report (#3)

A self-contained HTML report renders one section per snapshot, with the
embedding-cosine score, a semantic-category table, per-slot deltas, and
the two responses side-by-side. Anchor links (`#snapshot-<id>`) make a
CI artifact URL deep-linkable to a single failure. No JS, no external
assets:

```python
from prompt_regression import HashEmbedder, ReportEntry, diff_response, render_report

embedder = HashEmbedder()
results = [
    ReportEntry(
        snapshot_id=snap.id,
        diff=diff_response(snap, candidate_text, embedder=embedder),
        candidate_text=candidate_text,
        baseline_text=snap.canonical.text,
    )
    for snap, candidate_text in your_snapshots_and_candidates
]
Path("report.html").write_text(render_report(results), encoding="utf-8")
```

CI doesn't need the Python detour — `prompt-snap run` takes `--format html` and `--out` directly:

```bash
prompt-snap run \
    --snapshots tests/snapshots \
    --candidates tests/candidates.jsonl \
    --format html \
    --out report.html
```

`--format html` requires `--out` (HTML writes to a file, not stdout); `--out` works for `text` and `json` too.

Verdict colors mirror the diff layer's vocabulary (D-007): `pass` green,
`warn` amber, `fail` red. Passing sections collapse to a one-line note —
the report stays scannable when most snapshots are green.

## Regression demo (#4)

`scripts/render_regression_demo.py` runs an end-to-end demo: a baseline
snapshot for a "refund window for the Pro plan" prompt versus an
"upgraded" model's response that drops the eligibility-caveat slot and
phrases the window as "two weeks" instead of "14 days". The diff layer
catches both regressions (slot extraction misses the integer; the
semantic similarity drops below threshold), and the HTML report renders
the failure as a single artifact.

```bash
python scripts/render_regression_demo.py --no-screenshot
# → docs/regression_demo.html  (verdict: fail, cosine: 0.218)
```

A screenshot is generated automatically when Playwright or
`wkhtmltoimage` is available locally; the script falls back to writing
just the HTML when neither is installed.

**Honest disclosure (D-008).** The two responses are synthetic — clearly
labeled in the snapshot's `notes` field and in this section's title. The
diff layer and the report renderer don't care whether the inputs are
synthetic or recorded from real model versions; the path to a real
captured regression is "replace the two text constants in the script
with recorded responses and re-run". A future operator-run version
against real Anthropic API output drops in the same way.

## CLI: `prompt-snap` (#5)

`pip install -e .` installs the `prompt-snap` console script with
three subcommands. The dep-free `HashEmbedder` is the default; the
`--embedder` flag accepts `hash` today and reserves `voyage` /
`openai` / `cohere` for follow-up integrations (they raise a clear
"not yet wired" error rather than silently using a stale stub).

```bash
# Walk a snapshot dir, diff each against candidates in a JSONL, exit non-zero on any fail.
prompt-snap run \
    --snapshots ./snapshots \
    --candidates ./candidates.jsonl
# # prompt-snap run  total=2 failed=0 skipped=0
# verdict   cosine   snapshot
# -------- --------  ------------------------
# pass      0.940    snapshots/refund-policy.snapshot.yaml
# pass      0.967    snapshots/shipping-policy.snapshot.yaml

# Ad-hoc diff: one snapshot vs one candidate. Exits 1 on fail.
prompt-snap diff \
    --snapshot snapshots/refund-policy.snapshot.yaml \
    --candidate "Refunds are now available for 30 days after purchase."
# verdict: warn
# cosine:  0.812 (threshold 0.85)
# ...

# Re-baseline a snapshot after an intentional change. REQUIRES --force.
prompt-snap update \
    --snapshot snapshots/refund-policy.snapshot.yaml \
    --canonical "Refunds are available for 30 days after purchase." \
    --force
```

The candidates JSONL row shape is
`{"snapshot": "<path-relative-to-snapshots-dir>", "candidate": "<text>"}`
or `{"id": "<snapshot.id>", "candidate": "<text>"}`; the lookup tries
the relative path first, then falls back to the id.

`run` walks `*.snapshot.yaml`, `*.snapshot.yml`, `*.yml`, and `*.yaml`
under the supplied dir, merging the matches deduped. The opinionated
`*.snapshot.yaml` convention is preferred for fresh projects (clearly
distinguishes snapshot files from other yaml in the repo), but the
plain `.yml` / `.yaml` extensions also work — the committed
`examples/snapshots/*.yml` files are picked up by either convention.
If the walk finds zero snapshots the command exits 2 with the
considered-globs list in the error, so a pointed-at-the-wrong-dir run
fails loud instead of silently scanning nothing.

`run` and `diff` accept `--format json` for downstream tooling, and
both honor the embedder-vs-snapshot-model guard (D-006); pass
`--force-embedder` to override. `update` defends against accidental
re-baselining by requiring `--force` explicitly — running it without
the flag exits 2 with a clear message.

## Benchmarks / Results

*Real-LLM regression captured under [#4] is shipped as a synthetic
demo here (`docs/regression_demo.html`); a real recorded regression
replaces the two strings in `scripts/render_regression_demo.py` and
re-runs the same script.*

## Demo

The runnable surface today is two commands:

```bash
# Regenerate the synthetic regression report (built by #4).
python scripts/render_regression_demo.py

# Inspect the result in a browser.
open docs/regression_demo.html
```

A captured 60-second video (showing the report side-by-side with a
`prompt-snap diff` invocation) is tracked in **#15**.

## Why these decisions

See [`MEMORY/core_decisions_human.md`](MEMORY/core_decisions_human.md).

## License

MIT
