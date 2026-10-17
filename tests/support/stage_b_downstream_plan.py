"""Experimental measured-cost Stage-B downstream assignment; no gate authority.

Evidence: three complete green exact-head runs on frozen V1 or clean V1-based
drafts: 37845235363, 37942702263, 37982695916.
Nine downstream shard log IDs in canonical run/shard order:
113575752295, 113575752244, 113575752294, 113898121077, 113898121549, 113898121140, 114028089322, 114028089336, 114028089364.

Observed per-contract wall times rounded from the mean across the three
runs. Not a benchmark guarantee: GitHub runner sharing affects execution.
Original 31 adversarial contracts, subprocess isolation, 2400/3600s
timeouts and two-worker-per-shard bound are preserved by the caller.
"""
from __future__ import annotations

from math import isfinite

REFERENCE_FROZEN_MAIN_SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
REFERENCE_RUNS = (37845235363, 37942702263, 37982695916)
REFERENCE_LOG_JOB_IDS = (113575752295, 113575752244, 113575752294, 113898121077, 113898121549, 113898121140, 114028089322, 114028089336, 114028089364)
COST_SECONDS = {
    "rsi_pilot_exact_task_deploy_readiness_evaluation_contract.py": 912,
    "rsi_pilot_exact_task_post_production_activation_attestation_stage_b_driver.py": 1086,
    "rsi_pilot_exact_task_post_release_attestation_contract.py": 3456,
    "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py": 2114,
    "rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract.py": 2086,
    "rsi_pilot_exact_task_post_staging_success_status_attestation_contract.py": 1856,
    "rsi_pilot_exact_task_product_pilot_start_requirements_contract.py": 1838,
    "rsi_pilot_exact_task_product_pilot_tail_stage_b_driver.py": 872,
    "rsi_pilot_exact_task_production_activation_authorization_contract.py": 1864,
    "rsi_pilot_exact_task_production_activation_readiness_contract.py": 1485,
    "rsi_pilot_exact_task_production_activation_recovery_stage_b_driver.py": 876,
    "rsi_pilot_exact_task_production_activation_transaction_stage_b_driver.py": 1869,
    "rsi_pilot_exact_task_release_recovery_stage_b_driver.py": 1156,
    "rsi_pilot_exact_task_release_transaction_contract_base.py": 914,
    "rsi_pilot_exact_task_staging_deployment_authorization_contract.py": 914,
    "rsi_pilot_exact_task_staging_deployment_plan_contract.py": 1905,
    "rsi_pilot_exact_task_staging_deployment_recovery_stage_b_driver.py": 1108,
    "rsi_pilot_exact_task_staging_deployment_state_observation_contract.py": 1138,
    "rsi_pilot_exact_task_staging_deployment_status_authorization_contract.py": 1506,
    "rsi_pilot_exact_task_staging_deployment_status_plan_contract.py": 1880,
    "rsi_pilot_exact_task_staging_deployment_status_recovery_stage_b_driver.py": 1848,
    "rsi_pilot_exact_task_staging_deployment_status_state_observation_contract.py": 1859,
    "rsi_pilot_exact_task_staging_deployment_status_transaction_contract.py": 1880,
    "rsi_pilot_exact_task_staging_deployment_transaction_stage_b_driver.py": 1113,
    "rsi_pilot_exact_task_staging_runtime_build_identity_contract.py": 1827,
    "rsi_pilot_exact_task_staging_runtime_verification_contract.py": 1856,
    "rsi_pilot_exact_task_staging_success_status_authorization_contract.py": 1861,
    "rsi_pilot_exact_task_staging_success_status_plan_contract.py": 1464,
    "rsi_pilot_exact_task_staging_success_status_recovery_contract.py": 2621,
    "rsi_pilot_exact_task_staging_success_status_state_observation_contract.py": 1846,
    "rsi_pilot_exact_task_staging_success_status_transaction_contract.py": 1489,
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
