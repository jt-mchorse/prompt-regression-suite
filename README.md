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

The snapshot itself is a plain YAML file checked into your repo alongside
the prompt it covers, so diffs to expected behavior show up in pull
requests the same way diffs to code do. Issue [#1] ships the schema and the
loader/saver; issue [#2] adds the embedding-similarity + structured-slot
diff function on top of it; issue [#3] adds the HTML report; issue [#4]
documents a real regression caught with the resulting toolchain. Everything
in this repo is narrow on purpose: it does *not* replace
[`llm-eval-harness`](https://github.com/jt-mchorse/llm-eval-harness) — that
covers golden datasets and LLM-as-judge evals. This one is snapshot-style
only.

[#1]: https://github.com/jt-mchorse/prompt-regression-suite/issues/1
[#2]: https://github.com/jt-mchorse/prompt-regression-suite/issues/2
[#3]: https://github.com/jt-mchorse/prompt-regression-suite/issues/3
[#4]: https://github.com/jt-mchorse/prompt-regression-suite/issues/4

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
layers will plug in.

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

## Diff layer (#2 · this PR)

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

## Benchmarks / Results

*Benchmarks pending issue [#4]: a real model-version regression captured
end-to-end with the snapshot, diff, and HTML report layers in place. The
diff layer lands in [#2], the report layer in [#3].*

## Demo

*60-second demo pending — depends on the HTML report layer ([#3]).*

## Why these decisions

See [`MEMORY/core_decisions_human.md`](MEMORY/core_decisions_human.md).

## License

MIT
