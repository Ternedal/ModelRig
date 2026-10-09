"""Regression guard for static, traceable Stage-B capacity scenario."""
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage_b_midchain_scenario.py"
SPEC = importlib.util.spec_from_file_location("stage_b_midchain_scenario", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
driver_text = module.DRIVER.read_text(encoding="utf-8")
data = json.loads(module.COSTS.read_text(encoding="utf-8"))
files = module.canonical_contracts(driver_text)
assert len(files) == 36
plan = module.analyze(driver_text, data)
assert plan == module.analyze(driver_text, data), "scenario must be deterministic"
assert plan["contract_count"] == 36
assert plan["original_modeled_critical_seconds"] > 11000
assert plan["proposed_modeled_critical_seconds"] < plan["original_modeled_critical_seconds"]
flat = sum(plan["suggested_groups"], [])
assert len(flat) == 36 and set(flat) == set(files)
assert all(group for group in plan["suggested_groups"])
for key in ("activation_authorized", "measured_improvement", "stage_b_driver_modified", "release_gate_satisfied", "production_activation"):
    assert plan[key] is False
assert plan["modeled_only"] is True
assert plan["source_sha"] == module.SOURCE_SHA
assert "isolated exact-head" in plan["warning"]

def fails(fixture, source=driver_text):
    try:
        module.analyze(source, fixture)
    except ValueError:
        return
    raise AssertionError("tampered/unverified timing was accepted")

corrupt = deepcopy(data)
corrupt["contract_timings"].pop()
fails(corrupt)
corrupt = deepcopy(data)
corrupt["contract_timings"][-1] = corrupt["contract_timings"][0]
fails(corrupt)
corrupt = deepcopy(data)
corrupt["source_sha"] = "f" * 40
fails(corrupt)
corrupt = deepcopy(data)
corrupt["github_jobs"]["2"] = 999999999
fails(corrupt)
corrupt = deepcopy(data)
corrupt["contract_timings"][0]["elapsed_seconds"] = 0
fails(corrupt)
corrupt = deepcopy(data)
corrupt["contract_timings"][0]["elapsed_seconds"] = True
fails(corrupt)
corrupt = deepcopy(data)
corrupt["contract_timings"][0]["source_job_id"] = module.GITHUB_JOBS["2"]
fails(corrupt)
fails(data, driver_text.replace("_CONTRACT_FILES[index - 1 :: total]", "ignored = []"))
assert "_CONTRACT_FILES[index - 1 :: total]" in driver_text
# The scenario must not become silent CI authority.
assert "subprocess.run" not in SCRIPT.read_text(encoding="utf-8")
assert "_selected_contract_files()" in driver_text
print("PASS: offline Stage-B observed-cost scenario, coverage and falsification tests")
