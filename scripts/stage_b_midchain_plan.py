#!/usr/bin/env python3
"""Offline Stage-B midchain cost planner; DOES NOT change test execution."""
from __future__ import annotations
import ast
import json
import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests/support/rsi_pilot_exact_task_stage_b_midchain_driver.py"
EVIDENCE = ROOT / "tests/support/stage_b_midchain_measured_costs_20261009.json"
SCHEMA = "kaliv-stage-b-midchain-measured-costs/v1"
SOURCE_SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
# Driver serializes shard 2/3, shards 1/3 and 3/3 use two workers.
LANES = (2, 1, 2)
# Do not move observed >1800s contracts into the 1800s ordinary-shard bound.
ORDINARY_TIMEOUT = 1800


def driver_contracts(source: str) -> tuple[str, ...]:
    """Extract only the trusted literal contract list; never execute driver code."""
    module = ast.parse(source)
    values = [
        ast.literal_eval(node.value)
        for node in module.body if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_CONTRACT_FILES"
                for t in node.targets)
    ]
    if len(values) != 1 or not isinstance(values[0], tuple):
        raise ValueError("driver must have exactly one literal contract tuple")
    names = values[0]
    if not names or len(names) != len(set(names)) or not all(
        isinstance(name, str) and name.endswith(".py") for name in names
    ):
        raise ValueError("invalid or duplicated driver contracts")
    return names


def validated_costs(payload: dict, contracts: tuple[str, ...]) -> dict[str, float]:
    if payload.get("schema") != SCHEMA or payload.get("git_sha") != SOURCE_SHA:
        raise ValueError("wrong measurement provenance or schema")
    if (payload.get("workflow_run_id") != 37845235363
            or payload.get("completed_workflow_conclusion") != "success"):
        raise ValueError("measurement must come from the pinned successful run")
    raw = payload.get("cost_seconds")
    if not isinstance(raw, dict) or set(raw) != set(contracts):
        raise ValueError("measured contracts must match canonical driver exactly")
    costs = {}
    for name in contracts:
        value = raw[name]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("contract costs must be positive finite numbers")
        costs[name] = float(value)
    return costs


def lane_load(contracts: tuple[str, ...], costs: dict[str, float], workers: int) -> list[float]:
    """Optimistic two-worker list-scheduling estimate, never an actual runtime."""
    bins = [0.0] * workers
    for name in contracts:
        idx = min(range(workers), key=lambda j: (bins[j], j))
        bins[idx] += costs[name]
    return bins


def proposal(contracts: tuple[str, ...], costs: dict[str, float]) -> dict:
    # Deterministic descending costs, stable canonical order for ties.
    idx = {name: i for i, name in enumerate(contracts)}
    ordered = sorted(contracts, key=lambda n: (-costs[n], idx[n]))
    members: list[list[str]] = [[], [], []]
    bins = [[0.0] * workers for workers in LANES]

    for name in ordered:
        # Keep deep contracts in the existing serial/deep-bound shard; changing
        # that per-file timeout requires a separately reviewed change.
        available = (1,) if costs[name] > ORDINARY_TIMEOUT else (0, 1, 2)
        ranking = []
        for destination in available:
            trial = [list(b) for b in bins]
            lane = min(range(len(trial[destination])),
                       key=lambda j: (trial[destination][j], j))
            trial[destination][lane] += costs[name]
            ranking.append((
                max(max(b) for b in trial),
                max(trial[destination]), destination, lane,
            ))
        _, _, dest, lane = min(ranking)
        members[dest].append(name)
        bins[dest][lane] += costs[name]

    for shard in members:
        shard.sort(key=idx.__getitem__)
    assigned = [name for shard in members for name in shard]
    if len(assigned) != len(contracts) or set(assigned) != set(contracts):
        raise ValueError("candidate shard plan lost or duplicated contracts")
    if any(not shard for shard in members):
        raise ValueError("candidate shard plan has empty shard")
    if any(costs[name] > ORDINARY_TIMEOUT for shard in (members[0], members[2])
           for name in shard):
        raise ValueError("deep contract would move to a lower-timeout shard")
    return {
        "experimental": True,
        "no_execution_change": True,
        "production_activation": False,
        "source_sha": SOURCE_SHA,
        "source_run": 37845235363,
        "observed_actual_driver_seconds": [4520.7, 11078.2, 2591.8],
        "current_strided_estimated_max_seconds": max(
            max(lane_load(contracts[i::3], costs, LANES[i]))
            for i in range(3)
        ),
        "proposed_estimated_max_seconds": max(max(b) for b in bins),
        "proposed_shards": [
            {"shard": i+1, "lanes": LANES[i], "contracts": members[i],
             "estimated_lane_seconds": bins[i]} for i in range(3)
        ],
        "caveat": "This is a model, not a benchmark. Moving CPU-heavy contracts can alter their timings. No workflow or timeout changes; test exact-head independently before any execution change.",
    }


def main() -> int:
    try:
        canonical = driver_contracts(DRIVER.read_text(encoding="utf-8"))
        raw = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        result = proposal(canonical, validated_costs(raw, canonical))
    except (ValueError, OSError, SyntaxError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
