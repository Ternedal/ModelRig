"""Contracts for candidate-bound physical Windows desktop gate evidence."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.desktop_physical_gate import (  # noqa: E402
    DesktopPhysicalGateError,
    DesktopPhysicalGateReport,
    PhysicalGateFileVerifier,
    load_physical_gate_report,
)

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def rejected(value):
    try:
        DesktopPhysicalGateReport.from_dict(value)
    except DesktopPhysicalGateError as exc:
        return str(exc)
    return None


def valid_report():
    return {
        "schema": "kaliv-desktop-physical-gate-report/v1",
        "candidate_sha": "a" * 40,
        "version": "1.58.145",
        "run_id": "dpg_" + "1" * 24,
        "started_at_ms": 1_000_000,
        "finished_at_ms": 1_060_000,
        "host": {
            "os": "Windows",
            "windows_build": "10.0.26100",
            "architecture": "AMD64",
        },
        "probes": {
            "low_integrity": {
                "schema": "kaliv-desktop-physical-gate-probe/v1",
                "status": "passed",
                "parent_integrity_rid": 0x2000,
                "child_integrity_rid": 0x1000,
                "child_pid": 1234,
                "token_restricted": True,
            },
            "uipi": {
                "schema": "kaliv-desktop-physical-gate-probe/v1",
                "status": "passed",
                "sender_integrity_rid": 0x1000,
                "control_target_integrity_rid": 0x1000,
                "elevated_target_integrity_rid": 0x3000,
                "control_received": True,
                "elevated_received": False,
                "canary_sha256": "b" * 64,
            },
            "kill_switch": {
                "schema": "kaliv-desktop-physical-gate-probe/v1",
                "status": "passed",
                "job_kill_on_close": True,
                "child_pid": 2234,
                "grandchild_pid": 2235,
                "process_tree_terminated": True,
                "termination_ms": 250,
                "heartbeat_sha256": "c" * 64,
            },
        },
        "production_activation": False,
    }


print("valid report is exact, bounded and candidate-bound:")
raw = valid_report()
report = DesktopPhysicalGateReport.from_dict(raw)
check(report.to_dict() == raw, "round-trip preserves the exact report contract")
check(len(report.sha256) == 64, "canonical report has a stable SHA-256 digest")
evidence = report.evidence(expires_at_ms=1_060_000 + 86_400_000)
check(evidence.candidate_sha == "a" * 40 and evidence.evidence_sha256 == report.sha256, "evidence binds candidate and report digest")
check(evidence.low_integrity_verified and evidence.uipi_verified and evidence.kill_switch_verified, "all three physical gates reach the execution evidence")
check(evidence.production_activation is False, "physical evidence never activates production")

print("every physical claim is independently fail-closed:")
mutations = []
for path, value in (
    (("probes", "low_integrity", "child_integrity_rid"), 0x2000),
    (("probes", "low_integrity", "token_restricted"), False),
    (("probes", "uipi", "control_received"), False),
    (("probes", "uipi", "elevated_received"), True),
    (("probes", "uipi", "elevated_target_integrity_rid"), 0x1000),
    (("probes", "kill_switch", "job_kill_on_close"), False),
    (("probes", "kill_switch", "process_tree_terminated"), False),
    (("probes", "kill_switch", "grandchild_pid"), 2234),
    (("probes", "kill_switch", "termination_ms"), 10_001),
):
    changed = copy.deepcopy(raw)
    cursor = changed
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    mutations.append((path, rejected(changed)))
check(all(error is not None for _path, error in mutations), "low-integrity, UIPI and kill-switch sabotage all turn the report red")

changed = copy.deepcopy(raw)
changed["host"]["os"] = "Linux"
check(rejected(changed) is not None, "a CI/Linux report cannot impersonate physical Windows evidence")
changed = copy.deepcopy(raw)
changed["production_activation"] = True
check(rejected(changed) is not None, "production activation cannot be smuggled into the report")
changed = copy.deepcopy(raw)
changed["extra"] = "ignored?"
check(rejected(changed) is not None, "unknown top-level fields are rejected rather than ignored")
changed = copy.deepcopy(raw)
changed["finished_at_ms"] = changed["started_at_ms"] + 15 * 60 * 1000 + 1
check(rejected(changed) is not None, "an implausibly long physical run is rejected")
check(
    rejected({**raw, "candidate_sha": "A" * 40}) is not None,
    "candidate commit must be an exact lowercase full SHA",
)

print("file verifier detects stale paths, candidate mismatch and mutation:")
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp).resolve() / "desktop-physical-gate.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    loaded = load_physical_gate_report(path)
    verifier = PhysicalGateFileVerifier(
        path,
        candidate_sha="a" * 40,
        report_sha256=loaded.sha256,
    )
    check(verifier(loaded.evidence(expires_at_ms=1_146_400_000)), "exact file, candidate and digest verify")
    wrong_candidate = PhysicalGateFileVerifier(
        path,
        candidate_sha="d" * 40,
        report_sha256=loaded.sha256,
    )
    check(not wrong_candidate(loaded.evidence(expires_at_ms=1_146_400_000)), "same report cannot authorize another candidate")
    mutated = copy.deepcopy(raw)
    mutated["host"]["windows_build"] = "10.0.99999"
    path.write_text(json.dumps(mutated, ensure_ascii=False), encoding="utf-8")
    check(not verifier(loaded.evidence(expires_at_ms=1_146_400_000)), "post-validation file mutation invalidates the digest binding")
    check(
        rejected(valid_report()) is None,
        "mutation test did not alter the canonical valid fixture",
    )

try:
    load_physical_gate_report("relative-report.json")
except DesktopPhysicalGateError:
    relative_rejected = True
else:
    relative_rejected = False
check(relative_rejected, "relative report paths are refused")

source = (ROOT / "worker/app/desktop_physical_gate.py").read_text(encoding="utf-8")
check("os.getenv" not in source, "physical evidence has no environment-variable bypass")
check("subprocess" not in source and "ctypes" not in source, "report verifier performs no process launch or native input")
check("desktop_physical_gate" not in (ROOT / "worker/app/main.py").read_text(encoding="utf-8"), "worker startup does not import the physical gate")
from app import tools as T  # noqa: E402
check("desktop_click" not in T.REGISTRY and "desktop_type" not in T.REGISTRY, "physical evidence still registers no input tools")

print(f"\n===== DESKTOP PHYSICAL GATE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
