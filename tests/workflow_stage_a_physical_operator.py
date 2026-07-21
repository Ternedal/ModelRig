#!/usr/bin/env python3
"""Functional contract for the fail-closed Stage A operator."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage_a_physical_operator.py"
WRAPPER = ROOT / "scripts" / "run-stage-a-physical-validation.ps1"

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def refuses(fn, fragment):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        return fragment.lower() in str(exc).lower()
    return False


check(SCRIPT.is_file(), "Python operator exists")
check(WRAPPER.is_file(), "PowerShell launcher exists")

spec = importlib.util.spec_from_file_location("stage_a_operator_test", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

check(module.EXPECTED_BRANCH == "agent/t032-integration-candidate", "candidate branch is pinned")
check(module.EXPECTED_VERSION == "1.58.141", "candidate version is pinned")
check(module.PROOF_NAMES == (
    "preflight",
    "agent3",
    "model_eval",
    "voice",
    "rag",
    "scheduler_pilot",
), "proof allowlist is exactly six pre-release proofs")

check(module._validate_url("https://example.com/") == "https://example.com/", "HTTPS URL is accepted")
check(module._validate_url("https://example.com:443/path?x=1") == "https://example.com:443/path?x=1", "explicit 443 path/query is preserved")
check(refuses(lambda: module._validate_url("http://example.com/"), "https"), "HTTP is rejected")
check(refuses(lambda: module._validate_url("https://example.com:444/"), "443"), "non-443 port is rejected")
check(refuses(lambda: module._validate_url("https://user:pass@example.com/"), "credentials"), "credentials are rejected")
check(refuses(lambda: module._validate_url("https://example.com/#frag"), "fragment"), "fragments are rejected")
check(refuses(lambda: module._validate_url(" https://example.com/"), "spaces"), "surrounding spaces are rejected")

identity = {
    "version": "1.58.141",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "working_tree_clean": True,
    "version_stamps_consistent": True,
    "identity_source": "git",
}

originals = {name: getattr(module, name) for name in (
    "_candidate_identity", "_run_freeze", "_run_campaign", "_run_browser", "_run_final_gate"
)}


def install_fakes(events):
    module._candidate_identity = lambda expected_sha, root=ROOT: (
        events.append(("identity", expected_sha)) or dict(identity)
    )
    module._run_freeze = lambda expected_sha, actual, root=ROOT: (
        events.append(("freeze", expected_sha)) or {}
    )

    def campaign(mode, actual, *, max_age_hours, min_model_exact, root=ROOT):
        events.append(("campaign", mode, max_age_hours, min_model_exact))
        if mode == "prepare":
            return {"summary": {"missing": ["preflight", "agent3"]}}
        return {
            "summary": {"total": 6, "passed": list(module.PROOF_NAMES), "failed": [], "missing": []},
            "gate": {"candidate_campaign_complete": True},
        }

    module._run_campaign = campaign
    module._run_browser = lambda url, root=ROOT: events.append(("browser", url))
    module._run_final_gate = lambda actual, *, max_age_hours, root=ROOT: (
        events.append(("final", max_age_hours)) or {
            "summary": {"total": 7, "passed": [*module.PROOF_NAMES, "browser_peer_physical"], "errors": []},
            "gate": {
                "passed": True,
                "candidate_campaign_complete": True,
                "browser_peer_physical_complete": True,
                "candidate_ready_for_fast_forward": True,
                "release_validation_pending": True,
                "release_complete": False,
                "all_physical_evidence_complete": False,
                "production_activation": False,
            },
        }
    )


try:
    events = []
    install_fakes(events)
    module.execute("prepare", "a" * 40, physical_guard=False)
    check([item[0] for item in events] == ["identity", "freeze", "campaign"], "prepare stops after the checklist")
    check(events[-1][1] == "prepare", "prepare uses campaign prepare mode")

    events = []
    install_fakes(events)
    module.execute("verify", "a" * 40, physical_guard=False)
    check([item[0] for item in events] == ["identity", "freeze", "campaign"], "verify re-freezes then verifies")
    check(events[-1][1] == "verify", "verify uses campaign verify mode")

    events = []
    install_fakes(events)
    result = module.execute(
        "complete", "a" * 40,
        url="https://example.com/exact?approved=1",
        physical_guard=False,
    )
    check(
        [item[0] for item in events] == ["identity", "freeze", "campaign", "browser", "final"],
        "complete is ordered identity, freeze, six proofs, browser, final gate",
    )
    check(events[2][1] == "verify", "complete verifies six proofs before browser contact")
    check(events[3][1] == "https://example.com/exact?approved=1", "exact approved URL is preserved")
    check(result["gate"]["candidate_ready_for_fast_forward"] is True, "result is candidate-ready")
    check(result["gate"]["release_validation_pending"] is True, "release remains pending")
    check(result["gate"]["release_complete"] is False, "release cannot be claimed complete")
    check(result["gate"]["all_physical_evidence_complete"] is False, "seven proofs cannot claim eight")
    check(result["gate"]["production_activation"] is False, "production remains inactive")
finally:
    for name, value in originals.items():
        setattr(module, name, value)

print(f"\n===== STAGE A OPERATOR: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
