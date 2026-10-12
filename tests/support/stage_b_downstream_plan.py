"""DRAFT ONLY: evidence-based downstream balancing on parallel-admission parent.

The complete set of 31 canonical contracts and two independent isolated child
processes per shard are unchanged. New observed cost weights use 65% the
five-fully-green-run history locked in #2118, plus 35% the mean of the two
independently full-green #2122 exact-head runs (38089952531, 38089960759).
These timings were measured with the ORIGINAL strided partition, not guessed.
Predictions are NOT a real speedup. No safety, per-child timeout, or gate change.
"""
from __future__ import annotations

from math import isfinite

REFERENCE_FROZEN_MAIN_SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
REFERENCE_RUNS = (37845235363, 37942702263, 37982695916, 38036507743, 38048149969, 38089952531, 38089960759)
REFERENCE_LOG_JOB_IDS = (113575752295, 113575752244, 113575752294, 113898121077, 113898121549, 113898121140, 114028089322, 114028089336, 114028089364, 114177716907, 114177716996, 114177717062, 114216238480, 114216238489, 114216238515, 114333866615, 114333866546, 114333866590, 114338484180, 114338484223, 114338484236)
COST_SECONDS = {
    "rsi_pilot_exact_task_release_transaction_contract_base.py": 985,
    "rsi_pilot_exact_task_release_recovery_stage_b_driver.py": 1159,
    "rsi_pilot_exact_task_post_release_attestation_contract.py": 3104,
    "rsi_pilot_exact_task_deploy_readiness_evaluation_contract.py": 977,
    "rsi_pilot_exact_task_staging_deployment_plan_contract.py": 1909,
    "rsi_pilot_exact_task_staging_deployment_state_observation_contract.py": 1089,
    "rsi_pilot_exact_task_staging_deployment_authorization_contract.py": 970,
    "rsi_pilot_exact_task_staging_deployment_transaction_stage_b_driver.py": 1047,
    "rsi_pilot_exact_task_staging_deployment_recovery_stage_b_driver.py": 1061,
    "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py": 2262,
    "rsi_pilot_exact_task_staging_deployment_status_plan_contract.py": 1762,
    "rsi_pilot_exact_task_staging_deployment_status_state_observation_contract.py": 1791,
    "rsi_pilot_exact_task_staging_deployment_status_authorization_contract.py": 1488,
    "rsi_pilot_exact_task_staging_deployment_status_transaction_contract.py": 1765,
    "rsi_pilot_exact_task_staging_deployment_status_recovery_stage_b_driver.py": 1788,
    "rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract.py": 2241,
    "rsi_pilot_exact_task_staging_runtime_verification_contract.py": 1747,
    "rsi_pilot_exact_task_staging_runtime_build_identity_contract.py": 1771,
    "rsi_pilot_exact_task_staging_success_status_plan_contract.py": 1583,
    "rsi_pilot_exact_task_staging_success_status_state_observation_contract.py": 1854,
    "rsi_pilot_exact_task_staging_success_status_authorization_contract.py": 1805,
    "rsi_pilot_exact_task_staging_success_status_transaction_contract.py": 1480,
    "rsi_pilot_exact_task_staging_success_status_recovery_contract.py": 2621,
    "rsi_pilot_exact_task_post_staging_success_status_attestation_contract.py": 1686,
    "rsi_pilot_exact_task_production_activation_readiness_contract.py": 1584,
    "rsi_pilot_exact_task_production_activation_authorization_contract.py": 1868,
    "rsi_pilot_exact_task_production_activation_transaction_stage_b_driver.py": 1808,
    "rsi_pilot_exact_task_production_activation_recovery_stage_b_driver.py": 867,
    "rsi_pilot_exact_task_post_production_activation_attestation_stage_b_driver.py": 1024,
    "rsi_pilot_exact_task_product_pilot_start_requirements_contract.py": 1782,
    "rsi_pilot_exact_task_product_pilot_tail_stage_b_driver.py": 935,
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
