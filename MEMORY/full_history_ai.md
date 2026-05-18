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

---
session: 2026-05-16T04:20Z
duration_min: 35
issue: 4
focus: html_report_layer_3_plus_regression_demo_4_combined
delta:
  files_added: 4
  files_changed: 3
  tests_added: 16
  test_pass_rate: "70/70"
context_for_next_session:
  - html_report_module_in_prompt_regression_html_report_ty_renders_diffresult_to_single_self_contained_html
  - inline_css_no_js_no_external_assets_d_007_ci_artifact_url_is_deployment_story
  - reportentry_dataclass_carries_snapshot_id_diff_candidate_text_baseline_text
  - failing_sections_render_categories_slots_responses_passing_sections_collapse_to_one_line
  - anchor_links_snapshot_id_safe_slugified_so_ci_url_deep_links_to_failure
  - scripts_render_regression_demo_py_builds_baseline_snapshot_in_process_with_hashembedder_runs_diff_writes_html
  - demo_regression_is_synthetic_d_008_honestly_labeled_in_snapshot_notes_and_readme_real_capture_is_two_string_swap
  - screenshot_via_playwright_or_wkhtmltoimage_optional_fallback_writes_just_html
  - 13_html_report_tests_3_demo_script_tests_16_total_new_70_70_overall
  - issue_3_html_report_and_issue_4_real_regression_caught_both_close_in_this_pr
decisions_made: [D-007, D-008]
followups: []
---

---
session: 2026-05-16T20:10Z
duration_min: 40
issue: 5
focus: prompt_snap_cli_run_update_diff_subcommands
delta:
  files_added: 2  # prompt_regression/cli.py, tests/test_cli.py
  files_changed: 2  # pyproject.toml, README.md
  tests_added: 25
  test_pass_rate: "95/95"
context_for_next_session:
  - prompt_snap_console_script_registered_via_project_scripts_in_pyproject
  - three_subcommands_run_update_diff_argparse_main_in_cli_py
  - run_walks_snapshot_glob_recursively_loads_candidates_jsonl_keyed_by_path_or_id_emits_text_or_json_exits_1_on_failure
  - update_requires_force_flag_re_embeds_canonical_via_configured_embedder_writes_via_save_snapshot
  - diff_supports_candidate_arg_or_candidate_stdin_format_text_or_json_exits_1_on_fail
  - make_embedder_hash_default_voyage_openai_cohere_reserved_names_raise_not_implemented_loud_misconfig
  - skipped_snapshots_no_candidate_supplied_do_not_fail_run_exit_zero_only_real_failures_do
  - force_embedder_flag_overrides_d_006_embedder_model_mismatch_guard
  - no_new_decisions_pure_glue_over_existing_types
  - issue_5_acceptance_cli_installed_as_console_script_done_update_requires_force_done_help_complete_done
decisions_made: []
followups: []
---

---
session: 2026-05-18T16:07Z
duration_min: 30
issue: 10
focus: per_snapshot_tolerance_override_field
delta:
  files_added: 2  # tests/test_tolerance.py, examples/snapshots/creative_kite_v1.yml
  files_changed: 3  # prompt_regression/schema.py, prompt_regression/diff.py, README.md
  tests_added: 21
  test_pass_rate: "116/116"
context_for_next_session:
  - snapshot_tolerance_optional_float_in_zero_open_to_one_closed_validated_in_post_init_bool_str_list_rejected
  - to_dict_omits_tolerance_when_none_mirrors_notes_pattern_existing_yaml_round_trips_byte_stable
  - diff_response_effective_threshold_is_snapshot_tolerance_or_threshold_kwarg_diffresult_threshold_carries_effective
  - override_note_appended_to_diffresult_notes_when_snapshot_tolerance_differs_from_run_threshold
  - creative_kite_v1_yml_worked_example_tolerance_0_75_with_explanatory_notes
  - readme_diff_layer_section_has_per_snapshot_tolerance_subsection_with_yaml_snippet
  - no_new_d_entry_resolution_concern_over_existing_d_004_two_channel_diff_does_not_change_channel_composition
  - load_snapshot_save_snapshot_round_trip_invariant_preserved_for_both_tolerance_set_and_tolerance_absent
decisions_made: []
followups: []
---
