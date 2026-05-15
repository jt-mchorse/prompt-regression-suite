# Session History (AI-readable, append-only)

Schema: see .skills/portfolio-memory/SKILL.md

---
session: 2026-05-14T14:08:00Z
duration_min: 55
issue: 1
focus: snapshot_yaml_schema_and_loader
delta:
  files_added: 11
  files_changed: 4
  tests_added: 29
  coverage_pct: 95
context_for_next_session:
  - schema_v1_shipped_dataclasses_not_pydantic_per_d002
  - canonical_response_embedding_is_inline_in_yaml_per_d003
  - sample_snapshot_at_examples_snapshots_refund_window_v1_yml_is_the_diff_layer_input_for_issue_2
  - schema_version_string_1_strict_check_on_read_no_implicit_migration
  - prompt_extra_field_is_forward_compat_bucket_for_top_p_tools_etc_without_schema_bump
decisions_made: [D-002, D-003]
followups: []
---

---
session: 2026-05-15T16:59Z
duration_min: 55
issue: 2
focus: semantic_similarity_diff_layer
delta:
  files_added: 2
  files_changed: 2
  tests_added: 25
  test_pass_rate: "54/54"
context_for_next_session:
  - diff_layer_shipped_two_channels_cosine_plus_slots_anded_d004
  - embedder_protocol_with_hashembedder_reference_d005
  - embedder_model_mismatch_refused_by_default_d006_force_kwarg_overrides
  - identical_one_paraphrase_pass_off_topic_fail_acceptance_criteria_met
  - default_threshold_0_85_per_issue_2_acceptance_criterion
  - html_report_layer_3_consumes_diffresult_shape_locked_here
  - real_regression_screenshot_4_uses_diff_layer_end_to_end
decisions_made: [D-004, D-005, D-006]
followups: []
---
