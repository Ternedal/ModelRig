#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent3_termination_ui_physical_report.py"
spec = importlib.util.spec_from_file_location("t023_physical_report", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)

NOW = datetime(2026, 7, 27, 18, 0, tzinfo=timezone.utc)
IDENTITY = {
    "version": "1.58.146",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "identity_source": "git",
    "version_stamps_consistent": True,
    "working_tree_clean": True,
}
INVENTORY = {
    "none": ["tool:rig_status"],
    "cooperative": ["tool:pull_model"],
    "runtime": [],
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_baseline(root: Path, *, inventory=None):
    inventory = copy.deepcopy(inventory or INVENTORY)
    value = module.prepare_observations(
        operator="Anders",
        identity=IDENTITY,
        inventory=inventory,
        now=NOW,
    )
    for platform, platform_value in value["platforms"].items():
        platform_value["device_name"] = f"{platform}-device"
        platform_value["os_version"] = "test-os"
        for case in platform_value["cases"]:
            name = case["name"]
            receipt = case["receipt"]
            plan = receipt["plan"]
            plan.update(
                {
                    "state_before": "available",
                    "can_request_before": True,
                    "effect_before": (
                        "prevent_future_steps"
                        if name == "runtime_bound"
                        else "prevent_future_steps_active_tool_continues"
                    ),
                    "state_after": "terminal",
                    "can_request_after": False,
                }
            )
            receipt["model_stream"].update(
                {
                    "state": "not_active",
                    "active": False,
                    "handle_present": False,
                    "can_request": False,
                }
            )
            active = receipt["active_tool"]
            active.update(
                {
                    "tool": (
                        "tool:pull_model"
                        if name == "cooperative_declaration"
                        else (
                            "tool:runtime_demo"
                            if name == "runtime_bound"
                            else "tool:rig_status"
                        )
                    ),
                    "state_before": "executing",
                    "state_after": (
                        "completed_after_cancel"
                        if name == "late_completion"
                        else "cancelled"
                    ),
                    "reason": "physically observed",
                    "request_state_after": "terminal",
                }
            )
            if name == "runtime_bound":
                active.update(
                    {
                        "handle_present": True,
                        "can_request": True,
                        "request_state_before": "available",
                        "cleanup_ms": 900,
                    }
                )
            else:
                active.update(
                    {
                        "handle_present": False,
                        "can_request": False,
                        "request_state_before": "unavailable",
                        "cleanup_ms": None,
                    }
                )
            ui = case["ui"]
            ui.update(
                {
                    "shows_plan_scope": True,
                    "shows_model_stream_scope": True,
                    "shows_active_tool_scope": True,
                    "shows_stop_plan": True,
                    "shows_bare_stop": False,
                    "shows_direct_tool_stop": name == "runtime_bound",
                    "warns_active_tool_continues": True,
                    "polls_after_plan_cancel": True,
                    "shows_final_tool_state": True,
                    "normal_chat_unchanged": True,
                }
            )
            case["run_id_sha256"] = digest(f"{platform}:{name}:run")
            artifact = root / case["artifact_path"]
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(
                json.dumps(
                    {
                        "platform": platform,
                        "case": name,
                        "candidate": IDENTITY["git_sha"],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            case["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return value, inventory


def judge(value, inventory, root, *, now=NOW):
    return module.judge(
        observations=value,
        identity=IDENTITY,
        inventory=inventory,
        root=root,
        now=now,
    )[0]


checks = []


def check(label, condition):
    checks.append((label, bool(condition)))


with tempfile.TemporaryDirectory(prefix="kaliv-t023-physical-") as tmp:
    root = Path(tmp)
    baseline, inventory = make_baseline(root)
    check("baseline is green", judge(baseline, inventory, root) == [])

    changed = copy.deepcopy(baseline)
    changed["candidate"]["git_sha"] = "c" * 40
    check(
        "candidate drift fails closed",
        any("candidate.git_sha mismatch" in e for e in judge(changed, inventory, root)),
    )

    changed = copy.deepcopy(baseline)
    changed["capability_inventory_sha256"] = "d" * 64
    check(
        "capability inventory drift fails closed",
        any("capability_inventory_sha256 mismatch" in e for e in judge(changed, inventory, root)),
    )

    changed = copy.deepcopy(baseline)
    changed["platforms"]["android"]["cases"][0]["observed_at"] = (
        NOW - timedelta(hours=25)
    ).isoformat()
    check(
        "stale physical evidence fails",
        any("old" in e or "window" in e for e in judge(changed, inventory, root)),
    )

    changed = copy.deepcopy(baseline)
    changed["platforms"]["windows"]["cases"][0]["observed_at"] = (
        NOW + timedelta(hours=1)
    ).isoformat()
    check(
        "future physical evidence fails",
        any("future" in e for e in judge(changed, inventory, root)),
    )

    changed = copy.deepcopy(baseline)
    case = changed["platforms"]["android"]["cases"][0]
    artifact = root / case["artifact_path"]
    original = artifact.read_bytes()
    artifact.write_bytes(original + b"tamper")
    check(
        "artifact tamper fails",
        any("does not match" in e for e in judge(changed, inventory, root)),
    )
    artifact.write_bytes(original)

    changed = copy.deepcopy(baseline)
    changed["platforms"]["android"]["cases"][0]["artifact_path"] = "../escape.json"
    check(
        "artifact path escape fails",
        any("escapes" in e for e in judge(changed, inventory, root)),
    )

    changed = copy.deepcopy(baseline)
    ui = changed["platforms"]["android"]["cases"][0]["ui"]
    ui["shows_bare_stop"] = True
    ui["shows_direct_tool_stop"] = True
    errors = judge(changed, inventory, root)
    check(
        "false controls fail",
        any("shows_bare_stop" in e for e in errors)
        and any("shows_direct_tool_stop" in e for e in errors),
    )

    changed = copy.deepcopy(baseline)
    late = next(
        case
        for case in changed["platforms"]["windows"]["cases"]
        if case["name"] == "late_completion"
    )
    late["receipt"]["active_tool"]["state_after"] = "succeeded"
    late["ui"]["polls_after_plan_cancel"] = False
    errors = judge(changed, inventory, root)
    check(
        "late completion and polling truth fail closed",
        any("completed_after_cancel" in e for e in errors)
        and any("polls_after_plan_cancel" in e for e in errors),
    )

    changed = copy.deepcopy(baseline)
    changed["platforms"]["android"]["cases"].pop()
    check(
        "missing required case fails",
        any("cases mismatch" in e for e in judge(changed, inventory, root)),
    )

    changed = copy.deepcopy(baseline)
    cases = changed["platforms"]["windows"]["cases"]
    cases[1]["run_id_sha256"] = cases[0]["run_id_sha256"]
    check(
        "run reuse fails",
        any("reuses a run_id_sha256" in e for e in judge(changed, inventory, root)),
    )

with tempfile.TemporaryDirectory(prefix="kaliv-t023-runtime-") as tmp:
    root = Path(tmp)
    runtime_inventory = copy.deepcopy(INVENTORY)
    runtime_inventory["runtime"] = ["tool:runtime_demo"]
    baseline, inventory = make_baseline(root, inventory=runtime_inventory)
    check("runtime baseline is green", judge(baseline, inventory, root) == [])

    changed = copy.deepcopy(baseline)
    runtime_case = next(
        case
        for case in changed["platforms"]["android"]["cases"]
        if case["name"] == "runtime_bound"
    )
    runtime_case["receipt"]["active_tool"]["handle_present"] = False
    runtime_case["receipt"]["active_tool"]["can_request"] = False
    runtime_case["ui"]["shows_direct_tool_stop"] = False
    check(
        "runtime capability requires a bound handle and direct control",
        any("handle_present" in e for e in judge(changed, inventory, root)),
    )

    changed = copy.deepcopy(baseline)
    runtime_case = next(
        case
        for case in changed["platforms"]["windows"]["cases"]
        if case["name"] == "runtime_bound"
    )
    runtime_case["receipt"]["active_tool"]["cleanup_ms"] = 5001
    check(
        "runtime cleanup is bounded",
        any("cleanup_ms" in e for e in judge(changed, inventory, root)),
    )

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-023 TERMINATION UI PHYSICAL REPORT: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
