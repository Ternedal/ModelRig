"""EXPERIMENT ONLY: measured-cost 3x2 downstream sharding with parallel admission.

Actual per-contract PASS times from four independent FULL GREEN exact-head
runs (two original strided #2122; two earlier balanced #2118).
COST_SECONDS = rounded arithmetic mean of those four true contract timings.
All 31 canonical contracts remain active and isolated; original 2400/3600s
hard timeouts and no more than two workers per shard remain unchanged.
Modelled runtime is not proof of real performance or release authority.
"""
from __future__ import annotations

from math import isfinite

REFERENCE_FROZEN_MAIN_SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
REFERENCE_RUNS = (38089952531, 38089960759, 38081640622, 38081628439)
REFERENCE_LOG_JOB_IDS = (114333866615, 114333866546, 114333866590, 114338484180, 114338484223, 114338484236, 114313721674, 114313721567, 114313721600, 114329340864, 114329340802, 114329340771)
COST_SECONDS = {
    "rsi_pilot_exact_task_release_transaction_contract_base.py": 1039,
    "rsi_pilot_exact_task_release_recovery_stage_b_driver.py": 1087,
    "rsi_pilot_exact_task_post_release_attestation_contract.py": 3009,
    "rsi_pilot_exact_task_deploy_readiness_evaluation_contract.py": 987,
    "rsi_pilot_exact_task_staging_deployment_plan_contract.py": 1838,
    "rsi_pilot_exact_task_staging_deployment_state_observation_contract.py": 1037,
    "rsi_pilot_exact_task_staging_deployment_authorization_contract.py": 1014,
    "rsi_pilot_exact_task_staging_deployment_transaction_stage_b_driver.py": 1042,
    "rsi_pilot_exact_task_staging_deployment_recovery_stage_b_driver.py": 957,
    "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py": 2295,
    "rsi_pilot_exact_task_staging_deployment_status_plan_contract.py": 1748,
    "rsi_pilot_exact_task_staging_deployment_status_state_observation_contract.py": 1626,
    "rsi_pilot_exact_task_staging_deployment_status_authorization_contract.py": 1608,
    "rsi_pilot_exact_task_staging_deployment_status_transaction_contract.py": 1800,
    "rsi_pilot_exact_task_staging_deployment_status_recovery_stage_b_driver.py": 1635,
    "rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract.py": 2274,
    "rsi_pilot_exact_task_staging_runtime_verification_contract.py": 1792,
    "rsi_pilot_exact_task_staging_runtime_build_identity_contract.py": 1617,
    "rsi_pilot_exact_task_staging_success_status_plan_contract.py": 1684,
    "rsi_pilot_exact_task_staging_success_status_state_observation_contract.py": 1789,
    "rsi_pilot_exact_task_staging_success_status_authorization_contract.py": 1658,
    "rsi_pilot_exact_task_staging_success_status_transaction_contract.py": 1615,
    "rsi_pilot_exact_task_staging_success_status_recovery_contract.py": 2528,
    "rsi_pilot_exact_task_post_staging_success_status_attestation_contract.py": 1649,
    "rsi_pilot_exact_task_production_activation_readiness_contract.py": 1594,
    "rsi_pilot_exact_task_production_activation_authorization_contract.py": 1812,
    "rsi_pilot_exact_task_production_activation_transaction_stage_b_driver.py": 1658,
    "rsi_pilot_exact_task_production_activation_recovery_stage_b_driver.py": 939,
    "rsi_pilot_exact_task_post_production_activation_attestation_stage_b_driver.py": 1016,
    "rsi_pilot_exact_task_product_pilot_start_requirements_contract.py": 1630,
    "rsi_pilot_exact_task_product_pilot_tail_stage_b_driver.py": 946,
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
    groups: list[list[str]] = [[], [], []]
    # Simulate completion-order assignment to exactly two slots per existing
    # downstream shard. Never change process count, original contracts, or CI.
    loads: list[list[float]] = [[0.0, 0.0] for _ in range(3)]
    for filename in sorted(canonical, key=lambda x: (-COST_SECONDS[x], original_index[x])):
        cost = COST_SECONDS[filename]
        options = []
        for shard_index, workers in enumerate(loads):
            worker_index = 0 if workers[0] <= workers[1] else 1
            projected = list(workers)
            projected[worker_index] += cost
            options.append((
                max(projected),
                projected[worker_index],
                max(workers),
                shard_index,
                worker_index,
            ))
        _, _, _, shard_index, worker_index = min(options)
        groups[shard_index].append(filename)
        loads[shard_index][worker_index] += cost

    result = tuple(tuple(group) for group in groups)
    flat = [filename for shard in result for filename in shard]
    if (len(flat) != 31 or set(flat) != set(canonical)
            or any(not shard for shard in result)):
        raise AssertionError("downstream assignment lost or duplicated contracts")
    return result
