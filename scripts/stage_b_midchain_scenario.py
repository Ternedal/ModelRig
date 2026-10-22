#!/usr/bin/env python3
"""Read-only what-if model for ModelRig Stage-B midchain scheduling.

Never runs Stage-B, edits a workflow, changes timeouts or qualifies a release.
Inputs are observed passing logs for one EXACT frozen main revision only.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import ast
import json
import math
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "support" / "rsi_pilot_exact_task_stage_b_midchain_driver.py"
COSTS = ROOT / "tests" / "support" / "stage_b_midchain_timings_20261009.json"
SOURCE_SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
GITHUB_JOBS = {"1": 113575752307, "2": 113575752249, "3": 113575752334}
# Immutable observed tenths of a second, by canonical _CONTRACT_FILES order.
# Transcribed from successful exact-head run 37845235363, jobs in GITHUB_JOBS.
# This is an evidence-integrity check, NOT a calibrated speedup or CI authority.
EXPECTED_OBSERVED_TENTHS = (
    3161, 3172, 1608, 3256, 6, 1614,
    3186, 3148, 1615, 3181, 3200, 1662,
    3312, 3450, 1902, 4166, 4982, 4123,
    11017, 20313, 4574, 11438, 11240, 6167,
    11788, 11585, 6109, 11649, 11630, 6201,
    11597, 26599, 6255, 11517, 11457, 6151,
)
# Current job shape, confirmed from the existing, qualified driver.
CAPACITIES = (2, 1, 2)


def canonical_contracts(driver_text: str) -> tuple[str, ...]:
    # Fail closed if the driver changes. This is a WHAT-IF model, not CI wiring.
    required = (
        "_CONTRACT_FILES[index - 1 :: total]",
        "_MAX_PARALLEL_CONTRACTS = 2",
        'if shard == "2/3":\n        return 1',
        "_REQUIRED_SHARD_COUNT = 3",
    )
    if not all(s in driver_text for s in required):
        raise ValueError("Stage-B source semantics changed; reassess the model")
    try:
        statements = ast.parse(driver_text).body
        assignments = [
            n for n in statements if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_CONTRACT_FILES" for t in n.targets)
        ]
        if len(assignments) != 1:
            raise ValueError("must find exactly one canonical contract tuple")
        names = ast.literal_eval(assignments[0].value)
    except (SyntaxError, ValueError, TypeError, MemoryError) as exc:
        raise ValueError("cannot statically parse canonical contracts") from exc
    if not isinstance(names, tuple) or len(names) != 36:
        raise ValueError("expected exactly 36 midchain contracts")
    if not all(isinstance(s, str) and s.endswith(".py") for s in names):
        raise ValueError("invalid contract file")
    if len(set(names)) != len(names):
        raise ValueError("duplicate canonical contract")
    return names


def measured_costs(data: dict, files: tuple[str, ...]) -> dict[str, float]:
    if not isinstance(data, dict) or data.get("schema") != "modelrig-stage-b-midchain-timings/v1":
        raise ValueError("wrong timing schema")
    if data.get("source_sha") != SOURCE_SHA or data.get("exact_head_run_id") != 37845235363:
        raise ValueError("timings not bound to successful frozen exact-head source")
    if data.get("github_jobs") != GITHUB_JOBS:
        raise ValueError("job identity mismatch")
    observations = data.get("contract_timings")
    if not isinstance(observations, list) or len(observations) != len(files):
        raise ValueError("wrong timing record count")
    if len(EXPECTED_OBSERVED_TENTHS) != len(files):
        raise ValueError("pinned observations no longer match canonical contract count")
    result = {}
    for row in observations:
        if not isinstance(row, dict) or set(row) != {"file", "elapsed_seconds", "source_job_id"}:
            raise ValueError("malformed timing observation")
        name, raw, job = row["file"], row["elapsed_seconds"], row["source_job_id"]
        if not isinstance(name, str) or name not in files or name in result:
            raise ValueError("missing/duplicate/stale midchain contract cost")
        if type(raw) not in (int, float) or not math.isfinite(raw) or raw <= 0:
            raise ValueError("timings must be positive finite seconds")
        canonical_index = files.index(name)
        if Decimal(str(raw)) * 10 != EXPECTED_OBSERVED_TENTHS[canonical_index]:
            raise ValueError("timing disagrees with pinned successful exact-head log observation")
        if job != GITHUB_JOBS[str(canonical_index % 3 + 1)]:
            raise ValueError("observation from wrong original shard")
        result[name] = float(raw)
    if set(result) != set(files):
        raise ValueError("timings must cover every contract exactly once")
    return result


def capacity_scenario(files: tuple[str, ...], costs: dict[str, float]) -> tuple[tuple[str, ...], ...]:
    """LPT style deterministic *proposal*, with serial shard 2 and two other workers."""
    order = {name: idx for idx, name in enumerate(files)}
    items = sorted(files, key=lambda x: (-costs[x], order[x]))
    groups = [[], [], []]
    sums = [0.0, 0.0, 0.0]
    for name in items:
        i = min(range(3), key=lambda j: (sums[j] / CAPACITIES[j], j))
        groups[i].append(name)
        sums[i] += costs[name]
    for group in groups:
        group.sort(key=order.__getitem__)
    flattened = [x for group in groups for x in group]
    if len(flattened) != len(files) or set(flattened) != set(files) or any(not group for group in groups):
        raise ValueError("scenario must assign every contract exactly once")
    return tuple(tuple(g) for g in groups)


def modeled_makespan(groups: tuple[tuple[str, ...], ...], costs: dict[str, float]) -> tuple[float, ...]:
    result = []
    for i, names in enumerate(groups):
        lanes = [0.0] * CAPACITIES[i]
        for name in names:
            lane = min(range(len(lanes)), key=lambda k: (lanes[k], k))
            lanes[lane] += costs[name]
        result.append(round(max(lanes), 1))
    return tuple(result)


def analyze(driver_text: str, data: dict) -> dict:
    files = canonical_contracts(driver_text)
    costs = measured_costs(data, files)
    current = tuple(tuple(files[i::3]) for i in range(3))
    proposal = capacity_scenario(files, costs)
    baseline = modeled_makespan(current, costs)
    estimate = modeled_makespan(proposal, costs)
    return {
        "schema": "modelrig-stage-b-midchain-what-if/v1",
        "source_sha": SOURCE_SHA,
        "exact_head_run_id": data["exact_head_run_id"],
        "observed_job_ids": GITHUB_JOBS,
        "contract_count": len(files),
        "original_modeled_makespan_seconds": list(baseline),
        "proposed_modeled_makespan_seconds": list(estimate),
        "original_modeled_critical_seconds": max(baseline),
        "proposed_modeled_critical_seconds": max(estimate),
        "suggested_groups": [list(group) for group in proposal],
        "modeled_only": True,
        "measured_improvement": False,
        "activation_authorized": False,
        "stage_b_driver_modified": False,
        "release_gate_satisfied": False,
        "production_activation": False,
        "warning": (
            "Projected job times are not predictive: moving nested/deep contracts "
            "changes parallel contention and their effective timeout budget. "
            "Use an isolated exact-head Stage-B experiment before altering CI."
        ),
    }


def main() -> int:
    output = analyze(
        DRIVER.read_text(encoding="utf-8"),
        json.loads(COSTS.read_text(encoding="utf-8")),
    )
    print(json.dumps(output, sort_keys=True, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
