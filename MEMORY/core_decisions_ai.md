# Core Decisions (AI-readable, YAML, append-only)
# Schema: see .skills/portfolio-memory/SKILL.md

- id: D-001
  date: 2026-05-10
  decision: scope_per_portfolio_handoff_section_2
  rationale: locked_scope_prevents_drift
  alternatives_rejected: []
  reversibility: expensive
  related_issues: []
  superseded_by: null

- id: D-002
  date: 2026-05-14
  decision: schema_uses_dataclasses_plus_manual_validation_not_pydantic
  rationale: keep_runtime_deps_minimal_and_import_cost_low_for_downstream_portfolio_repos
  alternatives_rejected: [pydantic_v2_models, plain_dicts_with_no_validation]
  reversibility: cheap
  related_issues: [1, 2]
  superseded_by: null

- id: D-003
  date: 2026-05-14
  decision: canonical_response_embedding_stored_inline_as_list_of_floats_in_snapshot_yaml
  rationale: snapshots_stay_diff_reviewable_in_pull_requests_no_sidecar_npy_files_needed
  alternatives_rejected: [sidecar_npy_per_snapshot, base64_blob_inline]
  reversibility: cheap
  related_issues: [1, 2]
  superseded_by: null
