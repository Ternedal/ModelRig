"""Offline coverage and safety invariants for experimental downstream sharding.

No physical probes, network calls, subprocess contract runs or gate assertions.
A green result only protects *coverage*; true speedup requires exact-head CI.
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
assert planner.REFERENCE_RUNS == (37845235363, 37942702263, 37982695916)
assert len(planner.REFERENCE_LOG_JOB_IDS) == 9
assert len(set(planner.REFERENCE_LOG_JOB_IDS)) == 9

plan = planner.balanced_downstream_shards(files)
assert plan == planner.balanced_downstream_shards(files)
assert tuple(len(group) for group in plan) == (10, 11, 10)
assert sorted(name for group in plan for name in group) == sorted(files)
assert any(
    group != tuple(files[i::3]) for i, group in enumerate(plan)
)
# Shards retain the existing two independent isolated child processes.
assert driver._MAX_SHARDED_PARALLEL_CONTRACTS == 2
assert driver._MAX_PARALLEL_CONTRACTS == 2
assert driver._PER_CONTRACT_TIMEOUT_SECONDS == 2400
assert driver._TARGETED_DEEP_TIMEOUT_SECONDS == 3600
assert len(driver._TARGETED_DEEP_TIMEOUT_CONTRACTS) == 10
assert driver._TARGETED_DEEP_TIMEOUT_CONTRACTS <= set(files)

for shard_index in range(1, 4):
    with patch.dict(os.environ, {driver._CONTRACT_SHARD_ENV: f"{shard_index}/3"}):
        assert driver._selected_contract_files() == plan[shard_index - 1]
        for name in plan[shard_index - 1]:
            budget = (3600 if name in driver._TARGETED_DEEP_TIMEOUT_CONTRACTS
                      else 2400)
            assert 0 < planner.COST_SECONDS[name] < budget

# The original full-chain, unsharded path must still execute all contracts.
with patch.dict(os.environ, {driver._CONTRACT_SHARD_ENV: ""}):
    assert driver._selected_contract_files() == files

# Projection must model actual ThreadPoolExecutor submission order instead of
# an independently assigned bin-pack whose worker order is never executed.
modeled = []
for group in plan:
    workers = [0, 0]
    for name in group:
        slot = 0 if workers[0] <= workers[1] else 1
        workers[slot] += planner.COST_SECONDS[name]
    modeled.append(max(workers))
assert max(modeled) < 9400, modeled

for invalid in ("0/3", "4/3", "1/2", "random"):
    with patch.dict(os.environ, {driver._CONTRACT_SHARD_ENV: invalid}):
        try:
            driver._selected_contract_files()
        except AssertionError:
            pass
        else:
            raise AssertionError(f"invalid Stage-B downstream shard accepted: {invalid}")

for corrupt in (files[:-1], files + (files[0],),
                files[:-1] + ("unknown_contract.py",)):
    try:
        planner.balanced_downstream_shards(corrupt)
    except AssertionError:
        pass
    else:
        raise AssertionError("downstream planner lost its complete-coverage guard")

with patch.dict(planner.COST_SECONDS, {files[0]: 0}):
    try:
        planner.balanced_downstream_shards(files)
    except AssertionError:
        pass
    else:
        raise AssertionError("invalid measured downstream cost was accepted")

print(f"Stage-B downstream plan: {len(files)} contracts exactly once; "
      f"predicted worker makespans {modeled}; NOT an empirical speedup")
