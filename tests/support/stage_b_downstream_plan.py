"""DRAFT: robust measured-cost Stage-B downstream reassignment; no gate authority.

Seven complete green exact-head runs: 37845235363, 37942702263, 37982695916, 38036507743, 38048149969, 38083540450, 38083575692.
Twenty-seven pinned GitHub downstream job logs: 113575752295, 113575752244, 113575752294, 113898121077, 113898121549, 113898121140, 114028089322, 114028089336, 114028089364, 114177716907, 114177716996, 114177717062, 114216238480, 114216238489, 114216238515, 114321321398, 114321321450, 114321321405, 114321321390, 114321321392, 114321321407, 114336594175, 114336594115, 114336594156, 114336594206, 114336594173, 114336594220.
For each canonical contract: round(0.75 * the five-run calibrated
3x2-hosted-worker cost + 0.25 * two six-single-runner observed means).
Each original file still runs in full, and plans have NO release authority.
The historical weight guards against overfitting two six-runner observations.
Single- and double-worker timings differ because of runner contention. Predictions are NOT evidence of acceleration.
Do not skip/replace any contract, alter subprocess isolation or change
original 2400/3600-second hard timeouts and 1 worker per downstream shard.
"""
from __future__ import annotations

from math import isfinite

REFERENCE_FROZEN_MAIN_SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
REFERENCE_RUNS = (37845235363, 37942702263, 37982695916, 38036507743, 38048149969, 38083540450, 38083575692)
REFERENCE_LOG_JOB_IDS = (113575752295, 113575752244, 113575752294, 113898121077, 113898121549, 113898121140, 114028089322, 114028089336, 114028089364, 114177716907, 114177716996, 114177717062, 114216238480, 114216238489, 114216238515, 114321321398, 114321321450, 114321321405, 114321321390, 114321321392, 114321321407, 114336594175, 114336594115, 114336594156, 114336594206, 114336594173, 114336594220)
COST_SECONDS = {
    "rsi_pilot_exact_task_deploy_readiness_evaluation_contract.py": 925,
    "rsi_pilot_exact_task_post_production_activation_attestation_stage_b_driver.py": 977,
    "rsi_pilot_exact_task_post_release_attestation_contract.py": 2900,
    "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py": 2144,
    "rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract.py": 2322,
    "rsi_pilot_exact_task_post_staging_success_status_attestation_contract.py": 1590,
    "rsi_pilot_exact_task_product_pilot_start_requirements_contract.py": 1674,
    "rsi_pilot_exact_task_product_pilot_tail_stage_b_driver.py": 868,
    "rsi_pilot_exact_task_production_activation_authorization_contract.py": 1737,
    "rsi_pilot_exact_task_production_activation_readiness_contract.py": 1470,
    "rsi_pilot_exact_task_production_activation_recovery_stage_b_driver.py": 890,
    "rsi_pilot_exact_task_production_activation_transaction_stage_b_driver.py": 1805,
    "rsi_pilot_exact_task_release_recovery_stage_b_driver.py": 1149,
    "rsi_pilot_exact_task_release_transaction_contract_base.py": 942,
    "rsi_pilot_exact_task_staging_deployment_authorization_contract.py": 973,
    "rsi_pilot_exact_task_staging_deployment_plan_contract.py": 1777,
    "rsi_pilot_exact_task_staging_deployment_recovery_stage_b_driver.py": 1002,
    "rsi_pilot_exact_task_staging_deployment_state_observation_contract.py": 1097,
    "rsi_pilot_exact_task_staging_deployment_status_authorization_contract.py": 1473,
    "rsi_pilot_exact_task_staging_deployment_status_plan_contract.py": 1744,
    "rsi_pilot_exact_task_staging_deployment_status_recovery_stage_b_driver.py": 1709,
    "rsi_pilot_exact_task_staging_deployment_status_state_observation_contract.py": 1804,
    "rsi_pilot_exact_task_staging_deployment_status_transaction_contract.py": 1621,
    "rsi_pilot_exact_task_staging_deployment_transaction_stage_b_driver.py": 1034,
    "rsi_pilot_exact_task_staging_runtime_build_identity_contract.py": 1773,
    "rsi_pilot_exact_task_staging_runtime_verification_contract.py": 1669,
    "rsi_pilot_exact_task_staging_success_status_authorization_contract.py": 1857,
    "rsi_pilot_exact_task_staging_success_status_plan_contract.py": 1508,
    "rsi_pilot_exact_task_staging_success_status_recovery_contract.py": 2535,
    "rsi_pilot_exact_task_staging_success_status_state_observation_contract.py": 1784,
    "rsi_pilot_exact_task_staging_success_status_transaction_contract.py": 1377,
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
