"""Fast contract tests for observation-only Stage-B cost planning."""
from __future__ import annotations
import copy
import json
import sys
from pathlib import Path
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import stage_b_midchain_plan as plan  # noqa: E402

names = plan.driver_contracts(plan.DRIVER.read_text(encoding="utf-8"))
data = json.loads(plan.EVIDENCE.read_text(encoding="utf-8"))
costs = plan.validated_costs(data, names)
assert len(names) == 36
assert len(costs) == 36
actual = plan.proposal(names, costs)
assert actual == plan.proposal(names, costs), "nondeterministic proposal"
assignments = actual["proposed_shards"]
assert sorted(name for shard in assignments for name in shard["contracts"]) == sorted(names)
assert all(shard["contracts"] for shard in assignments)
assert assignments[1]["lanes"] == 1
assert {n for n in names if costs[n] > plan.ORDINARY_TIMEOUT}.issubset(
    set(assignments[1]["contracts"])
)
assert actual["no_execution_change"] is True
assert actual["experimental"] is True
assert actual["production_activation"] is False
assert actual["proposed_estimated_max_seconds"] < actual["current_strided_estimated_max_seconds"]
assert actual["observed_actual_driver_seconds"] == [4520.7, 11078.2, 2591.8]

def rejects(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("fail-closed cost input unexpectedly accepted")

missing = copy.deepcopy(data)
missing["cost_seconds"].pop(names[0])
rejects(lambda: plan.validated_costs(missing, names))
extra = copy.deepcopy(data)
extra["cost_seconds"]["stale.py"] = 100
rejects(lambda: plan.validated_costs(extra, names))
wrong_ref = copy.deepcopy(data)
wrong_ref["git_sha"] = "f" * 40
rejects(lambda: plan.validated_costs(wrong_ref, names))
wrong_run = copy.deepcopy(data)
wrong_run["workflow_run_id"] += 1
rejects(lambda: plan.validated_costs(wrong_run, names))
for value in (0, -2, "44", float("inf"), True):
    bad = copy.deepcopy(data)
    bad["cost_seconds"][names[0]] = value
    rejects(lambda: plan.validated_costs(bad, names))
rejects(lambda: plan.driver_contracts("_CONTRACT_FILES = ('a.py', 'a.py')"))
# Actual Stage-B execution remains the originally green three-way striding.
# This analysis does not claim that a proposed mapping has been run or qualified.
driver = plan.DRIVER.read_text(encoding="utf-8")
assert "_CONTRACT_FILES[index - 1 :: total]" in driver
print("PASS: isolated Stage-B measured cost planning, no runtime changes")
