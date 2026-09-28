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

## D-010 — an unmatched candidate key is an input error, not a silent skip (2026-08-25)

**Decision.** `prompt-snap run` reports every candidate row whose key matched no
snapshot, by name, and exits 2. `--allow-unmatched-candidates` downgrades the
failure to a report for the one legitimate case: a single candidates file shared
across several snapshot directories.

**Why.** The exit code was derived from `failed` alone, so an orphan candidate
row was dropped with no note, no count and no diagnostic. Measured on the shipped
`examples/`, changing only the two keys:

| candidates file | summary | exit |
|---|---|---|
| correct (control) | `total=2 failed=1 skipped=0` | 1 |
| zero rows | `error: no candidate rows loaded` | 2 |
| 2 rows, neither key matches | `total=2 failed=0 skipped=2` | **0** |
| 2 rows, one key matches | `total=2 failed=0 skipped=1` | **0** |

The operator's likeliest mistakes — keying by absolute path, by a since-renamed
`snapshot.id`, or with a typo — all land in the bottom two rows: a clean-looking
report and a green CI step that verified nothing.

This is not a new standard. `_load_candidates` already refuses a candidates file
with zero rows, because a run with nothing to check is meaningless. An all-orphan
file reaches the identical state by a quieter road. And the snapshot-to-candidate
lookup forty lines below already names the harm, for the neighbouring case where
the candidate *value* is empty rather than its key unmatched: "silently skips it,
letting the worst regression pass CI green."

**Alternatives considered.** *Report without failing* — a report nobody reads does
not stop a green CI step that checked nothing. *Exit 1* — that code means
"regressions found"; this is a usage error, which is 2 everywhere else in this
CLI. *No escape hatch* — a shared candidates file across snapshot directories is
a real workflow.

*A separate `skipped == total` rule* was considered and rejected as both
redundant and harmful. A partial candidates file has `skipped > 0` and zero
orphans, which is legitimate and must stay green; and the only other route to
`skipped == total` is a zero-row file, already handled at exit 2. So the second
rule could only fire where the orphan rule already does, while risking a false
positive on the partial run.

**Reversibility.** Cheap. Worth recording because it changes an exit code: a run
that previously passed CI can now fail. That is the intended outcome — those runs
were passing without checking anything.

---

## D-011 — the uniqueness rule covers the whole candidate key space
**Date:** 2026-09-21 · **Extends:** D-010 · **Reversibility:** cheap

**Decision.** The directory-level uniqueness rule is stated over the key space
`run` actually reads — each snapshot's relative path *and* its `Snapshot.id` —
rather than over the id namespace alone.

**Why.** `run`'s candidate lookup tries `rel` first, then `snap.id`. #167 made
the *id* namespace collision-free. Nothing kept the two namespaces disjoint, and
`Snapshot.id` is validated only as a non-empty string, so an id may be spelled
exactly like another file's relative path. One candidate row is then consumed by
two different snapshots — and `FirstSeenIds` cannot see it, because the two
*ids* are distinct.

Measured end to end, `a.yml` with id `refund-v1`, `b.yml` with id `"a.yml"`, one
candidate keyed `"a.yml"`:

| case | exit | `b.yml` |
|---|---:|---|
| control — distinct ids | 0 | `skipped`, "no candidate supplied" |
| collision, `b` differs | 1 | `fail`, cosine 0.000 |
| **collision, `b` is a copy** | **0** | **`pass`, cosine 1.0** |

The third row is the silently-clean report #150/D-010 established `run` must not
produce, reached through a different collision. D-010's own mechanism is
defeated the same way #167 describes: `consumed.add(rel)` marks the key used, so
`unmatched_candidates` comes back empty. And `validate` called the directory
`ok: True`.

**The judgment call: which file is the shadow.** For an id/id collision, walk
order decides — both claims are ids and order is the only tie-break available.
For an id shadowing a *path*, it must not. A relative path is a file's identity:
unique by construction and not changeable without moving the file. An id is
operator-chosen metadata. So the id-carrier is always the offender, whether it
sorts before or after the file whose path it shadows. Both directions occur and
are symmetric — measured — and the order-dependent neighbour (first-seen over
the union) goes red on exactly the "id shadows a later path" case.

**A file claiming a key twice is not a collision.** A snapshot whose own id
equals its own relative path claims one key, and the lookup consumes it once.
Hence the `snapshot_id != where` clause; dropping it turns two arms red.

**One finding code, not two.** `duplicate_id` is broadened rather than joined by
a new code. `FINDING_CODES` is a stable, JSON-routable tuple locked against both
the module docstring and the README, and this repo's own precedent (#133) is
that a new code exists when an operator routing on it "needs to fix a
[different] kind of problem". Here the operator's action is identical in both
cases — rename a `Snapshot.id`. So the code *list* is unchanged; only its
documented meaning widens, and the reason string says which collision occurred.

**Alternatives considered:**
- A new `key_collision` code — rejected; same operator action, and it changes
  what `duplicate_id` means for anyone already filtering on it.
- Constrain `Snapshot.id` to a path-free character set — rejected *here*. It
  closes the overlap at the source, but it is a schema change that could reject
  snapshots already on disk, and the README documents keying by path *or* id as
  a deliberate convenience, so the namespaces overlap by design. Refusing the
  collision is smaller than refusing the shape; refusing the shape has migration
  cost and deserves its own evidence.
- First-seen over the union — rejected, and measured wrong: it makes the shadow
  depend on walk order and flags the wrong file in one of the two directions.
- Claim only paths and drop #167's id rule — rejected; six arms red, including
  #167's own tests.

**Related issues:** #171, #167, #150

## D-012 — A stated ordering stays visible when its two numbers are rendered
**Date:** 2026-09-24 · **Reversibility:** cheap · **Issues:** #175 (with #10, #35)

`diff_response` decides `cosine_pass = cosine_score >= effective_threshold` at full float precision and then explained the decision at a fixed three decimal places. So a near-threshold failure published a note that contradicted itself: `cosine 0.850 below threshold 0.850`. A near-threshold failure is the ordinary shape of a marginal regression, and it is exactly when an operator reads the note most carefully. The guard was never wrong — only its explanation was, which is why no existing test caught it: every verdict in every one of these cases is correct.

Both sides of such a sentence now go through `render_comparison`, which starts at three places and widens only while the two render identically, and always returns both sides at the same precision.

**Why the rule is on the rendered strings and not on a width.** A wider fixed width is not the same fix: `.6f` makes the collision need a tighter margin (`0.8499999995`) without removing it — that neighbour was built and run, five arms red. A rule expressed as a hand-picked width also has no way to say what it is *for*. Deciding on the rendered strings cannot drift from what the reader sees, because it *is* what the reader sees.

**Same precision on both sides is a separate and harder requirement.** The neighbour that widens only the value passed the first sweep, because every margin in that sweep sat below a round `0.85`, so the cosine was always the side with the long expansion — half the population. In the other orientation the neighbour renders `cosine 0.8500000000 below threshold 0.850`, where the rendered score is *not* less than the rendered threshold. The note then states the reverse of the verdict, which is worse than hiding it. A reversed-orientation sweep and a structural same-precision arm took that neighbour from zero red to thirteen.

**Four surfaces, and the tolerance note is the cleanest case.** The fail note, the warn note, the per-snapshot tolerance note, and the HTML report's meta line beside the verdict badge. The tolerance note is emitted under `snapshot.tolerance != threshold`, so an inequality is established one line before the rendering; at three places it could publish `per-snapshot tolerance 0.850 overrides run threshold 0.850` — an override described as changing nothing. The guard proved the difference and the rendering hid it.

**`cli.py` is deliberately excluded, and the exclusion is itself a test.** Its `cosine: … (threshold …)` line renders the cosine at `.4f` and the threshold unformatted, so the two sides sit at different precisions and trailing zeros mean they can never render as the same string. It also asserts no ordering: it reports a score and, parenthetically, the configured threshold. The line in that output which *does* assert an ordering is the note, which is fixed. Written as `test_the_cli_line_cannot_read_as_a_contradiction`, so if anyone formats the threshold to match the cosine the exclusion fails loudly instead of rotting.

**Rejected outright:** rounding the *comparison* to match the display. That makes the gate less precise in order to make the message consistent, which is backwards. D-004's two-channel verdict is untouched.

---

## D-013 — the CLI `cosine:` line joins the rule D-012 excluded it from

**Date.** 2026-09-25 · **Issue.** #177 · **Reversibility.** cheap
**Supersedes.** D-012's CLI-exclusion paragraph only. The rest of D-012 stands.

**Decision.** `cli.py`'s `cosine: … (threshold …)` line renders through
`render_comparison`, like the other four surfaces. `render_comparison` gains a
**required** `places` parameter so each surface keeps its own width.

**Why.** D-012 excluded this line on two claims, and both are false.

*"It renders the two sides at different precisions, so trailing zeros keep them
from ever reading as the same number."* True only while the threshold's `repr`
has fewer than four decimals. `f"{x:.4f}"` against `str(x)` collides at
`0.8501`, `0.1234`, `0.9999` — and `--threshold` is `type=float` on both
`check` and `diff`. The argument silently assumed a *round configured*
threshold, which the default happens to be.

*"The sentence asserts no ordering."* True of the sentence, false of the output.
`_format_diff_text` puts `verdict:` on the line directly above, and the gate is
`>=`, so a cosine equal to the threshold **passes**. Measured:

```
verdict: fail
cosine:  0.8501 (threshold 0.8501)
```

**And the surface was already broken at the shipped default**, by a mechanism
neither D-012 nor #177's own issue named. Rewritten as a seven-threshold table
and run against the old line, the ordering arm goes red on **six of seven** —
including `round-default`. `f"{0.85 - 1e-9:.4f}"` is `'0.8500'` and `str(0.85)`
is `'0.85'`: two different strings that read as the *same value*, so the pair
states "0.85 is below 0.85" under a `fail` verdict. The old arm asserted only
that the two strings *differ*. That was the wrong unit; the right one is whether
the pair agrees with the verdict.

**The old exclusion was held by one data point behind a universal docstring.**
A single call at `0.85`, under a docstring claiming the two "can never render as
the same string". A green arm on a false universal is worse than no arm, because
it reads as a guarantee.

**The two replacement arms are exactly complementary, measured.** Against the
old line, the ordering arm is red on six of seven and green on
`arithmetic-derived`; the structural same-precision arm is red on the three
round ids plus `arithmetic-derived` and green on the three four-decimal ones.
Together they cover all seven; separately neither does. That is the argument for
keeping both, rather than a style preference.

**`places` is now required, and this issue is the evidence.** The helper
hardcoded `COMPARISON_PLACES` (3). The first caller with a different width
arrived here — the CLI line publishes four — and routing it through the
three-place helper republished the README CLI tour's pinned `cosine:  0.8058`
as `0.806`. Narrowing a documented number while fixing an unrelated defect is
the regression `llm-eval-harness#252` shipped, and it was caught here only
because `test_readme_cli_tour_examples` pins the line byte-for-byte.

**Published output did move, and the move is documented rather than silent.**
The *measured* cosine is byte-identical (`0.8058`, `0.0508`); the threshold
gains trailing zeros (`0.75` → `0.7500`), which is the same-precision rule doing
its job. Two independent locks covered that line; the second pins that the
effective threshold is visibly different from the `0.850` default, and that
property is unchanged.

**Alternatives considered.** All built and run.
- *Narrow the exclusion to round thresholds.* Rejected: claim 2 is false for
  every threshold, so there is no scope on which the stated reason holds.
- *Route it at the notes' width of 3.* Rejected: 4 red — the `leh#252`
  regression.
- *Widen only the cosine side.* Rejected: 10 red, 7 on the structural arm.
- *Keep the old arm and add cases.* Rejected: its assertion was on the wrong
  unit, so more cases would not have helped.
