"""Experimental two-run, cost-aware Stage-B midchain shard mapping (no execution).

Inputs: certified exact-head ModelRig runs 37845235363 and 37942702263,
36 contracts with mean rounded observed seconds. Estimates are NOT SLAs.
The two >1800s contracts remain in serial shard 2/3 because moving them
to a 1800-second standard-timeout shard could fabricate a failure.
"""
from __future__ import annotations

from math import isfinite

REFERENCE_MAIN_SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
REFERENCE_RUNS = (37845235363, 37942702263)
COST_SECONDS = {
    "rsi_pilot_exact_task_execution_plan_requirements_contract.py": 299,
    "rsi_pilot_exact_task_development_task_binding_contract.py": 320,
    "rsi_pilot_exact_task_development_task_binding_live_provenance_contract.py": 192,
    "rsi_pilot_exact_task_executor_capability_live_guard_contract.py": 303,
    "rsi_pilot_exact_task_executor_secret_custody_contract.py": 1,
    "rsi_pilot_exact_task_executor_capability_semantics_contract.py": 191,
    "rsi_pilot_exact_task_execution_plan_contract.py": 299,
    "rsi_pilot_exact_task_prelaunch_reservation_contract.py": 317,
    "rsi_pilot_exact_task_execution_transaction_contract.py": 190,
    "rsi_pilot_exact_task_post_execution_evaluation_contract.py": 300,
    "rsi_pilot_exact_task_local_commit_plan_contract.py": 320,
    "rsi_pilot_exact_task_local_commit_object_identity_contract.py": 196,
    "rsi_pilot_exact_task_local_commit_write_authorization_contract.py": 311,
    "rsi_pilot_exact_task_local_commit_transaction_contract.py": 345,
    "rsi_pilot_exact_task_post_commit_integration_evaluation_contract.py": 227,
    "rsi_pilot_exact_task_integration_readiness_contract.py": 384,
    "rsi_pilot_exact_task_remote_publication_plan_contract.py": 499,
    "rsi_pilot_exact_task_remote_state_observation_contract.py": 491,
    "rsi_pilot_exact_task_remote_publication_authorization_contract.py": 1000,
    "rsi_pilot_exact_task_remote_publication_transaction_contract.py": 2036,
    "rsi_pilot_exact_task_remote_publication_recovery_contract.py": 546,
    "rsi_pilot_exact_task_post_publication_attestation_contract.py": 1034,
    "rsi_pilot_exact_task_pr_lifecycle_authorization_contract.py": 1132,
    "rsi_pilot_exact_task_pr_lifecycle_transaction_contract.py": 749,
    "rsi_pilot_exact_task_pr_lifecycle_recovery_contract.py": 1061,
    "rsi_pilot_exact_task_post_lifecycle_attestation_contract.py": 1156,
    "rsi_pilot_exact_task_review_state_attestation_contract.py": 743,
    "rsi_pilot_exact_task_merge_readiness_evaluation_contract.py": 1052,
    "rsi_pilot_exact_task_merge_authorization_contract.py": 1171,
    "rsi_pilot_exact_task_merge_transaction_contract.py": 743,
    "rsi_pilot_exact_task_merge_recovery_contract.py": 1053,
    "rsi_pilot_exact_task_post_merge_attestation_contract.py": 2676,
    "rsi_pilot_exact_task_release_readiness_evaluation_contract.py": 742,
    "rsi_pilot_exact_task_release_plan_contract.py": 1049,
    "rsi_pilot_exact_task_release_state_observation_contract.py": 1156,
    "rsi_pilot_exact_task_release_authorization_contract.py": 727,
}
_SERIAL_PINNED = frozenset({
    "rsi_pilot_exact_task_remote_publication_transaction_contract.py",
    "rsi_pilot_exact_task_post_merge_attestation_contract.py",
})
_WORKERS_PER_SHARD = (2, 1, 2)


def balanced_midchain_shards(files) -> tuple[tuple[str, ...], ...]:
    canonical = tuple(files)
    if len(canonical) != len(set(canonical)) or set(canonical) != set(COST_SECONDS):
        raise AssertionError("Midchain cost evidence must match each canonical contract exactly")
    if len(_SERIAL_PINNED) != 2 or not _SERIAL_PINNED <= set(canonical):
        raise AssertionError("Midchain serial deep-contract pins invalid")
    if any(type(cost) not in (int, float) or not isfinite(cost) or cost <= 0
           for cost in COST_SECONDS.values()):
        raise AssertionError("Midchain contract costs must be positive finite seconds")

    groups: list[list[str]] = [[], [], []]
    # Projected worker-slot loads model two workers for 1/3 and 3/3,
    # while 2/3 keeps its existing hard-coded ONE worker and timeouts.
    loads = [[0.0] * workers for workers in _WORKERS_PER_SHARD]
    for filename in canonical:
        if filename in _SERIAL_PINNED:
            groups[1].append(filename)
            loads[1][0] += COST_SECONDS[filename]

    original_index = {filename: index for index, filename in enumerate(canonical)}
    for filename in sorted(
        (filename for filename in canonical if filename not in _SERIAL_PINNED),
        key=lambda f: (-COST_SECONDS[f], original_index[f]),
    ):
        cost = COST_SECONDS[filename]
        options = []
        for shard_index in range(3):
            for worker_index in range(_WORKERS_PER_SHARD[shard_index]):
                before = max(loads[shard_index])
                after = max(
                    value + cost if i == worker_index else value
                    for i, value in enumerate(loads[shard_index])
                )
                options.append((after, after - before, shard_index, worker_index))
        _, _, shard_index, worker_index = min(options)
        groups[shard_index].append(filename)
        loads[shard_index][worker_index] += cost

    result = tuple(
        tuple(filename for filename in canonical if filename in set(group))
        for group in groups
    )
    flattened = [filename for group in result for filename in group]
    if (len(flattened) != len(canonical) or set(flattened) != set(canonical)
            or any(not group for group in result)
            or not _SERIAL_PINNED <= set(result[1])):
        raise AssertionError("Midchain balanced plan must be complete, disjoint and safe")
    return result
