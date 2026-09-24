"""Measured Stage-B contract costs for deterministic weighted sharding.

Measurements come from successful exact-head qualification run 35960087681 on
head c6c8ca2fa948270fd8beb49b362260bdbfb2c8be (2026-09-24).  Values are
wall-clock seconds printed by the isolated contract drivers.  The tables are
checked in deliberately: adding/removing a contract without refreshing measured
costs fails closed through weighted_shards().
"""
from __future__ import annotations

MEASUREMENT_WORKFLOW_RUN_ID = 35960087681
MEASUREMENT_HEAD_SHA = "c6c8ca2fa948270fd8beb49b362260bdbfb2c8be"

MIDCHAIN_COST_SECONDS: dict[str, float] = {
    "rsi_pilot_exact_task_execution_plan_requirements_contract.py": 219.1,
    "rsi_pilot_exact_task_development_task_binding_contract.py": 318.9,
    "rsi_pilot_exact_task_development_task_binding_live_provenance_contract.py": 156.1,
    "rsi_pilot_exact_task_executor_capability_live_guard_contract.py": 218.8,
    "rsi_pilot_exact_task_executor_secret_custody_contract.py": 0.6,
    "rsi_pilot_exact_task_executor_capability_semantics_contract.py": 157.3,
    "rsi_pilot_exact_task_execution_plan_contract.py": 220.6,
    "rsi_pilot_exact_task_prelaunch_reservation_contract.py": 316.5,
    "rsi_pilot_exact_task_execution_transaction_contract.py": 161.8,
    "rsi_pilot_exact_task_post_execution_evaluation_contract.py": 219.0,
    "rsi_pilot_exact_task_local_commit_plan_contract.py": 320.5,
    "rsi_pilot_exact_task_local_commit_object_identity_contract.py": 162.8,
    "rsi_pilot_exact_task_local_commit_write_authorization_contract.py": 225.1,
    "rsi_pilot_exact_task_local_commit_transaction_contract.py": 340.4,
    "rsi_pilot_exact_task_post_commit_integration_evaluation_contract.py": 191.4,
    "rsi_pilot_exact_task_integration_readiness_contract.py": 290.2,
    "rsi_pilot_exact_task_remote_publication_plan_contract.py": 491.7,
    "rsi_pilot_exact_task_remote_state_observation_contract.py": 414.4,
    "rsi_pilot_exact_task_remote_publication_authorization_contract.py": 776.9,
    "rsi_pilot_exact_task_remote_publication_transaction_contract.py": 1994.4,
    "rsi_pilot_exact_task_remote_publication_recovery_contract.py": 447.8,
    "rsi_pilot_exact_task_post_publication_attestation_contract.py": 821.7,
    "rsi_pilot_exact_task_pr_lifecycle_authorization_contract.py": 1133.9,
    "rsi_pilot_exact_task_pr_lifecycle_transaction_contract.py": 613.1,
    "rsi_pilot_exact_task_pr_lifecycle_recovery_contract.py": 846.6,
    "rsi_pilot_exact_task_post_lifecycle_attestation_contract.py": 1147.8,
    "rsi_pilot_exact_task_review_state_attestation_contract.py": 623.9,
    "rsi_pilot_exact_task_merge_readiness_evaluation_contract.py": 837.0,
    "rsi_pilot_exact_task_merge_authorization_contract.py": 1162.6,
    "rsi_pilot_exact_task_merge_transaction_contract.py": 622.7,
    "rsi_pilot_exact_task_merge_recovery_contract.py": 845.8,
    "rsi_pilot_exact_task_post_merge_attestation_contract.py": 2654.4,
    "rsi_pilot_exact_task_release_readiness_evaluation_contract.py": 624.8,
    "rsi_pilot_exact_task_release_plan_contract.py": 840.7,
    "rsi_pilot_exact_task_release_state_observation_contract.py": 1161.7,
    "rsi_pilot_exact_task_release_authorization_contract.py": 632.3,
}

DOWNSTREAM_COST_SECONDS: dict[str, float] = {
    "rsi_pilot_exact_task_release_transaction_contract_base.py": 1178.1,
    "rsi_pilot_exact_task_release_recovery_stage_b_driver.py": 1142.9,
    "rsi_pilot_exact_task_post_release_attestation_contract.py": 3522.4,
    "rsi_pilot_exact_task_deploy_readiness_evaluation_contract.py": 1152.9,
    "rsi_pilot_exact_task_staging_deployment_plan_contract.py": 1873.9,
    "rsi_pilot_exact_task_staging_deployment_state_observation_contract.py": 1161.5,
    "rsi_pilot_exact_task_staging_deployment_authorization_contract.py": 1132.1,
    "rsi_pilot_exact_task_staging_deployment_transaction_stage_b_driver.py": 1102.8,
    "rsi_pilot_exact_task_staging_deployment_recovery_stage_b_driver.py": 1114.3,
    "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py": 2646.2,
    "rsi_pilot_exact_task_staging_deployment_status_plan_contract.py": 1850.1,
    "rsi_pilot_exact_task_staging_deployment_status_state_observation_contract.py": 1873.9,
    "rsi_pilot_exact_task_staging_deployment_status_authorization_contract.py": 1884.2,
    "rsi_pilot_exact_task_staging_deployment_status_transaction_contract.py": 1841.4,
    "rsi_pilot_exact_task_staging_deployment_status_recovery_stage_b_driver.py": 1870.3,
    "rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract.py": 2632.9,
    "rsi_pilot_exact_task_staging_runtime_verification_contract.py": 1807.7,
    "rsi_pilot_exact_task_staging_runtime_build_identity_contract.py": 1842.2,
    "rsi_pilot_exact_task_staging_success_status_plan_contract.py": 1854.9,
    "rsi_pilot_exact_task_staging_success_status_state_observation_contract.py": 1819.3,
    "rsi_pilot_exact_task_staging_success_status_authorization_contract.py": 1885.4,
    "rsi_pilot_exact_task_staging_success_status_transaction_contract.py": 1878.2,
    "rsi_pilot_exact_task_staging_success_status_recovery_contract.py": 2598.2,
    "rsi_pilot_exact_task_post_staging_success_status_attestation_contract.py": 1858.5,
    "rsi_pilot_exact_task_production_activation_readiness_contract.py": 1857.6,
    "rsi_pilot_exact_task_production_activation_authorization_contract.py": 1843.8,
    "rsi_pilot_exact_task_production_activation_transaction_stage_b_driver.py": 1901.1,
    "rsi_pilot_exact_task_production_activation_recovery_stage_b_driver.py": 1093.1,
    "rsi_pilot_exact_task_post_production_activation_attestation_stage_b_driver.py": 1061.2,
    "rsi_pilot_exact_task_product_pilot_start_requirements_contract.py": 1875.8,
    "rsi_pilot_exact_task_product_pilot_tail_stage_b_driver.py": 1094.3,
}
