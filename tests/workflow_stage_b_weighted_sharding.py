#!/usr/bin/env python3
"""Fast contract for deterministic Stage-B weighted shard planning."""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

from stage_b_weighted_sharding import weighted_shards  # noqa: E402


def expect_failure(fn, message: str) -> None:
    try:
        fn()
    except AssertionError:
        return
    raise AssertionError(message)


contracts = ("a.py", "b.py", "c.py", "d.py", "e.py", "f.py")
balanced_costs = {
    "a.py": 9,
    "b.py": 8,
    "c.py": 7,
    "d.py": 6,
    "e.py": 5,
    "f.py": 4,
}
expected = (
    ("a.py", "f.py"),
    ("b.py", "e.py"),
    ("c.py", "d.py"),
)
plan = weighted_shards(contracts, balanced_costs, 3)
assert plan == expected, plan
assert weighted_shards(contracts, balanced_costs, 3) == plan
assert sorted(filename for shard in plan for filename in shard) == sorted(contracts)

tie_costs = {filename: 1 for filename in contracts}
assert weighted_shards(contracts, tie_costs, 3) == (
    ("a.py", "d.py"),
    ("b.py", "e.py"),
    ("c.py", "f.py"),
)

expect_failure(
    lambda: weighted_shards(
        contracts,
        {k: v for k, v in balanced_costs.items() if k != "f.py"},
        3,
    ),
    "missing cost must fail closed",
)
expect_failure(
    lambda: weighted_shards(contracts, {**balanced_costs, "stale.py": 1}, 3),
    "stale cost must fail closed",
)
expect_failure(
    lambda: weighted_shards(
        ("a.py", "a.py", "b.py"),
        {"a.py": 1, "b.py": 1},
        2,
    ),
    "duplicate contracts must fail closed",
)
expect_failure(
    lambda: weighted_shards(("a.py",), {"a.py": 0}, 1),
    "zero cost must fail closed",
)
expect_failure(
    lambda: weighted_shards(("a.py",), {"a.py": math.inf}, 1),
    "non-finite cost must fail closed",
)
expect_failure(
    lambda: weighted_shards(("a.py",), {"a.py": True}, 1),
    "boolean cost must fail closed",
)
expect_failure(
    lambda: weighted_shards(("a.py",), {"a.py": 1}, 2),
    "empty shards must not be representable",
)

print("PASS: deterministic Stage-B weighted sharding primitive")


# Experimental measured midchain plan: source-bound static costs, no omitted/
# duplicate contracts, deterministic membership, preserved serial deep shard.
import os
from unittest.mock import patch
from stage_b_midchain_balancing import (
    MIDCHAIN_SECONDS, MEASURED_MAIN_SHA, MEASUREMENT_RUN_ID,
    SERIAL_DEEP_CONTRACTS, measured_midchain_shards,
)
from rsi_pilot_exact_task_stage_b_midchain_driver import (
    _CONTRACT_FILES as MIDCHAIN_CONTRACTS,
    _selected_contract_files,
    _worker_count,
    _contract_timeout_seconds,
)

assert MEASUREMENT_RUN_ID == 37845235363
assert MEASURED_MAIN_SHA == "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
assert len(MIDCHAIN_CONTRACTS) == 36
proposal = measured_midchain_shards(MIDCHAIN_CONTRACTS)
assert proposal == measured_midchain_shards(MIDCHAIN_CONTRACTS)
assert sorted(f for group in proposal for f in group) == sorted(MIDCHAIN_CONTRACTS)
assert len(set(f for group in proposal for f in group)) == len(MIDCHAIN_CONTRACTS)
assert SERIAL_DEEP_CONTRACTS.issubset(proposal[1])
assert not (SERIAL_DEEP_CONTRACTS & set(proposal[0]))
assert not (SERIAL_DEEP_CONTRACTS & set(proposal[2]))
for index in (1, 2, 3):
    with patch.dict(os.environ, {"MODELRIG_STAGE_B_CONTRACT_SHARD": f"{index}/3"}):
        assert _selected_contract_files() == proposal[index - 1]
        assert _worker_count(len(proposal[index - 1])) == (1 if index == 2 else 2)
        for filename in proposal[index - 1]:
            if filename in SERIAL_DEEP_CONTRACTS:
                assert _contract_timeout_seconds(filename) >= 2400
with patch.dict(os.environ, {"MODELRIG_STAGE_B_CONTRACT_SHARD": ""}):
    assert _selected_contract_files() == MIDCHAIN_CONTRACTS
expect_failure(lambda: measured_midchain_shards(
    MIDCHAIN_CONTRACTS, {name: cost for name, cost in MIDCHAIN_SECONDS.items()
                         if name != MIDCHAIN_CONTRACTS[0]}),
    "missing measured contract cost must fail closed")
expect_failure(lambda: measured_midchain_shards(
    MIDCHAIN_CONTRACTS, {**MIDCHAIN_SECONDS, "stale.py": 15.0}),
    "unreviewed/stale measured contract cost must fail closed")
expect_failure(lambda: measured_midchain_shards(
    MIDCHAIN_CONTRACTS, {**MIDCHAIN_SECONDS,
                         next(iter(SERIAL_DEEP_CONTRACTS)): 0.1}),
    "deep-serial contract cannot silently become parallel")
expect_failure(lambda: measured_midchain_shards(
    MIDCHAIN_CONTRACTS, {**MIDCHAIN_SECONDS, MIDCHAIN_CONTRACTS[0]: 2000.0}),
    "new >1800s contract cannot silently enter parallel/default-1800s shard")
print("PASS: measured exact-main-head Stage-B midchain coverage + serial safety")
