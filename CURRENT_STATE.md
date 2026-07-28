# CURRENT_STATE.md

> **GENERATED — do not edit.** `python3 scripts/current_state.py`
> regenerates this; CI fails if the committed copy has drifted
> (`tests/workflow_current_state.py`). Everything here is read out of the
> code, so it cannot quietly become untrue. If a fact belongs here, teach
> the generator to read it -- do not type it in.

**Version:** 1.58.147

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
| `KALIV_AGENT3_VALIDATION_MAX_AGE_HOURS` | `(unset)` |
| `KALIV_AGENT3_VALIDATION_REPORT` | `(unset)` |
| `KALIV_ALLOW_RAG_CLOUD` | `` |
| `KALIV_CLOUD_ALLOW_PRIVATE` | `0` |
| `KALIV_DATA_DIR` | `(unset)` |
| `KALIV_EGRESS_GATE` | `` |
| `KALIV_MAX_UPLOAD_MB` | `25` |
| `KALIV_PULL_READ_TIMEOUT_S` | `600` |
| `KALIV_SCHEDULER` | `` |
| `KALIV_SCHEDULER_API` | `0` |
| `KALIV_SCHEDULER_POLL_S` | `` |
| `KALIV_TOOLS_DIR` | `(unset)` |
| `KALIV_TOOLS_ENABLED` | `0` |
| `KALIV_TOOL_ISOLATION` | `` |
| `KALIV_VISION_MODEL` | `(unset)` |
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
| `RAG_DESIGN.md` | LIVE · replace-by-source leveret (1.58.40) · T-043 benchmark-harness leveret · måling/kalibrering kræver rig · **Ejer:** Anders |
| `UPDATER_DESIGN.md` | LIVE · §4a self-update UDESTÅR (manuel udskiftning indtil da) · **Ejer:** Anders (rig) |
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
- `tests/worker_agent3_memory_protection.py`
- `tests/worker_agent3_memory_protection_migration.py`
- `tests/worker_agent3_model_eval.py`
- `tests/worker_agent3_outcome_answer.py`
- `tests/worker_agent3_outcome_answer_api.py`
- `tests/worker_agent3_outcome_context.py`
- `tests/worker_agent3_outcome_context_adversarial.py`
- `tests/worker_agent3_plan_authority_api.py`
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
- `tests/worker_agent3_unattended_execution.py`
- `tests/worker_agent3_validation_gate.py`
- `tests/worker_agent3_validation_path_contract.py`
- `tests/worker_agent3_validation_status.py`
- `tests/worker_agent3_workflow_completion.py`
- `tests/worker_agent3_workflow_receipt_integrity.py`
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
- `tests/worker_unit.py`
