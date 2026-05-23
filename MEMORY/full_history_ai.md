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

---
session: 2026-05-18T20:25Z
duration_min: 20
issue: 12
focus: snapshot_test_locks_docs_regression_demo_html_to_render_script_output
delta:
  files_added: 1   # tests/test_regression_demo_snapshot.py
  files_changed: 0
  tests_added: 2   # byte-equal snapshot + synthetic-disclosure framing check
  test_pass_rate: "118/118"
context_for_next_session:
  - snapshot_pattern_runs_render_regression_demo_main_against_tmp_path_no_screenshot_compares_committed_docs_regression_demo_html_byte_equal
  - failure_message_names_python_scripts_render_regression_demo_py_no_screenshot_regen_command
  - tamper_verified_by_replacing_title_string_in_render_script_test_fired_then_reverted
  - synthetic_disclosure_test_guards_across_model_versions_framing_so_future_renderer_refactor_dropping_disclosure_is_loud
  - pattern_parallel_to_llm_cost_optimizer_savings_snapshot_test_committed_today_no_new_d_entry_enforces_no_fabricated_demo_handoff_section_10
decisions_made: []
followups: []
---

---
session: 2026-05-19T06:35Z
duration_min: 25
issue: 14
focus: drop_issue_n_ships_framing_plus_extend_snapshot
delta:
  files_changed: 1   # README.md
  files_changed_tests: 1   # tests/test_regression_demo_snapshot.py
  tests_added: 3
  test_pass_rate: "121/121"
context_for_next_session:
  - readme_what_this_is_paragraph_2_rewritten_to_six_bullet_past_tense
  - demo_section_replaces_bare_pending_with_two_command_path_plus_followup_15
  - snapshot_test_extended_with_3_new_drift_lock_invariants
  - tamper_verified_reinjecting_issue_n_ships_fires_snapshot
decisions_made: []
followups: ["#15"]
---

---
session: 2026-05-19T20:10Z
duration_min: 28
issue: 17
focus: snapshot_lock_readme_numeric_identifier_defaults_to_source_constants
delta:
  files_added: 1   # tests/test_readme_defaults_snapshot.py
  tests_added: 4
  test_pass_rate: "125/125"
context_for_next_session:
  - readme_defaults_now_locked_four_surfaces_default_threshold_pip_extras_prompt_snap_console_script_subcommand_surface
  - threshold_test_asserts_two_readme_mentions_agree_with_each_other_before_comparing_to_source
  - subcommand_test_discovers_live_via_argparse_actions_choices_not_help_output
  - tamper_verified_three_of_four_default_threshold_console_script_rename_subcommand_drop
  - sister_to_test_regression_demo_snapshot_orthogonal_axis_source_constants_vs_rendered_html
decisions_made: []
followups: []
---

---
session: 2026-05-19T21:25Z
duration_min: 20
issue: 19
focus: public_surface_snapshot_locks_prompt_regression_top_level_init_exports
delta:
  files_added: 1   # tests/test_public_surface.py
  tests_added: 10
  test_pass_rate: "135/135"
context_for_next_session:
  - third_public_surface_snapshot_landed_same_session_as_eval_harness_25_and_cost_optimizer_23
  - this_package_uses_relative_imports_from_dot_x_import_so_ast_walk_filters_on_importfrom_level_ge_1_instead_of_module_name_prefix
  - readme_snippet_test_parametrized_via_regex_extraction_three_snippets_today_future_snippets_auto_covered
  - guard_test_asserts_regex_non_empty
  - parametrized_over_four_submodules_diff_html_report_io_schema_one_anchor_each
  - tamper_verified_three_of_four_drop_snapshot_all_alias_rename_snapshot_nuke_readme_imports
  - sister_pattern_now_in_three_python_repos_eval_harness_cost_optimizer_prompt_regression_same_session
decisions_made: []
followups: []
---

---
session: 2026-05-22T03:45Z
duration_min: 25
issue: 22
focus: broaden_snapshot_glob_to_match_committed_yml_examples_plus_yaml_plus_snapshot_yaml_convention
delta:
  files_changed: 2   # prompt_regression/cli.py, README.md
  files_modified_tests: 1  # tests/test_cli.py (3 new tests + assertion tightening on empty-dir error)
  tests_added: 3
  test_pass_rate: "138/138"
decisions_made: []
context_for_next_session:
  - cli_snapshot_glob_hard_coded_to_star_snapshot_yaml_but_committed_examples_use_bare_yml_so_prompt_snap_run_snapshots_examples_snapshots_errored_with_no_star_snapshot_yaml_files_under_path_not_silent_but_unusable
  - broadened_to_tuple_snapshot_yaml_snapshot_yml_yml_yaml_walker_rglobs_each_dedupes_via_seen_set_sorts
  - opinionated_snapshot_yaml_still_preferred_for_fresh_projects_but_bare_yml_yaml_now_just_work_for_pre_existing_conventions_and_for_the_committed_examples_dir
  - error_message_now_lists_all_four_globs_considered_so_misconfigured_caller_can_verify_extension_coverage_without_reading_source
  - dedup_invariant_tested_separately_because_foo_snapshot_yaml_matches_both_star_snapshot_yaml_and_star_yaml_walker_must_collapse
  - sixth_post_v0_1_drift_fix_today_after_emb_shootout_chunking_lab_vector_search_at_scale_python_async_llm_pipelines_agent_orchestration_platform
followups: []
---

---
session: 2026-05-22T19:55Z
duration_min: 25
issue: 24
focus: docs_architecture_md_reflects_all_six_shipped_surfaces_not_one_only_pre_shipping_state
delta:
  files_changed: 1   # docs/architecture.md
  files_added: 1     # tests/test_architecture_doc.py
  tests_added: 7
  tamper_verify_axes: 3
context_for_next_session:
  - architecture_md_was_frozen_at_snapshot_schema_pr_issue_1_four_mermaid_nodes_pending_classdef_pending_defined_section_header_shipped_this_pr_issue_1_pending_section_listed_2_3_4_as_future_work_all_closed_months_ago
  - rewrote_to_steady_state_diagram_every_node_shipped_unused_classdef_pending_dropped_each_node_carries_origin_issue_annotation_added_per_layer_sections_for_1_2_10_3_5_plus_cross_cutting_surfaces_for_hygiene_patterns
  - new_tests_test_architecture_doc_py_three_invariants_known_shipped_issues_1_2_3_4_5_10_excluded_12_14_15_17_19_22_each_locked_separately_banned_phrases_this_pr_unfiled_to_be_filed
  - tamper_verified_three_axes_each_fires_with_specific_drift_quoted
  - fifteenth_post_v0_1_drift_or_doc_fix_in_portfolio_pattern_sixth_architecture_doc_lock_test_in_this_session_fourth_python_variant
  - portfolio_now_nine_repos_with_architecture_doc_lock_tests_remaining_with_arch_md_but_no_lock_rag_kit_agent_orch_chunking_lab_async_pipelines_cost_optimizer_all_already_in_clean_steady_state_no_drift_to_fix
  - issue_filed_mid_session_as_priority_med_then_closed_in_same_session_per_session_prompt_loop_protocol
decisions_made: []
followups: []
---

---
session: 2026-05-23T15:45Z
duration_min: 18
issue: 26
focus: arch_doc_active_decision_range_axis_d_002_through_d_008_full_backfill
decisions_made: []
delta:
  files_changed: 2
  files_added: 0
  tests_added: 3
  test_pass_rate: "148/148"
context_for_next_session:
  - eighth_repo_in_portfolio_to_ship_active_decision_range_axis
  - arch_doc_had_zero_d_nnn_citations_pre_pr_complete_backfill_d_002_dataclasses_d_003_inline_embedding_d_004_two_channel_diff_d_005_embedder_protocol_d_006_model_name_refusal_d_007_single_file_no_js_html_d_008_synthetic_but_labeled_demo
  - one_remaining_repo_for_this_axis_agent_orchestration_platform
followups: []
---
