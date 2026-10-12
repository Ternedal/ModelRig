"""EXPERIMENT ONLY: six isolated single-worker downstream runners.

For each of the exact 31 original canonical contracts, seconds are the rounded
mean of REAL PASS per-contract wall times extracted from both full green
single-worker six-runner exact-head runs 38083540450 and 38083575692.
These measured costs are input to a simulation, NEVER proof of a speedup.
Both 31-contract sets must be complete (12 source GitHub job logs).
The original 2400/3600-second per-contract deadlines, assertions,
fail-closed proof/nonce checks and process isolation are unchanged.
The unsharded full contract path is unchanged.
"""
from __future__ import annotations

from math import isfinite

REFERENCE_FROZEN_MAIN_SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
REFERENCE_RUNS = (38083540450, 38083575692)
REFERENCE_LOG_JOB_IDS = (114321321398, 114321321450, 114321321405, 114321321390, 114321321392, 114321321407, 114336594175, 114336594115, 114336594156, 114336594206, 114336594173, 114336594220)
COST_SECONDS = {
    "rsi_pilot_exact_task_release_transaction_contract_base.py": 831,
    "rsi_pilot_exact_task_release_recovery_stage_b_driver.py": 1126,
    "rsi_pilot_exact_task_post_release_attestation_contract.py": 2171,
    "rsi_pilot_exact_task_deploy_readiness_evaluation_contract.py": 774,
    "rsi_pilot_exact_task_staging_deployment_plan_contract.py": 1381,
    "rsi_pilot_exact_task_staging_deployment_state_observation_contract.py": 973,
    "rsi_pilot_exact_task_staging_deployment_authorization_contract.py": 982,
    "rsi_pilot_exact_task_staging_deployment_transaction_stage_b_driver.py": 1110,
    "rsi_pilot_exact_task_staging_deployment_recovery_stage_b_driver.py": 676,
    "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py": 1833,
    "rsi_pilot_exact_task_staging_deployment_status_plan_contract.py": 1854,
    "rsi_pilot_exact_task_staging_deployment_status_state_observation_contract.py": 1609,
    "rsi_pilot_exact_task_staging_deployment_status_authorization_contract.py": 1620,
    "rsi_pilot_exact_task_staging_deployment_status_transaction_contract.py": 1358,
    "rsi_pilot_exact_task_staging_deployment_status_recovery_stage_b_driver.py": 1274,
    "rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract.py": 2605,
    "rsi_pilot_exact_task_staging_runtime_verification_contract.py": 1610,
    "rsi_pilot_exact_task_staging_runtime_build_identity_contract.py": 1586,
    "rsi_pilot_exact_task_staging_success_status_plan_contract.py": 1335,
    "rsi_pilot_exact_task_staging_success_status_state_observation_contract.py": 1585,
    "rsi_pilot_exact_task_staging_success_status_authorization_contract.py": 1826,
    "rsi_pilot_exact_task_staging_success_status_transaction_contract.py": 1287,
    "rsi_pilot_exact_task_staging_success_status_recovery_contract.py": 2264,
    "rsi_pilot_exact_task_post_staging_success_status_attestation_contract.py": 1289,
    "rsi_pilot_exact_task_production_activation_readiness_contract.py": 1147,
    "rsi_pilot_exact_task_production_activation_authorization_contract.py": 1345,
    "rsi_pilot_exact_task_production_activation_transaction_stage_b_driver.py": 1607,
    "rsi_pilot_exact_task_production_activation_recovery_stage_b_driver.py": 1079,
    "rsi_pilot_exact_task_post_production_activation_attestation_stage_b_driver.py": 953,
    "rsi_pilot_exact_task_product_pilot_start_requirements_contract.py": 1153,
    "rsi_pilot_exact_task_product_pilot_tail_stage_b_driver.py": 686,
}

def balanced_downstream_shards(files) -> tuple[tuple[str, ...], ...]:
    canonical = tuple(files)
    if (len(canonical) != 31 or len(set(canonical)) != 31
            or set(canonical) != set(COST_SECONDS)):
        raise AssertionError("downstream plan must contain exactly the 31 canonical contracts")
    if any(type(v) not in (int, float) or not isfinite(v) or v <= 0
           for v in COST_SECONDS.values()):
        raise AssertionError("downstream costs must be positive finite seconds")

    original_index = {name: i for i, name in enumerate(canonical)}
    # Six independent downstream GitHub jobs each launch ONE isolated child
    # at a time. Relative to 3 jobs x 2 children, the total maximum number
    # of concurrent contracts stays 6; each child now owns its runner CPU.
    # No change to contract assertions, subprocess isolation or timeouts.
    groups: list[list[str]] = [[] for _ in range(6)]
    loads: list[float] = [0.0] * 6
    for filename in sorted(canonical, key=lambda x: (-COST_SECONDS[x], original_index[x])):
        shard_index = min(range(6), key=lambda i: (loads[i], i))
        groups[shard_index].append(filename)
        loads[shard_index] += COST_SECONDS[filename]

    result = tuple(tuple(group) for group in groups)
    flat = [filename for shard in result for filename in shard]
    if (len(flat) != 31 or set(flat) != set(canonical)
            or any(not shard for shard in result)):
        raise AssertionError("downstream assignment lost or duplicated contracts")
    return result
