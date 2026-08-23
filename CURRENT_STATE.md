# CURRENT_STATE.md

> **GENERATED — do not edit.** `python3 scripts/current_state.py`
> regenerates this; CI fails if the committed copy has drifted
> (`tests/workflow_current_state.py`). Everything here is read out of the
> code, so it cannot quietly become untrue. If a fact belongs here, teach
> the generator to read it -- do not type it in.

**Version:** 2.0.11

## Tools the model can see

Every row is generated from the strict `kaliv-capability/v2` descriptor,
not from a parallel documentation projection. `access` gates what a tool
may do; `impact` describes the consequence; `data class` governs where
results may travel; scheduling, network, termination and replay semantics
are the same versioned values validated by worker, backend and clients.

| Capability | schema | access | impact | data class | isolated | sched | network | stop | replay |
|---|---|---|---|---|---|---|---|---|---|
| `tool:cancel_job` | `kaliv-capability/v2` | write | write | operational | no | no | none | none | yes |
| `tool:current_datetime` | `kaliv-capability/v2` | read | read | public | no | yes | none | none | yes |
| `tool:delete_model` | `kaliv-capability/v2` | write | destructive | operational | no | no | configured_service | none | no |
| `tool:job_status` | `kaliv-capability/v2` | read | read | operational | no | yes | none | none | yes |
| `tool:list_documents` | `kaliv-capability/v2` | read | read | private | no | yes | none | none | yes |
| `tool:list_models` | `kaliv-capability/v2` | read | read | operational | no | yes | configured_service | none | yes |
| `tool:note_append` | `kaliv-capability/v2` | write | write | private | no | yes | none | none | no |
| `tool:pull_model` | `kaliv-capability/v2` | write | admin | operational | no | no | configured_service | cooperative | no |
| `tool:rig_status` | `kaliv-capability/v2` | read | read | operational | no | yes | none | none | yes |

## Switches (default = what a rig does today)

| Env | Default |
|---|---|
| `KALIV_AGENT3_APPROVAL_REQUIRED` | `(unset)` |
| `KALIV_AGENT3_ENABLED` | `0` |
| `KALIV_AGENT3_PILOT_MAX_AGE_HOURS` | `(unset)` |
| `KALIV_AGENT3_PILOT_REPORT` | `(unset)` |
| `KALIV_AGENT3_TASK_UI` | `(unset)` |
| `KALIV_AGENT3_TASK_WORKERS` | `2` |
| `KALIV_AGENT3_VALIDATION_MAX_AGE_HOURS` | `(unset)` |
| `KALIV_AGENT3_VALIDATION_REPORT` | `(unset)` |
| `KALIV_AGENT4_OPERATOR_API` | `0` |
| `KALIV_ALLOW_RAG_CLOUD` | `` |
| `KALIV_CLOUD_ALLOW_PRIVATE` | `0` |
| `KALIV_COMPUTER_USE` | `0` |
| `KALIV_DATA_DIR` | `(unset)` |
| `KALIV_EGRESS_GATE` | `` |
| `KALIV_GITHUB_CONNECTOR_PILOT` | `0` |
| `KALIV_HOME_RIG_PILOT` | `0` |
| `KALIV_MAX_UPLOAD_MB` | `25` |
| `KALIV_PULL_READ_TIMEOUT_S` | `600` |
| `KALIV_READ_CONNECTOR_PILOT` | `0` |
| `KALIV_SCHEDULER` | `` |
| `KALIV_SCHEDULER_API` | `0` |
| `KALIV_SCHEDULER_POLL_S` | `` |
| `KALIV_TOOLS_DIR` | `(unset)` |
| `KALIV_TOOLS_ENABLED` | `0` |
| `KALIV_TOOL_ISOLATION` | `` |
| `KALIV_VISION_MODEL` | `(unset)` |
| `KALIV_WEB_RESEARCH_ENABLED` | `` |
| `KALIV_WORKER_ALLOW_LAN` | `0` |

## Desktop credential storage

| Property | Current implementation |
|---|---|
| Beskyttede settings | `cloudKey`, `deviceToken` |
| At-rest-beskyttelse | Windows DPAPI (current-user) |
| Legacy-klartekst migreres før udlevering | ja |
| Korrupt/ukendt envelope fejler lukket | ja |
| DPAPI-test defineret og koblet i CI (windows-latest) | ja |
| Bestået på denne commit | kan ikke verificeres offline — se CI-status for headen |

## Design docs and what they claim about themselves

| Doc | Status |
|---|---|
| `CLIENT_STATE_DESIGN.md` | DELVIST · trin 1-2 leveret (1.58.44/45) · trin 3-5 kræver device-test · **Ejer:** Anders |
| `ISOLATION_DESIGN.md` | LIVE · I0a+I0c leveret (dormant) · I0b afventer rig · **Ejer:** Anders (gates) — se CURRENT_STATE.md for switches |
| `RAG_DESIGN.md` | LIVE · replace-by-source leveret (1.58.40) · atomisk ingest + corpus-kontrakt leveret (1.58.148) · T-043 benchmark-harness leveret · måling/kalibrering kræver rig · **Ejer:** Anders |
| `UPDATER_DESIGN.md` | LIVE · implementation complete + CI-verificeret · fysisk signed-release→signed-release acceptance afventer #401 · **Ejer:** Anders (rig) |
| `VALIDATION-1.58.49.md` | AFVENTER KØRSEL · resultatfelter tomme · gælder 1.58.49+ · **Ejer:** Anders (rig + telefon) |

## Test suites in CI

Run by glob, so a file that matches is a file that runs
(`tests/workflow_test_coverage.py` proves none can hide).

- `tests/backend_smoke.py`
- `tests/backend_v1.py`
- `tests/e2e.py`
- `tests/worker_agent3_approval.py`
- `tests/worker_agent3_approval_api.py`
- `tests/worker_agent3_approval_concurrency.py`
- `tests/worker_agent3_atomic_journal.py`
- `tests/worker_agent3_campaign_adapter.py`
- `tests/worker_agent3_campaign_adapter_races.py`
- `tests/worker_agent3_cancellation_contract.py`
- `tests/worker_agent3_capability_graph.py`
- `tests/worker_agent3_capability_graph_api.py`
- `tests/worker_agent3_capability_probe.py`
- `tests/worker_agent3_capability_receipt.py`
- `tests/worker_agent3_capability_receipt_api.py`
- `tests/worker_agent3_cloud_read_policy.py`
- `tests/worker_agent3_entrypoint.py`
- `tests/worker_agent3_entrypoint_wiring.py`
- `tests/worker_agent3_integration.py`
- `tests/worker_agent3_late_cancel.py`
- `tests/worker_agent3_memory.py`
- `tests/worker_agent3_memory_api.py`
- `tests/worker_agent3_memory_context.py`
- `tests/worker_agent3_memory_protected_api.py`
- `tests/worker_agent3_memory_protected_api_query_order.py`
- `tests/worker_agent3_memory_protected_api_strict_models.py`
- `tests/worker_agent3_memory_protected_backup.py`
- `tests/worker_agent3_memory_protected_body_stream.py`
- `tests/worker_agent3_memory_protected_context.py`
- `tests/worker_agent3_memory_protected_context_dpapi.py`
- `tests/worker_agent3_memory_protected_context_mount_gate.py`
- `tests/worker_agent3_memory_protected_gateway.py`
- `tests/worker_agent3_memory_protected_leak_surfaces.py`
- `tests/worker_agent3_memory_protected_leak_surfaces_dpapi.py`
- `tests/worker_agent3_memory_protected_mount_gate.py`
- `tests/worker_agent3_memory_protected_planner.py`
- `tests/worker_agent3_memory_protected_planner_dpapi.py`
- `tests/worker_agent3_memory_protected_reader.py`
- `tests/worker_agent3_memory_protected_status_refresh.py`
- `tests/worker_agent3_memory_protected_writer.py`
- `tests/worker_agent3_memory_protection.py`
- `tests/worker_agent3_memory_protection_migration.py`
- `tests/worker_agent3_memory_store_path_separation.py`
- `tests/worker_agent3_memory_store_selection.py`
- `tests/worker_agent3_model_eval.py`
- `tests/worker_agent3_mount_contract.py`
- `tests/worker_agent3_outcome_answer.py`
- `tests/worker_agent3_outcome_answer_api.py`
- `tests/worker_agent3_outcome_context.py`
- `tests/worker_agent3_outcome_context_adversarial.py`
- `tests/worker_agent3_plan_authority_api.py`
- `tests/worker_agent3_plan_single_use.py`
- `tests/worker_agent3_plan_store.py`
- `tests/worker_agent3_planner.py`
- `tests/worker_agent3_planner_capability_binding.py`
- `tests/worker_agent3_planner_memory.py`
- `tests/worker_agent3_planner_review.py`
- `tests/worker_agent3_planner_review_guard.py`
- `tests/worker_agent3_readonly_pilot.py`
- `tests/worker_agent3_replan_api.py`
- `tests/worker_agent3_replan_planner.py`
- `tests/worker_agent3_replan_preview.py`
- `tests/worker_agent3_replan_preview_api.py`
- `tests/worker_agent3_replan_runtime.py`
- `tests/worker_agent3_replanner.py`
- `tests/worker_agent3_retry.py`
- `tests/worker_agent3_review_api_apply.py`
- `tests/worker_agent3_review_api_approve.py`
- `tests/worker_agent3_review_api_deny.py`
- `tests/worker_agent3_review_api_resume.py`
- `tests/worker_agent3_review_api_start.py`
- `tests/worker_agent3_review_binding.py`
- `tests/worker_agent3_review_reads.py`
- `tests/worker_agent3_review_replan_api.py`
- `tests/worker_agent3_rig_evidence.py`
- `tests/worker_agent3_rig_validation_cli.py`
- `tests/worker_agent3_risk_parity.py`
- `tests/worker_agent3_routing_preview.py`
- `tests/worker_agent3_smoke_cli.py`
- `tests/worker_agent3_task_readiness.py`
- `tests/worker_agent3_task_readiness_entrypoint.py`
- `tests/worker_agent3_task_surface.py`
- `tests/worker_agent3_task_ui_validation.py`
- `tests/worker_agent3_termination_ui_physical_report.py`
- `tests/worker_agent3_unattended_execution.py`
- `tests/worker_agent3_validation_gate.py`
- `tests/worker_agent3_validation_path_contract.py`
- `tests/worker_agent3_validation_status.py`
- `tests/worker_agent3_workflow_completion.py`
- `tests/worker_agent3_workflow_receipt_integrity.py`
- `tests/worker_agent4_a4_23_filter_before_summary.py`
- `tests/worker_agent4_a4_25_snapshot_authority_guard.py`
- `tests/worker_agent4_a4_25b_snapshot_store.py`
- `tests/worker_agent4_a4_25c_snapshot_publisher.py`
- `tests/worker_agent4_a4_25c_snapshot_recovery.py`
- `tests/worker_agent4_a4_25d_snapshot_operator.py`
- `tests/worker_agent4_campaign_list_api.py`
- `tests/worker_agent4_campaign_list_query.py`
- `tests/worker_agent4_checkpoints.py`
- `tests/worker_agent4_foundation.py`
- `tests/worker_agent4_handoff_barrier_placement.py`
- `tests/worker_agent4_handoff_contract.py`
- `tests/worker_agent4_handoff_e2e.py`
- `tests/worker_agent4_handoff_mutation_contract.py`
- `tests/worker_agent4_handoff_persistence.py`
- `tests/worker_agent4_handoff_persistence_regressions.py`
- `tests/worker_agent4_handoff_runtime.py`
- `tests/worker_agent4_operator_api.py`
- `tests/worker_agent4_operator_api_review.py`
- `tests/worker_agent4_production_bootstrap.py`
- `tests/worker_agent4_production_read_mutation_boundary.py`
- `tests/worker_agent4_recovery.py`
- `tests/worker_agent4_resources.py`
- `tests/worker_agent4_scheduler_service.py`
- `tests/worker_agent_continue.py`
- `tests/worker_agent_multistep.py`
- `tests/worker_approval_receipts.py`
- `tests/worker_audit.py`
- `tests/worker_backup.py`
- `tests/worker_browser_host.py`
- `tests/worker_browser_peer_adapter.py`
- `tests/worker_browser_peer_fulfillment.py`
- `tests/worker_browser_peer_runtime.py`
- `tests/worker_browser_peer_ssrf_adversarial.py`
- `tests/worker_browser_use_adapter.py`
- `tests/worker_browser_use_network_guard.py`
- `tests/worker_browser_use_runtime_guard.py`
- `tests/worker_build_identity.py`
- `tests/worker_capability_schema_v2.py`
- `tests/worker_confirm_outbound_reads.py`
- `tests/worker_confirmation_impact.py`
- `tests/worker_control_center_api.py`
- `tests/worker_control_center_status.py`
- `tests/worker_d4_auto_routing.py`
- `tests/worker_data_sharing_policy.py`
- `tests/worker_desktop_action_plan.py`
- `tests/worker_desktop_action_preview_tool.py`
- `tests/worker_desktop_capture.py`
- `tests/worker_desktop_contract.py`
- `tests/worker_desktop_input_execution.py`
- `tests/worker_desktop_physical_gate.py`
- `tests/worker_desktop_policy.py`
- `tests/worker_desktop_screenshot_entrypoint.py`
- `tests/worker_desktop_screenshot_tool.py`
- `tests/worker_desktop_vision_bridge.py`
- `tests/worker_desktop_win32.py`
- `tests/worker_desktop_win32_abi.py`
- `tests/worker_eval.py`
- `tests/worker_hardening.py`
- `tests/worker_hardening_stream_disconnect.py`
- `tests/worker_home_rig_runtime.py`
- `tests/worker_jobs.py`
- `tests/worker_migrate.py`
- `tests/worker_netguard.py`
- `tests/worker_occurrence_ledger.py`
- `tests/worker_paths.py`
- `tests/worker_pinned_http_transport.py`
- `tests/worker_public_address_parity.py`
- `tests/worker_rag.py`
- `tests/worker_rag_benchmark.py`
- `tests/worker_rag_cloud.py`
- `tests/worker_rag_corpus_contract.py`
- `tests/worker_rag_pdf_lifecycle.py`
- `tests/worker_rag_source_toggle.py`
- `tests/worker_read_connector_data_sharing_identity.py`
- `tests/worker_read_connector_eval.py`
- `tests/worker_read_connector_package_contract.py`
- `tests/worker_read_connector_provider_request.py`
- `tests/worker_read_connector_provider_transport.py`
- `tests/worker_read_connector_registration_hardening.py`
- `tests/worker_read_connector_runtime.py`
- `tests/worker_read_scope.py`
- `tests/worker_read_scope_windows_aliases.py`
- `tests/worker_research_claim_evidence.py`
- `tests/worker_research_contract.py`
- `tests/worker_research_data_sharing_adapter.py`
- `tests/worker_research_egress_ledger.py`
- `tests/worker_research_peer_authorization.py`
- `tests/worker_research_peer_binding.py`
- `tests/worker_research_peer_transfer.py`
- `tests/worker_research_sharing_boundary.py`
- `tests/worker_research_sharing_boundary_consistency.py`
- `tests/worker_research_sharing_execution.py`
- `tests/worker_research_sharing_execution_async_contract.py`
- `tests/worker_riggate_v1_contract.py`
- `tests/worker_schedule_admin_persistence_time.py`
- `tests/worker_schedule_admin_preview_time.py`
- `tests/worker_schedule_api.py`
- `tests/worker_schedule_api_guard.py`
- `tests/worker_schedule_api_time.py`
- `tests/worker_schedule_approval.py`
- `tests/worker_schedule_approval_time.py`
- `tests/worker_schedule_label.py`
- `tests/worker_schedule_lease.py`
- `tests/worker_schedule_post_execution.py`
- `tests/worker_schedule_revoke.py`
- `tests/worker_schedule_runner.py`
- `tests/worker_schedule_runtime.py`
- `tests/worker_schedule_service.py`
- `tests/worker_scheduler.py`
- `tests/worker_scheduler_pilot_barrier.py`
- `tests/worker_scheduler_pilot_manifest.py`
- `tests/worker_scheduler_single_flight.py`
- `tests/worker_scheduler_single_flight_lease.py`
- `tests/worker_scheduler_time.py`
- `tests/worker_scheduler_time_store.py`
- `tests/worker_toolhost.py`
- `tests/worker_tools.py`
- `tests/worker_tools_guardrail.py`
- `tests/worker_tools_readtools.py`
- `tests/worker_unit.py`
- `tests/worker_vision.py`
- `tests/worker_voice_baseline.py`
- `tests/worker_voice_stream.py`
- `tests/worker_voice_strip.py`
- `tests/worker_voice_tts_empty_synthesis.py`
- `tests/worker_voice_tts_voicerig_provider.py`
- `tests/worker_web_fetch_adapter.py`
- `tests/worker_web_research_capability.py`
- `tests/worker_web_research_fetch.py`
- `tests/worker_web_research_intent.py`
- `tests/worker_web_research_mount.py`
- `tests/worker_web_research_tool.py`
- `tests/workflow_access_derivation_parity.py`
- `tests/workflow_action_pins.py`
- `tests/workflow_activation_readiness.py`
- `tests/workflow_agent3_android_termination_ui.py`
- `tests/workflow_agent3_dormant.py`
- `tests/workflow_agent3_memory_protected_backup_physical.py`
- `tests/workflow_agent3_readonly_pilot_one_click.py`
- `tests/workflow_agent3_termination_physical_campaign.py`
- `tests/workflow_agent3_termination_ui_physical_operator.py`
- `tests/workflow_agent3_write_pilot_collect_operator.py`
- `tests/workflow_agent3_write_pilot_current_main_binding.py`
- `tests/workflow_agent3_write_pilot_final_gate.py`
- `tests/workflow_agent3_write_pilot_negative_operator.py`
- `tests/workflow_agent3_write_pilot_positive_operator.py`
- `tests/workflow_agent3_write_pilot_preflight.py`
- `tests/workflow_agent3_write_pilot_recorder.py`
- `tests/workflow_agent3_write_pilot_report.py`
- `tests/workflow_agent4_a4_18r_audit.py`
- `tests/workflow_agent4_a4_18r_fixture.py`
- `tests/workflow_agent4_a4_18r_operator_contract.py`
- `tests/workflow_agent4_a4_22_single_writer_pairing.py`
- `tests/workflow_agent4_a4_25f_audit.py`
- `tests/workflow_agent4_a4_25f_evidence_completion.py`
- `tests/workflow_agent4_a4_25f_operator_contract.py`
- `tests/workflow_agent4_a4_25f_physical_snapshot_harness.py`
- `tests/workflow_agent4_campaign_list_paging.py`
- `tests/workflow_agent4_dormant_runtime.py`
- `tests/workflow_agent4_evidence_records.py`
- `tests/workflow_agent4_foundation.py`
- `tests/workflow_agent4_pr_description.py`
- `tests/workflow_agent4_read_product_integration.py`
- `tests/workflow_agent4_storage_boundary.py`
- `tests/workflow_android_credential_commit.py`
- `tests/workflow_android_palette_divergence.py`
- `tests/workflow_android_scheduler_picker.py`
- `tests/workflow_appliance_lifecycle_updater_chain.py`
- `tests/workflow_baseline_one_click.py`
- `tests/workflow_bodyrig_contracts.py`
- `tests/workflow_brand_no_token_duplicates.py`
- `tests/workflow_browser_peer_public_validation.py`
- `tests/workflow_browser_peer_public_validation_operator.py`
- `tests/workflow_candidate_campaign.py`
- `tests/workflow_candidate_freeze.py`
- `tests/workflow_candidate_gate.py`
- `tests/workflow_chain_argument_check.py`
- `tests/workflow_client_capability_gates.py`
- `tests/workflow_client_microcopy_parity.py`
- `tests/workflow_client_path_segments.py`
- `tests/workflow_contract_adapter.py`
- `tests/workflow_current_state.py`
- `tests/workflow_data_sharing_decision.py`
- `tests/workflow_dep_pins.py`
- `tests/workflow_design_token_contrast.py`
- `tests/workflow_design_tokens.py`
- `tests/workflow_desktop_agent3_termination_ui_contract.py`
- `tests/workflow_doc_authority.py`
- `tests/workflow_freeze_check.py`
- `tests/workflow_milestone3_current_main.py`
- `tests/workflow_milestone3_current_main_handoff.py`
- `tests/workflow_pairing_link_parity.py`
- `tests/workflow_physical_validation_campaign.py`
- `tests/workflow_physical_validation_campaign_task_ui.py`
- `tests/workflow_physical_validation_final_gate.py`
- `tests/workflow_proof_campaign_gate_receipt_rule_matrix.py`
- `tests/workflow_proof_campaign_gate_receipt_unknown_gate.py`
- `tests/workflow_proof_campaign_owned_pairing.py`
- `tests/workflow_proof_campaign_skip_fail_closed.py`
- `tests/workflow_proof_scope_git_fail_closed.py`
- `tests/workflow_release.py`
- `tests/workflow_remaining_physical_pilots.py`
- `tests/workflow_rig_preflight.py`
- `tests/workflow_route_inventory.py`
- `tests/workflow_runner_offline.py`
- `tests/workflow_scheduler_m2_composition.py`
- `tests/workflow_scheduler_pilot_evidence.py`
- `tests/workflow_scheduler_pilot_operator.py`
- `tests/workflow_scheduler_pilot_wizard.py`
- `tests/workflow_screen_insets.py`
- `tests/workflow_spec_contract.py`
- `tests/workflow_stage_a_checkpoint.py`
- `tests/workflow_stage_a_one_click.py`
- `tests/workflow_stage_a_operator_surface.py`
- `tests/workflow_stage_a_phone_test.py`
- `tests/workflow_stage_a_physical_operator.py`
- `tests/workflow_stage_a_resume_cleanup.py`
- `tests/workflow_stage_a_scheduler_easy.py`
- `tests/workflow_stage_a_scheduler_finalize.py`
- `tests/workflow_stage_a_scheduler_publish.py`
- `tests/workflow_stage_a_voice_test.py`
- `tests/workflow_stage_b_one_click.py`
- `tests/workflow_stage_b_physical_gate.py`
- `tests/workflow_staged_promotion_runbook.py`
- `tests/workflow_stale_check.py`
- `tests/workflow_success_harness.py`
- `tests/workflow_t037_provider_request_boundary.py`
- `tests/workflow_t037_read_connector_boundary.py`
- `tests/workflow_test_coverage.py`
- `tests/workflow_updater_status_consistency.py`
- `tests/workflow_web_research_parity.py`
- `tests/workflow_worker_entrypoints.py`
