#!/usr/bin/env python3
"""Fast contract for deterministic Stage-B weighted shard planning."""
from __future__ import annotations

import ast
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

from stage_b_weighted_costs import (  # noqa: E402
    DOWNSTREAM_COST_SECONDS,
    MEASUREMENT_HEAD_SHA,
    MEASUREMENT_WORKFLOW_RUN_ID,
    MIDCHAIN_COST_SECONDS,
)
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

def _extract_contract_files(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_CONTRACT_FILES"
            for target in node.targets
        ):
            continue
        value = ast.literal_eval(node.value)
        assert isinstance(value, tuple)
        assert all(isinstance(item, str) for item in value)
        return value
    raise AssertionError(f"_CONTRACT_FILES not found in {path}")


def _loads(
    shards: tuple[tuple[str, ...], ...],
    costs: dict[str, float],
) -> tuple[float, ...]:
    return tuple(sum(costs[name] for name in shard) for shard in shards)


midchain_contracts = _extract_contract_files(
    SUPPORT / "rsi_pilot_exact_task_stage_b_midchain_driver.py"
)
downstream_contracts = _extract_contract_files(
    SUPPORT / "rsi_pilot_exact_task_release_transaction_contract.py"
)
assert set(MIDCHAIN_COST_SECONDS) == set(midchain_contracts)
assert set(DOWNSTREAM_COST_SECONDS) == set(downstream_contracts)

midchain_plan = weighted_shards(midchain_contracts, MIDCHAIN_COST_SECONDS, 3)
downstream_plan = weighted_shards(downstream_contracts, DOWNSTREAM_COST_SECONDS, 3)
midchain_loads = _loads(midchain_plan, MIDCHAIN_COST_SECONDS)
downstream_loads = _loads(downstream_plan, DOWNSTREAM_COST_SECONDS)

assert max(midchain_loads) - min(midchain_loads) < 200.0, midchain_loads
assert max(downstream_loads) - min(downstream_loads) < 500.0, downstream_loads
assert MEASUREMENT_WORKFLOW_RUN_ID == 35960087681
assert MEASUREMENT_HEAD_SHA == "c6c8ca2fa948270fd8beb49b362260bdbfb2c8be"

print("PASS: deterministic Stage-B weighted sharding primitive")
