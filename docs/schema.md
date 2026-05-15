# Snapshot schema (v1)

A snapshot in this repo is one YAML file that captures the inputs that
produced a model response, the structural expectations that response must
continue to satisfy, and a canonical reference response with an inline
embedding for similarity-based diffing.

Schema version is `1` and is required on every snapshot. The reader
refuses to load any other version — there is no implicit migration.

## Top-level fields

| Field            | Required | Type                | Notes                                                                |
| ---------------- | -------- | ------------------- | -------------------------------------------------------------------- |
| `id`             | yes      | string              | Stable key, unique within the repo's snapshot dir. No dates/models.  |
| `prompt`         | yes      | mapping             | Inputs that produced the canonical response. See below.              |
| `response_shape` | yes      | mapping             | What a future response must continue to satisfy. See below.          |
| `canonical`      | yes      | mapping             | Reference response (text + embedding + embedding model).             |
| `schema_version` | no       | string              | Defaults to the package's current version (`"1"`).                   |
| `created_at`     | no       | ISO-8601 UTC string | Defaults to now-on-construction.                                     |
| `notes`          | no       | string              | Free-form author notes. Round-trips through YAML.                    |

## `prompt`

| Field         | Required | Type                | Notes                                                  |
| ------------- | -------- | ------------------- | ------------------------------------------------------ |
| `model`       | yes      | string              | Model ID (e.g., `claude-haiku-4-5-20251001`).          |
| `user`        | yes      | string              | The user message. Non-empty.                           |
| `system`      | no       | string              | Optional system prompt.                                |
| `temperature` | no       | number in [0, 2]    | Sampling temperature.                                  |
| `max_tokens`  | no       | positive integer    | Generation cap.                                        |
| `extra`       | no       | mapping             | Forward-compat bucket (`top_p`, `tools`, etc.).        |

The `extra` field exists deliberately so future sampling parameters can be
captured without bumping the schema version. The diff layer (#2) is
allowed to consult `extra` when explaining a drift, but it must not
*require* any particular `extra` key.

## `response_shape`

| Field                | Required | Type                            | Notes                                          |
| -------------------- | -------- | ------------------------------- | ---------------------------------------------- |
| `semantic_categories`| no       | list of unique non-empty strings| Soft expectations, scored by similarity (#2).  |
| `structured_slots`   | no       | mapping of `{name: {type: ...}}`| Hard expectations, enforced by exact diff (#2).|

Allowed `structured_slots` types are: `string`, `number`, `integer`,
`boolean`, `array`, `object`, `null`. Each slot spec is a mapping; only
`type` is required. Authors may add a free-text `description` (and other
fields) and they will round-trip.

## `canonical`

| Field             | Required | Type            | Notes                                                                  |
| ----------------- | -------- | --------------- | ---------------------------------------------------------------------- |
| `text`            | yes      | string          | The reference response in full.                                        |
| `embedding`       | yes      | list of floats  | Inline embedding of `text`. Non-empty.                                 |
| `embedding_model` | yes      | string          | Identifier of the model that produced `embedding`.                     |

The embedding is stored inline rather than as a sidecar file (see
`MEMORY/core_decisions_human.md` D-003). The diff layer is expected to
refuse to compare embeddings produced by different `embedding_model`
values — that's the snapshot's escape hatch when the embedding pipeline
changes underneath it.

## Loader / saver

```python
from prompt_regression import Snapshot, load_snapshot, save_snapshot

s: Snapshot = load_snapshot("examples/snapshots/refund_window_v1.yml")
save_snapshot(s, "out/refund_window_v1.yml")
```

Round-trip identity is the contract: `load_snapshot(save_snapshot(s)) == s`.

Validation errors all raise `prompt_regression.SnapshotValidationError`,
so callers can catch one type instead of distinguishing
`TypeError`/`ValueError`.
