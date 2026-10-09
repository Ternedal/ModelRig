"""Fast regression test: Stage-B midchain weights must never lose a contract."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

SUPPORT = Path(__file__).resolve().parent / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
import rsi_pilot_exact_task_stage_b_midchain_driver as driver  # noqa: E402
from stage_b_midchain_plan import (  # noqa: E402
    COST_SECONDS, REFERENCE_MAIN_SHA, REFERENCE_RUNS,
    _SERIAL_PINNED, balanced_midchain_shards,
)

files = driver._CONTRACT_FILES
assert REFERENCE_MAIN_SHA == "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
assert REFERENCE_RUNS == (37845235363, 37942702263)
assert len(files) == 36 and len(set(files)) == 36
plan = balanced_midchain_shards(files)
assert plan == balanced_midchain_shards(files)  # deterministic
assert sorted(f for group in plan for f in group) == sorted(files)  # exhaustive
assert _SERIAL_PINNED <= set(plan[1])
assert tuple(len(group) for group in plan) == (16, 4, 16)
# Regression: the execution order is the cost-planned sequence. Re-sorting
# each shard to source order after scheduling would invalidate modeled loads.
assert any(tuple(sorted(group, key=files.index)) != group for group in plan)
# Exactly two deep >1800s contracts are pinned to the serial 2400s shard.
assert all(COST_SECONDS[name] < driver._PER_CONTRACT_TIMEOUT_SECONDS for
           name in plan[0] + plan[2])
assert sum(COST_SECONDS[f] for f in plan[1]) < 5500
for n in (1, 2, 3):
    with patch.dict(os.environ, {driver._CONTRACT_SHARD_ENV: f"{n}/3"}):
        assert driver._selected_contract_files() == plan[n - 1]
        with patch.object(driver.os, "cpu_count", return_value=2):
            assert driver._worker_count(len(plan[n - 1])) == (1 if n == 2 else 2)
        assert driver._contract_timeout_seconds() == (2400 if n == 2 else 1800)
assert driver._contract_timeout_seconds(
    "rsi_pilot_exact_task_post_merge_attestation_contract.py"
) == driver._TARGETED_DEEP_TIMEOUT_SECONDS == 3600

for invalid in ("0/3", "4/3", "1/2", "wrong"):
    with patch.dict(os.environ, {driver._CONTRACT_SHARD_ENV: invalid}):
        try:
            driver._selected_contract_files()
        except AssertionError:
            pass
        else:
            raise AssertionError("invalid shard spec accepted")
for mutated in (files[:-1], files + (files[0],),
                files[:-1] + ("unknown_contract.py",)):
    try:
        balanced_midchain_shards(mutated)
    except AssertionError:
        pass
    else:
        raise AssertionError("contract coverage drift accepted")

# This test is pure; it must not invoke any costly subprocess or actual Stage-B.
print("Stage-B experimental measured midchain shard partition PASS")
