"""EXPERIMENT: deterministic 31-contract Stage-B cost balance on parallel admission.

All timings are extracted from completed PASS lines of 15 downstream shard
job logs spanning five separately full-green exact-head runs: #2103,
two robust-v2 runs (#2118), and two parallel-admission runs (#2122).
For each original canonical file use round(0.7 * five-run mean
+ 0.3 * five-run maximum). No fabricated timing or negative test was used.
The result is a SCHEDULING HEURISTIC only; not performance acceptance proof.
The unchanged executor still runs only 2 isolated children per downstream
shard; per-child hard timeout limits remain 2400s or 3600s as applicable.
"""
from __future__ import annotations

from math import isfinite

REFERENCE_FROZEN_MAIN_SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
REFERENCE_RUNS = (37982695916, 38081640622, 38081628439, 38089952531, 38089960759)
REFERENCE_LOG_JOB_IDS = (
    114028089322, 114028089336, 114028089364,
    114313721674, 114313721567, 114313721600,
    114329340864, 114329340802, 114329340771,
    114333866615, 114333866546, 114333866590,
    114338484180, 114338484223, 114338484236,
)
COST_SECONDS = {
    "rsi_pilot_exact_task_release_transaction_contract_base.py": 1049,
    "rsi_pilot_exact_task_release_recovery_stage_b_driver.py": 1129,
    "rsi_pilot_exact_task_post_release_attestation_contract.py": 3225,
    "rsi_pilot_exact_task_deploy_readiness_evaluation_contract.py": 986,
    "rsi_pilot_exact_task_staging_deployment_plan_contract.py": 1910,
    "rsi_pilot_exact_task_staging_deployment_state_observation_contract.py": 1115,
    "rsi_pilot_exact_task_staging_deployment_authorization_contract.py": 1023,
    "rsi_pilot_exact_task_staging_deployment_transaction_stage_b_driver.py": 1075,
    "rsi_pilot_exact_task_staging_deployment_recovery_stage_b_driver.py": 1030,
    "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py": 2281,
    "rsi_pilot_exact_task_staging_deployment_status_plan_contract.py": 1806,
    "rsi_pilot_exact_task_staging_deployment_status_state_observation_contract.py": 1754,
    "rsi_pilot_exact_task_staging_deployment_status_authorization_contract.py": 1604,
    "rsi_pilot_exact_task_staging_deployment_status_transaction_contract.py": 1875,
    "rsi_pilot_exact_task_staging_deployment_status_recovery_stage_b_driver.py": 1769,
    "rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract.py": 2255,
    "rsi_pilot_exact_task_staging_runtime_verification_contract.py": 1871,
    "rsi_pilot_exact_task_staging_runtime_build_identity_contract.py": 1750,
    "rsi_pilot_exact_task_staging_success_status_plan_contract.py": 1703,
    "rsi_pilot_exact_task_staging_success_status_state_observation_contract.py": 1859,
    "rsi_pilot_exact_task_staging_success_status_authorization_contract.py": 1802,
    "rsi_pilot_exact_task_staging_success_status_transaction_contract.py": 1602,
    "rsi_pilot_exact_task_staging_success_status_recovery_contract.py": 2639,
    "rsi_pilot_exact_task_post_staging_success_status_attestation_contract.py": 1795,
    "rsi_pilot_exact_task_production_activation_readiness_contract.py": 1586,
    "rsi_pilot_exact_task_production_activation_authorization_contract.py": 1897,
    "rsi_pilot_exact_task_production_activation_transaction_stage_b_driver.py": 1802,
    "rsi_pilot_exact_task_production_activation_recovery_stage_b_driver.py": 937,
    "rsi_pilot_exact_task_post_production_activation_attestation_stage_b_driver.py": 1055,
    "rsi_pilot_exact_task_product_pilot_start_requirements_contract.py": 1766,
    "rsi_pilot_exact_task_product_pilot_tail_stage_b_driver.py": 941,
}


def balanced_downstream_shards(files) -> tuple[tuple[str, ...], ...]:
    canonical = tuple(files)
    if (
        len(canonical) != 31
        or len(set(canonical)) != 31
        or set(canonical) != set(COST_SECONDS)
    ):
        raise AssertionError("downstream plan must contain exactly 31 canonical files")
    if any(
        type(cost) not in (int, float) or not isfinite(cost) or cost <= 0
        for cost in COST_SECONDS.values()
    ):
        raise AssertionError("downstream cost must be a finite positive number")
    original_index = {name: i for i, name in enumerate(canonical)}
    groups: list[list[str]] = [[], [], []]
    loads: list[list[float]] = [[0.0, 0.0] for _ in range(3)]
    for filename in sorted(
        canonical, key=lambda name: (-COST_SECONDS[name], original_index[name])
    ):
        cost = COST_SECONDS[filename]
        options = []
        for shard_index, workers in enumerate(loads):
            worker_index = 0 if workers[0] <= workers[1] else 1
            projected = list(workers)
            projected[worker_index] += cost
            options.append(
                (
                    max(projected),
                    projected[worker_index],
                    max(workers),
                    shard_index,
                    worker_index,
                )
            )
        _, _, _, shard_index, worker_index = min(options)
        groups[shard_index].append(filename)
        loads[shard_index][worker_index] += cost

    selected = tuple(tuple(group) for group in groups)
    flattened = [filename for group in selected for filename in group]
    if (
        len(flattened) != 31
        or set(flattened) != set(canonical)
        or len(set(flattened)) != 31
        or any(not group for group in selected)
    ):
        raise AssertionError("downstream planner lost or duplicated a contract")
    return selected
