# Core Decisions

Strategic decisions for this repo, with reasoning. Append-only — superseded decisions are marked, not removed.

## D-001 — Scope locked to portfolio handoff §2 (2026-05-10)
**Decision:** Scope of this repo is fixed by the portfolio handoff document, section 2.

**Why:** The handoff spec was deliberated; ad-hoc scope expansion within a session is the failure mode this prevents.

**Alternatives considered:** None — this is a baseline.

**Reversibility:** Expensive. Scope changes require a deliberate revisit and a new decision entry.

**Related issues:** —

## D-002 — Schema uses dataclasses + manual validation, not pydantic (2026-05-14)
**Decision:** The snapshot schema is implemented as plain dataclasses with hand-written validation in `__post_init__`. PyYAML is the only runtime dep beyond stdlib.

**Why:** This package is meant to be imported from other portfolio repos (notably `llm-eval-harness` consumers and `rag-production-kit`'s eval suite). Pulling pydantic into every downstream environment buys very little — the schema is small, the validation rules are clear, and the dataclass approach matches the precedent set by `llm-eval-harness` D-002. Keeping the dep surface minimal also makes the package fast to import inside CI.

**Alternatives considered:**
- pydantic v2 models — rejected; too heavy a dep for a small schema.
- Plain dicts with no validation — rejected; the diff layer (#2) and the report layer (#3) both need structural guarantees, and pushing validation into every reader is worse than centralizing it.

**Reversibility:** Cheap. Migrating to pydantic later is a mechanical refactor and the YAML on disk doesn't change.

**Related issues:** #1, #2.

## D-003 — Canonical-response embedding stored inline in snapshot YAML (2026-05-14)
**Decision:** The canonical response's embedding is stored inline as a list of floats inside the snapshot YAML file, not in a sidecar `.npy` file.

**Why:** Snapshots are checked into git alongside the prompts they cover, and the whole value proposition is that changes show up in pull request diffs. A sidecar `.npy` is opaque in PR review and adds a second file the reader has to chase. The inline-floats representation is verbose at high embedding dimensions but stays diff-reviewable; for typical small embedding models (384–768 dims) the file size stays well under any reasonable limit.

**Alternatives considered:**
- Sidecar `.npy` file per snapshot — rejected; opaque in PR diffs, second file to manage.
- Base64-encoded float32 blob inline — rejected; compact but opaque, defeats the diff-reviewability goal.

**Reversibility:** Cheap. The loader can grow a fallback path for sidecar `.npy` or base64 blobs later without breaking existing inline-floats snapshots.

**Related issues:** #1, #2.

## D-004 — Diff layer is two channels (cosine + slot) AND-ed into one verdict (2026-05-15)
**Decision:** `diff_response()` returns a `DiffResult` with a cosine similarity score, a list of per-slot deltas, optional semantic-category scores, and a single `verdict ∈ {pass, warn, fail}` that's the AND of both channels. A high cosine score with a missing structured slot is a `fail`, not a `pass`. A `warn` is reserved for cosine in the configurable warn-band just below threshold with all slots passing.

**Why:** Cosine similarity catches *topical* drift — the response changed subject. Structured-slot extraction catches *structural* drift — the response still talks about the right thing but stopped naming the plan, or stopped quoting a number. They're orthogonal failure modes; collapsing them into one weighted score hides which one regressed. AND-ing them at the verdict layer keeps each channel's signal visible while still producing the single pass/fail bit CI needs.

**Alternatives considered:**
- Cosine only — rejected: misses structural drift.
- Slots only — rejected: misses topical drift.
- Weighted blend into one combined score — rejected: hides which channel regressed.

**Reversibility:** Cheap.

**Related issues:** #2, #3

## D-005 — `Embedder` is a single-method Protocol (2026-05-15)
**Decision:** `prompt_regression.diff.Embedder` is a Protocol with `model_name: str` and `embed(text) -> list[float]`. Tests use the dep-free `HashEmbedder` reference; production callers BYO via the Protocol.

**Why:** The portfolio is using single-method Protocol as the standard test-substitution seam (`rag-production-kit` Embedder + Reranker, `llm-eval-harness` Backend, `llm-cost-optimizer` Embedder + Storage). Consistent shape across repos.

**Alternatives considered:**
- Hard-coded OpenAI embedder — rejected: vendor lock-in, SDK install on tests.
- Abstract base class — rejected: ceremony for a one-method seam.
- sklearn-style `BaseEstimator` — rejected: no `fit`.

**Reversibility:** Cheap.

**Related issues:** #2, #4

## D-006 — Diff refuses on embedder/snapshot model mismatch (2026-05-15)
**Decision:** `diff_response()` raises `EmbedderModelMismatchError` if the embedder's `model_name` doesn't match the snapshot's recorded `canonical.embedding_model`. `force=True` overrides.

**Why:** A silently re-embedded comparison produces false PASSes that look like the suite is working — every snapshot passes, but the cosine numbers don't mean what the operator thinks. Default refusal forces deliberate re-snapshot with the new model.

**Alternatives considered:**
- Warn only — rejected: warnings get ignored.
- Silent re-embed on mismatch — rejected: this is the failure mode.
- Require an explicit `re-snapshot` CLI before any diff — rejected: too heavy for in-process use.

**Reversibility:** Cheap. `force=True` is the operator's safety valve.

**Related issues:** #2

## D-007 — HTML report is a single self-contained file (2026-05-16)
**Decision:** `prompt_regression.render_report(entries)` returns one HTML string with inline CSS, no JavaScript, no external assets. The CI artifact-URL is the deployment story: a single uploaded HTML file viewable in any browser, deep-linkable per snapshot via `#snapshot-<id>` anchors.

**Why:** CI consumers want a URL, not a pipeline. A multi-file report (separate CSS, separate JSON, separate index) forces consumers to either zip+download or set up a static-hosting layer. A single file lands as one artifact, opens in Chrome/Firefox/Safari with no setup, and stays usable forever (no broken CDN reference five years from now). No JS keeps the report readable in static viewers and in `cat`/`less` for the determined.

**Alternatives considered:**
- React-via-CDN — rejected: overkill for a static report; the trace viewer in `agent-orchestration-platform` (#6 / D-006 there) uses it precisely because it has interactive list/detail navigation, which this static artifact doesn't.
- Separate CSS file — rejected: breaks the single-URL artifact story.
- Jinja2 templating — rejected: adds a dep for a one-off render that f-strings handle.

**Reversibility:** Cheap. The renderer is one module of pure-string assembly; restructuring is a contained refactor.

**Related issues:** #3, #4

## D-008 — Regression demo uses synthetic responses, honestly labeled (2026-05-16)
**Decision:** The "real regression caught" demo for issue #4 ships with two synthetic response strings — a baseline and an "upgraded" model's response — clearly labeled in the snapshot's `notes` field and in the README section title as a documentation demo. The path to a real captured regression is documented as "replace the two strings in `scripts/render_regression_demo.py` with recorded responses and re-run".

**Why:** A *real* cross-version capture requires (a) operator API budget and (b) two different model versions to query, neither of which a hermetic CI session can provide. The bar set by the issue ("real regression caught") is interpreted as "the diff and report layers can demonstrably catch a regression-shaped change end-to-end" — which the synthetic example proves. Fabricating one and labeling it real would be exactly the kind of dishonesty the portfolio's no-fabricated-benchmarks rule exists to prevent. Honest disclosure plus a two-line swap path is the right balance.

**Alternatives considered:**
- Block issue #4 until real-API capture is available — rejected: would indefinitely stall the demo + screenshot work without delivering value.
- Ship a fake, unlabeled "regression" — rejected: dishonest; would mislead anyone reading the README.
- Generate responses from a live LLM at demo-run time — rejected: requires `ANTHROPIC_API_KEY` in CI; defeats the point of a reproducible-on-fresh-clone demo.

**Reversibility:** Cheap. Two strings in one file get replaced when an operator runs a real capture; the snapshot's `notes` field and the README's framing get updated in the same PR.

**Related issues:** #4

---

## D-009 — A non-strict `mypy` gate over `prompt_regression`, in CI and as a test

**Date:** 2026-08-24

**Decision.** Adopt the non-strict `mypy` baseline gate: `python_version =
"3.11"`, `files = ["prompt_regression"]`, `warn_unused_ignores`,
`warn_redundant_casts`, no blanket `ignore_missing_imports`. It runs in the CI
lint job and again as `tests/test_mypy_clean.py`, both invoking a bare `mypy` so
they read exactly the `[tool.mypy]` block in `pyproject.toml`.

**Why.** Three sibling repos already run this gate, and the config is copied
from them — but the *rationale* is not, because theirs does not transfer.
`llm-eval-harness` (D-016) and `llm-cost-optimizer` (D-014) justify their gate
by shipping a `py.typed` marker: their annotations are visible to downstream
type-checkers, so drift breaks a consumer. `prompt_regression` ships no marker.

What applies here is **latent green** rot, and #146 is the evidence rather than
the hypothesis: six errors sat on a green `main` until someone ran `mypy` by
hand while working an unrelated issue. Hand-running a checker is not a discovery
mechanism.

Wiring it into both the CI step and a test is the substance, not belt-and-braces.
A CI step alone means the failure arrives after pushing. A test alone is bypassed
by a future change to the pytest scope. And invoking a *bare* `mypy` in both —
rather than passing a file list — is what keeps the test, the CI step and a
developer's terminal checking the same thing.

**What the six errors actually were, since the split matters.** Four were
`Library stubs not installed for "yaml"`. That is a *dependency* gap, not a code
defect: the import is real and resolvable, only its types were missing. So the
fix is `types-PyYAML` in the `dev` extra, and neither a blanket
`ignore_missing_imports` nor a per-module override is warranted — either would
have silenced a genuine typo just as effectively as a stubless import, to hide a
problem that has a proper solution.

The other two were annotation slips in `diff.py`: a `value` name rebound across
a three-branch chain (so inference took the first branch's type and the other
two read as errors), and `SLOT_TYPE_PYTHON`, whose values mix a bare `type` with
a `tuple[type, type]` and therefore widened to `dict[str, object]`, making
`isinstance(actual, expected_python)` uncheckable. Neither masked a defect —
checked rather than assumed, by confirming that no branch reads another's
binding and that the dict's contents are correct.

**But one was found next door.** While checking whether the annotation errors
masked anything, `_coerce_match`'s finiteness guard turned out to read
`if not want_int and not math.isfinite(value)` — so the integer branch has no
magnitude bound and a 400-digit integer is returned with `status: "ok"` where
the float branch returns `None`. Filed as #147 rather than fixed here.

**Scope limitation, stated rather than papered over.** The gate covers the
package only, matching all three siblings. `mypy prompt_regression scripts tests`
reports 17 further errors across 12 files. Worth noting the difference from
`chunking-strategies-lab`, where the same widening is *blocked* by a module-name
collision that stops `mypy` before it checks anything: here `mypy` starts fine,
so widening is real work rather than blocked work.

**Alternatives considered.**
- *Full strict mode now* — rejected; baseline first, as all three siblings did.
- *Blanket `ignore_missing_imports`* — rejected; silences typos too.
- *A per-module `yaml` override instead of the stub package* — rejected; hides a
  problem that has a proper fix.
- *Just fix the six errors* — rejected; closes the instance, leaves the class.
- *CI step only, or test only* — rejected for the reasons above.

**Reversibility:** Cheap. A config block, two dev dependencies, a CI line, and a
test file.

**Related issues:** #146, #147
