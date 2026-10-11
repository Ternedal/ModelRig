"""Pure offline guard for five-run measured Stage-B downstream reassignment.

No physical contract or production evidence is executed or synthesized here.
The actual immutable-head Stage-B GitHub workflow MUST run all real tests.
"""
from __future__ import annotations

import math
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
    37982695916, 38081640622, 38081628439, 38089952531, 38089960759
)
assert len(planner.REFERENCE_LOG_JOB_IDS) == (
    len(set(planner.REFERENCE_LOG_JOB_IDS))
) == 15
assert set(planner.COST_SECONDS) == set(files)
assert planner.COST_SECONDS[
    "rsi_pilot_exact_task_post_release_attestation_contract.py"
] == 3225
assert planner.COST_SECONDS[
    "rsi_pilot_exact_task_staging_success_status_recovery_contract.py"
] == 2639

plan = planner.balanced_downstream_shards(files)
assert plan == planner.balanced_downstream_shards(files)
assert len(plan) == 3
assert tuple(map(len, plan)) == (10, 10, 11)
assert len(set(name for group in plan for name in group)) == 31
assert sorted(name for group in plan for name in group) == sorted(files)
assert plan != tuple(tuple(files[i::3]) for i in range(3))

# Original hard limits and process isolation remain unchanged.
assert driver._REQUIRED_SHARD_COUNT == 3
assert driver._MAX_SHARDED_PARALLEL_CONTRACTS == 2
assert driver._MAX_PARALLEL_CONTRACTS == 2
assert driver._PER_CONTRACT_TIMEOUT_SECONDS == 2400
assert driver._TARGETED_DEEP_TIMEOUT_SECONDS == 3600
assert len(driver._TARGETED_DEEP_TIMEOUT_CONTRACTS) == 10
assert driver._TARGETED_DEEP_TIMEOUT_CONTRACTS <= set(files)

for n in range(1, 4):
    with patch.dict(os.environ, {driver._CONTRACT_SHARD_ENV: f"{n}/3"}):
        assert driver._selected_contract_files() == plan[n - 1]

for name in files:
    budget = (
        3600 if name in driver._TARGETED_DEEP_TIMEOUT_CONTRACTS else 2400
    )
    assert 0 < planner.COST_SECONDS[name] < budget

# No replacement of the full unsharded and original canonical path.
with patch.dict(os.environ, {driver._CONTRACT_SHARD_ENV: ""}):
    assert driver._selected_contract_files() == files
for bad in ("0/3", "4/3", "1/2", "1/6", "random", "1/0"):
    with patch.dict(os.environ, {driver._CONTRACT_SHARD_ENV: bad}):
        try:
            driver._selected_contract_files()
        except AssertionError:
            pass
        else:
            raise AssertionError(f"invalid shard accepted: {bad}")

for corrupt in (
    files[:-1],
    files + (files[0],),
    files[:-1] + ("rsi_pilot_exact_task_unrecognized.py",),
):
    try:
        planner.balanced_downstream_shards(corrupt)
    except AssertionError:
        pass
    else:
        raise AssertionError("unsafe contract coverage was accepted")

for invalid in (0, -1, float("inf"), float("nan"), True):
    with patch.dict(planner.COST_SECONDS, {files[0]: invalid}):
        try:
            planner.balanced_downstream_shards(files)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"invalid cost was accepted: {invalid}")

predictions = []
for group in plan:
    worker_loads = [0, 0]
    for name in group:
        slot = 0 if worker_loads[0] <= worker_loads[1] else 1
        worker_loads[slot] += planner.COST_SECONDS[name]
    predictions.append(max(worker_loads))
assert predictions == [8746, 8343, 8975], predictions
assert all(math.isfinite(v) and v > 0 for v in predictions)
print(f"Stage-B robust plan: 31 original contracts; modeled maxima {predictions}; "
      "measured speedup NOT YET PROVEN")
