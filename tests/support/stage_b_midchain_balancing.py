"""Fail-closed, measured Stage-B midchain partition (experiment, not V1 authority).

Values are per-contract elapsed seconds from the successful, source-pinned
ModelRig main exact-head qualification run 37845235363 (2026-10-09), jobs:
midchain-1 113575752307, midchain-2 113575752249,
midchain-3 113575752334. One observation, NOT guaranteed future runtimes.

Keep the two >1800s deep nested contracts alone in serial shard 2. Other
contract costs are greedily packed onto the estimated currently least-busy
worker slot in shards 1 and 3, with exact filename/contract-order ties.
Every original subprocess and timeout remains owned by the existing driver.
"""
from __future__ import annotations

from stage_b_weighted_sharding import weighted_shards

MEASUREMENT_RUN_ID = 37845235363
MEASURED_MAIN_SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
MIDCHAIN_SECONDS = {
    "rsi_pilot_exact_task_execution_plan_requirements_contract.py": 316.1,
    "rsi_pilot_exact_task_development_task_binding_contract.py": 317.2,
    "rsi_pilot_exact_task_development_task_binding_live_provenance_contract.py": 160.8,
    "rsi_pilot_exact_task_executor_capability_live_guard_contract.py": 325.6,
    "rsi_pilot_exact_task_executor_secret_custody_contract.py": 0.6,
    "rsi_pilot_exact_task_executor_capability_semantics_contract.py": 161.4,
    "rsi_pilot_exact_task_execution_plan_contract.py": 318.6,
    "rsi_pilot_exact_task_prelaunch_reservation_contract.py": 314.8,
    "rsi_pilot_exact_task_execution_transaction_contract.py": 161.5,
    "rsi_pilot_exact_task_post_execution_evaluation_contract.py": 318.1,
    "rsi_pilot_exact_task_local_commit_plan_contract.py": 320.0,
    "rsi_pilot_exact_task_local_commit_object_identity_contract.py": 166.2,
    "rsi_pilot_exact_task_local_commit_write_authorization_contract.py": 331.2,
    "rsi_pilot_exact_task_local_commit_transaction_contract.py": 345.0,
    "rsi_pilot_exact_task_post_commit_integration_evaluation_contract.py": 190.2,
    "rsi_pilot_exact_task_integration_readiness_contract.py": 416.6,
    "rsi_pilot_exact_task_remote_publication_plan_contract.py": 498.2,
    "rsi_pilot_exact_task_remote_state_observation_contract.py": 412.3,
    "rsi_pilot_exact_task_remote_publication_authorization_contract.py": 1101.7,
    "rsi_pilot_exact_task_remote_publication_transaction_contract.py": 2031.3,
    "rsi_pilot_exact_task_remote_publication_recovery_contract.py": 457.4,
    "rsi_pilot_exact_task_post_publication_attestation_contract.py": 1143.8,
    "rsi_pilot_exact_task_pr_lifecycle_authorization_contract.py": 1124.0,
    "rsi_pilot_exact_task_pr_lifecycle_transaction_contract.py": 616.7,
    "rsi_pilot_exact_task_pr_lifecycle_recovery_contract.py": 1178.8,
    "rsi_pilot_exact_task_post_lifecycle_attestation_contract.py": 1158.5,
    "rsi_pilot_exact_task_review_state_attestation_contract.py": 610.9,
    "rsi_pilot_exact_task_merge_readiness_evaluation_contract.py": 1164.9,
    "rsi_pilot_exact_task_merge_authorization_contract.py": 1163.0,
    "rsi_pilot_exact_task_merge_transaction_contract.py": 620.1,
    "rsi_pilot_exact_task_merge_recovery_contract.py": 1159.7,
    "rsi_pilot_exact_task_post_merge_attestation_contract.py": 2659.9,
    "rsi_pilot_exact_task_release_readiness_evaluation_contract.py": 625.5,
    "rsi_pilot_exact_task_release_plan_contract.py": 1151.7,
    "rsi_pilot_exact_task_release_state_observation_contract.py": 1145.7,
    "rsi_pilot_exact_task_release_authorization_contract.py": 615.1,
}
# These two measured >1800s. Shard 2 uses one worker and a 2400s default,
# plus the existing targeted 3600s post-merge bound. Do not move either
# into a parallel/default-1800s shard by an automated heuristic.
SERIAL_DEEP_CONTRACTS = frozenset({
    "rsi_pilot_exact_task_remote_publication_transaction_contract.py",
    "rsi_pilot_exact_task_post_merge_attestation_contract.py",
})
WORKER_SLOTS = (2, 1, 2)


def measured_midchain_shards(
    contract_files: tuple[str, ...],
    costs: dict[str, float] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    files = tuple(contract_files)
    measured = MIDCHAIN_SECONDS if costs is None else costs
    # The existing pure weighted primitive performs strict uniqueness, range,
    # finite/positive-cost and exact-file-key coverage checks. Use its proven
    # validation but not its homogeneous one-slot scheduling policy.
    weighted_shards(files, measured, len(WORKER_SLOTS))
    if not SERIAL_DEEP_CONTRACTS.issubset(files):
        raise AssertionError("Stage-B required deep serial contracts missing")
    if any(measured[name] <= 1800 for name in SERIAL_DEEP_CONTRACTS):
        raise AssertionError("Stage-B pinned serial contract costs changed unexpectedly")

    by_index = {name: i for i, name in enumerate(files)}
    members = [[], [], []]
    workers = [[0.0, 0.0], [0.0], [0.0, 0.0]]
    for name in sorted(SERIAL_DEEP_CONTRACTS, key=by_index.__getitem__):
        members[1].append(name)
        workers[1][0] += float(measured[name])

    for name in sorted(
        (name for name in files if name not in SERIAL_DEEP_CONTRACTS),
        key=lambda value: (-float(measured[value]), by_index[value]),
    ):
        # Predict the makespan if each candidate shard schedules the contract
        # on its least-loaded worker, without creating any actual worker here.
        candidates = []
        for shard_index, load_slots in enumerate(workers):
            least = min(range(len(load_slots)), key=lambda i: (load_slots[i], i))
            predicted = max(
                max(load_slots), load_slots[least] + float(measured[name]))
            candidates.append((predicted, shard_index, least))
        _predicted, shard_index, worker_index = min(candidates)
        members[shard_index].append(name)
        workers[shard_index][worker_index] += float(measured[name])

    for group in members:
        group.sort(key=by_index.__getitem__)
    flattened = [name for group in members for name in group]
    if len(flattened) != len(files) or set(flattened) != set(files):
        raise AssertionError("Stage-B midchain must run every canonical contract once")
    if any(not group for group in members):
        raise AssertionError("Stage-B midchain produced an empty shard")
    if any(name in members[0] or name in members[2] for name in SERIAL_DEEP_CONTRACTS):
        raise AssertionError("Stage-B deep contracts must remain serial on shard 2")
    return tuple(tuple(group) for group in members)  # type: ignore[return-value]
