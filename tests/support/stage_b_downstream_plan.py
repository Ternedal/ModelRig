"""EXPERIMENT ONLY: 7-successful-run weighted downstream split; NEVER release authority.

Five earlier full-green measured runs are represented by frozen v2 cost weights:
3 older reference runs weighted 75%, 2 newer reference runs 25%.
Two newly completed full-green *parallel admission* runs add independent measured
contract times. New cost = round(0.5 * v2 five-run weighted cost
                         + 0.25 * #38089952531 actual contract duration
                         + 0.25 * #38089960759 actual contract duration).
These are source-data inputs to a deterministic three-shard/two-worker plan,
NOT a measured speedup. All 31 original contracts, signatures and 2400/3600s
per-contract hard timeouts remain unchanged. No runner-count increase.
"""
from __future__ import annotations

from math import isfinite

REFERENCE_FROZEN_MAIN_SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
REFERENCE_RUNS = (37845235363, 37942702263, 37982695916, 38036507743, 38048149969, 38089952531, 38089960759)
REFERENCE_LOG_JOB_IDS = (113575752295, 113575752244, 113575752294, 113898121077, 113898121549, 113898121140, 114028089322, 114028089336, 114028089364, 114177716907, 114177716996, 114177717062, 114216238480, 114216238489, 114216238515, 114333866546, 114333866590, 114333866615, 114338484180, 114338484223, 114338484236)
COST_SECONDS = {
    "rsi_pilot_exact_task_release_transaction_contract_base.py": 988,
    "rsi_pilot_exact_task_release_recovery_stage_b_driver.py": 1160,
    "rsi_pilot_exact_task_post_release_attestation_contract.py": 3087,
    "rsi_pilot_exact_task_deploy_readiness_evaluation_contract.py": 978,
    "rsi_pilot_exact_task_staging_deployment_plan_contract.py": 1908,
    "rsi_pilot_exact_task_staging_deployment_state_observation_contract.py": 1068,
    "rsi_pilot_exact_task_staging_deployment_authorization_contract.py": 970,
    "rsi_pilot_exact_task_staging_deployment_transaction_stage_b_driver.py": 1064,
    "rsi_pilot_exact_task_staging_deployment_recovery_stage_b_driver.py": 1039,
    "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py": 2268,
    "rsi_pilot_exact_task_staging_deployment_status_plan_contract.py": 1786,
    "rsi_pilot_exact_task_staging_deployment_status_state_observation_contract.py": 1758,
    "rsi_pilot_exact_task_staging_deployment_status_authorization_contract.py": 1516,
    "rsi_pilot_exact_task_staging_deployment_status_transaction_contract.py": 1789,
    "rsi_pilot_exact_task_staging_deployment_status_recovery_stage_b_driver.py": 1759,
    "rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract.py": 2246,
    "rsi_pilot_exact_task_staging_runtime_verification_contract.py": 1772,
    "rsi_pilot_exact_task_staging_runtime_build_identity_contract.py": 1743,
    "rsi_pilot_exact_task_staging_success_status_plan_contract.py": 1590,
    "rsi_pilot_exact_task_staging_success_status_state_observation_contract.py": 1856,
    "rsi_pilot_exact_task_staging_success_status_authorization_contract.py": 1779,
    "rsi_pilot_exact_task_staging_success_status_transaction_contract.py": 1511,
    "rsi_pilot_exact_task_staging_success_status_recovery_contract.py": 2620,
    "rsi_pilot_exact_task_post_staging_success_status_attestation_contract.py": 1684,
    "rsi_pilot_exact_task_production_activation_readiness_contract.py": 1587,
    "rsi_pilot_exact_task_production_activation_authorization_contract.py": 1868,
    "rsi_pilot_exact_task_production_activation_transaction_stage_b_driver.py": 1781,
    "rsi_pilot_exact_task_production_activation_recovery_stage_b_driver.py": 884,
    "rsi_pilot_exact_task_post_production_activation_attestation_stage_b_driver.py": 1041,
    "rsi_pilot_exact_task_product_pilot_start_requirements_contract.py": 1754,
    "rsi_pilot_exact_task_product_pilot_tail_stage_b_driver.py": 938,
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
