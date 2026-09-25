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
