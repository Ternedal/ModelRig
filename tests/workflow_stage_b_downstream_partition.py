"""Fail-closed deterministic coverage checks for experimental 7-run cost sharding.

This test never performs, stubs, authorizes or bypasses canonical contracts.
Only complete real exact-head CI can qualify run-time security and performance.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

SUPPORT = Path(__file__).resolve().parent / "support"
sys.path.insert(0, str(SUPPORT))
import rsi_pilot_exact_task_release_transaction_contract as driver  # noqa: E402
import stage_b_downstream_plan as planner  # noqa: E402

files = driver._CONTRACT_FILES
assert len(files) == len(set(files)) == 31
assert planner.REFERENCE_FROZEN_MAIN_SHA == (
    "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
)
assert planner.REFERENCE_RUNS == (
    37845235363, 37942702263, 37982695916, 38036507743,
    38048149969, 38089952531, 38089960759,
)
assert len(planner.REFERENCE_LOG_JOB_IDS) == 21
assert len(set(planner.REFERENCE_LOG_JOB_IDS)) == 21
assert set(planner.COST_SECONDS) == set(files)
assert planner.COST_SECONDS[
    "rsi_pilot_exact_task_post_release_attestation_contract.py"
] == 3115

plan = planner.balanced_downstream_shards(files)
assert plan == planner.balanced_downstream_shards(files)
assert tuple(len(group) for group in plan) == (11, 10, 10)
assert sorted(name for group in plan for name in group) == sorted(files)
assert all(len(group) >= 1 for group in plan)
assert any(group != tuple(files[i::3]) for i, group in enumerate(plan))

assert driver._REQUIRED_SHARD_COUNT == 3
assert driver._MAX_SHARDED_PARALLEL_CONTRACTS == 2
assert driver._MAX_PARALLEL_CONTRACTS == 2
assert driver._PER_CONTRACT_TIMEOUT_SECONDS == 2400
assert driver._TARGETED_DEEP_TIMEOUT_SECONDS == 3600
assert len(driver._TARGETED_DEEP_TIMEOUT_CONTRACTS) == 10
assert driver._TARGETED_DEEP_TIMEOUT_CONTRACTS <= set(files)

for i in range(1, 4):
    with patch.dict(os.environ, {driver._CONTRACT_SHARD_ENV: f"{i}/3"}):
        assert driver._selected_contract_files() == plan[i - 1]
        for name in plan[i - 1]:
            limit = (3600 if name in driver._TARGETED_DEEP_TIMEOUT_CONTRACTS
                     else 2400)
            assert 0 < planner.COST_SECONDS[name] < limit

with patch.dict(os.environ, {driver._CONTRACT_SHARD_ENV: ""}):
    assert driver._selected_contract_files() == files

predicted = []
for group in plan:
    workers = [0, 0]
    for name in group:
        slot = 0 if workers[0] <= workers[1] else 1
        workers[slot] += planner.COST_SECONDS[name]
    predicted.append(max(workers))
assert predicted == [8848, 8196, 8231], predicted

for invalid in ("0/3", "4/3", "1/2", "garbage"):
    with patch.dict(os.environ, {driver._CONTRACT_SHARD_ENV: invalid}):
        try:
            driver._selected_contract_files()
        except AssertionError:
            pass
        else:
            raise AssertionError(f"invalid downstream shard accepted: {invalid}")

for missing in (files[:-1], files + (files[0],), files[:-1] + ("wrong.py",)):
    try:
        planner.balanced_downstream_shards(missing)
    except AssertionError:
        pass
    else:
        raise AssertionError("downstream planner accepted lost/duplicate contract")

for bad in (0, -1, float("nan"), float("inf"), None):
    with patch.dict(planner.COST_SECONDS, {files[0]: bad}):
        try:
            planner.balanced_downstream_shards(files)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"downstream planner accepted invalid cost {bad!r}")

print("Downstream 31 canonical contracts, seven-run source, 3x2 isolated safety invariants PASS")
