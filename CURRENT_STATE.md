# CURRENT_STATE.md

> **GENERATED — do not edit.** `python3 scripts/current_state.py`
> regenerates this; CI fails if the committed copy has drifted
> (`tests/workflow_current_state.py`). Everything here is read out of the
> code, so it cannot quietly become untrue. If a fact belongs here, teach
> the generator to read it -- do not type it in.

**Version:** 1.58.91

## Tools the model can see

`risk` gates what a tool may DO. `sensitivity` gates where its ANSWER may
travel. They are orthogonal.

| Tool | risk | sensitivity | isolated |
|---|---|---|---|
| `cancel_job` | write | operational | no |
| `current_datetime` | read | public | no |
| `delete_model` | write | operational | no |
| `job_status` | read | operational | no |
| `list_documents` | read | private | no |
| `list_models` | read | operational | no |
| `note_append` | write | private | no |
| `pull_model` | write | operational | no |
| `rig_status` | read | operational | no |

## Switches (default = what a rig does today)

| Env | Default |
|---|---|
| `KALIV_AGENT3_ENABLED` | `0` |
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

## Design docs and what they claim about themselves

| Doc | Status |
|---|---|
| `CLIENT_STATE_DESIGN.md` | DELVIST · trin 1-2 leveret (1.58.44/45) · trin 3-5 kræver device-test · **Ejer:** Anders |
| `ISOLATION_DESIGN.md` | LIVE · I0a+I0c leveret (dormant) · I0b afventer rig · **Ejer:** Anders (gates) — se CURRENT_STATE.md for switches |
| `RAG_DESIGN.md` | LIVE · replace-by-source leveret (1.58.40) · §5-kalibrering kræver rig · **Ejer:** Anders |
| `UPDATER_DESIGN.md` | LIVE · §4a self-update UDESTÅR (manuel udskiftning indtil da) · **Ejer:** Anders (rig) |
| `VALIDATION-1.58.49.md` | AFVENTER KØRSEL · resultatfelter tomme · gælder 1.58.49+ · **Ejer:** Anders (rig + telefon) |

## Test suites in CI

Run by glob, so a file that matches is a file that runs
(`tests/workflow_test_coverage.py` proves none can hide).

- `tests/backend_smoke.py`
- `tests/backend_v1.py`
- `tests/e2e.py`
- `tests/worker_agent3_atomic_journal.py`
- `tests/worker_agent3_capability_graph.py`
- `tests/worker_agent3_capability_graph_api.py`
- `tests/worker_agent3_capability_probe.py`
- `tests/worker_agent3_capability_receipt.py`
- `tests/worker_agent3_capability_receipt_api.py`
- `tests/worker_agent3_cloud_read_policy.py`
- `tests/worker_agent3_entrypoint.py`
- `tests/worker_agent3_integration.py`
- `tests/worker_agent3_late_cancel.py`
- `tests/worker_agent3_memory.py`
- `tests/worker_agent3_memory_api.py`
- `tests/worker_agent3_memory_context.py`
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
- `tests/worker_agent3_validation_gate.py`
- `tests/worker_agent3_validation_path_contract.py`
- `tests/worker_agent3_validation_status.py`
- `tests/worker_agent_continue.py`
- `tests/worker_agent_multistep.py`
- `tests/worker_audit.py`
- `tests/worker_backup.py`
- `tests/worker_desktop_policy.py`
- `tests/worker_eval.py`
- `tests/worker_hardening.py`
- `tests/worker_jobs.py`
- `tests/worker_migrate.py`
- `tests/worker_netguard.py`
- `tests/worker_paths.py`
- `tests/worker_rag.py`
- `tests/worker_rag_cloud.py`
- `tests/worker_read_scope.py`
- `tests/worker_schedule_api.py`
- `tests/worker_schedule_api_guard.py`
- `tests/worker_schedule_runner.py`
- `tests/worker_schedule_runtime.py`
- `tests/worker_schedule_service.py`
- `tests/worker_scheduler.py`
- `tests/worker_toolhost.py`
- `tests/worker_tools.py`
- `tests/worker_tools_guardrail.py`
- `tests/worker_tools_readtools.py`
- `tests/worker_unit.py`
- `tests/worker_vision.py`
- `tests/worker_voice_stream.py`
- `tests/worker_voice_strip.py`
- `tests/workflow_action_pins.py`
- `tests/workflow_activation_readiness.py`
- `tests/workflow_agent3_dormant.py`
- `tests/workflow_current_state.py`
- `tests/workflow_dep_pins.py`
- `tests/workflow_doc_authority.py`
- `tests/workflow_release.py`
- `tests/workflow_test_coverage.py`
- `tests/workflow_worker_entrypoints.py`
