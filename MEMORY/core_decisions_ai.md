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

- id: D-004
  date: 2026-05-15
  decision: diff_layer_two_channels_cosine_plus_slot_extraction_anded_for_final_verdict
  rationale: cosine_alone_misses_structural_drift_slots_alone_miss_topical_drift_both_required_for_a_real_pass
  alternatives_rejected: [cosine_only, slots_only, weighted_blend_with_one_combined_score]
  reversibility: cheap
  related_issues: [2, 3]
  superseded_by: null

- id: D-005
  date: 2026-05-15
  decision: embedder_is_single_method_protocol_parallel_to_portfolio_pattern
  rationale: same_seam_as_rag_kit_eval_harness_cost_optimizer_test_substitution_consistent_across_repos
  alternatives_rejected: [hard_coded_openai_embedder, abstract_base_class, sklearn_style_estimator]
  reversibility: cheap
  related_issues: [2, 4]
  superseded_by: null

- id: D-006
  date: 2026-05-15
  decision: diff_refuses_when_embedder_model_name_doesnt_match_snapshot_embedding_model
  rationale: silently_re_embedded_comparison_produces_false_pass_that_looks_like_the_suite_is_working
  alternatives_rejected: [warn_only, silent_re_embed_on_mismatch, require_explicit_re_snapshot_command]
  reversibility: cheap
  related_issues: [2]
  superseded_by: null
