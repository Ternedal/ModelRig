from __future__ import annotations

import importlib.util
import sys
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


scripts = Path("scripts").resolve()
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location(
    "agent3_rig_evidence", scripts / "agent3_rig_evidence.py"
)
assert spec and spec.loader
evidence = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = evidence
spec.loader.exec_module(evidence)


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


class FakeClient:
    def __init__(self, backend_version="1.58.38", worker_version="1.58.38",
                 code_sha256="d" * 64):
        self.backend_version = backend_version
        self.worker_version = worker_version
        self.code_sha256 = code_sha256
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET" and path == "/api/v1/status":
            return {"version": self.backend_version}
        if method == "GET" and path == "/api/v1/experimental/agent3/status":
            return {
                "enabled": True,
                "experimental": True,
                "worker_version": self.worker_version,
                # A rig that cannot say which code it runs cannot produce
                # evidence about code (F-508).
                "code_sha256": self.code_sha256,
                "production_activation": False,
            }
        raise AssertionError(f"unexpected request: {method} {path}")


def valid_report(*, decision: str, planner_model: str) -> dict:
    now = time.time()
    receipt = {
        "requested": True,
        "sent_to_model": True,
        "target": "local",
        "included_ids": ["memory/private"],
        "excluded_ids": [],
        "character_count": 99,
        "sha256": "a" * 64,
    }
    if decision == "approve":
        state = "completed"
        mutation_expected = True
        write_events = [
            "run_created",
            "policy_decision",
            "confirmation_required",
            "confirmation_approved",
            "step_started",
            "step_succeeded",
            "run_completed",
        ]
    else:
        state = "cancelled"
        mutation_expected = False
        write_events = [
            "run_created",
            "policy_decision",
            "confirmation_required",
            "confirmation_denied",
        ]
    return {
        "schema": "kaliv-agent3-rig-validation/v1",
        "started_at": datetime.fromtimestamp(now - 10, timezone.utc).isoformat(),
        "finished_at": datetime.fromtimestamp(now - 5, timezone.utc).isoformat(),
        "success": True,
        "host": {"hostname": "private-host"},
        "target": {
            "base_url": "http://private-host:8080",
            "planner_model": planner_model,
            "write_decision": decision,
        },
        "validation": {
            "id": "private-validation-id",
            "memory_subject": "private-subject",
            "marker_sha256": "c" * 64,
        },
        "checks": {
            "status": {
                "enabled": True,
                "experimental": True,
                "production_tools_path_untouched": True,
            },
            "context_preview": {
                "included_ids": ["memory/private"],
                "excluded_ids": [],
                "character_count": 99,
                "sha256": "a" * 64,
                "sent_to_model": False,
            },
            "read_run": {
                "state": "completed",
                "receipt": deepcopy(receipt),
                "event_kinds": [
                    "run_created",
                    "policy_decision",
                    "step_started",
                    "step_succeeded",
                    "run_completed",
                ],
            },
            "write_preview": {
                "tool": "note_append",
                "risk": "write",
                "receipt": deepcopy(receipt),
            },
            "confirmation_card": {
                "digest_sha256": "b" * 64,
                "pre_confirmation_events": [
                    "run_created",
                    "policy_decision",
                    "confirmation_required",
                ],
            },
            "write_confirmation": {
                "decision": decision,
                "state": state,
                "mutation_expected": mutation_expected,
                "event_kinds": write_events,
            },
            "single_use": {"replay_blocked": True},
        },
        "cleanup": {
            "deleted": True,
            "content_erased": True,
            "source_ref_erased": True,
        },
        "error": None,
    }


def fake_run_validation(
    _client,
    *,
    planner_model,
    approve_write,
    report_path,
    poll_seconds,
    max_wait_seconds,
):
    assert poll_seconds > 0
    assert max_wait_seconds > 0
    report = valid_report(
        decision="approve" if approve_write else "deny",
        planner_model=planner_model,
    )
    evidence.validation._write_report(report_path, report)
    return report


root = Path(tempfile.mkdtemp(prefix="agent3-rig-evidence-"))
deny_path = root / "deny.json"
deny_client = FakeClient()
deny = evidence.produce_evidence(
    deny_client,
    planner_model="fake-local-planner",
    approve_write=False,
    report_path=deny_path,
    poll_seconds=0.01,
    max_wait_seconds=1,
    run_validation=fake_run_validation,
)
check(deny["assessment"]["eligible_for_developer_preview"] is True, "deny evidence opens developer preview")
check(deny["assessment"]["eligible_for_write_pilot"] is False, "deny evidence does not open write pilot")
check(deny["assessment"]["production_activation"] is False, "evidence never activates production")
check(deny["report"]["target"]["modelrig_version"] == "1.58.38", "backend version is persisted")
check(deny["report"]["target"]["worker_version"] == "1.58.38", "worker version is persisted")
check(deny["report"]["target"]["planner_model"] == "fake-local-planner", "planner model is persisted")
check(deny["report"]["checks"]["version_binding"]["match"] is True, "version binding is explicit")
check(
    deny_client.calls[:2]
    == [
        ("GET", "/api/v1/status", None),
        ("GET", "/api/v1/experimental/agent3/status", None),
    ],
    "preflight uses both protected status sources",
)

approve_path = root / "approve.json"
approved = evidence.produce_evidence(
    FakeClient(),
    planner_model="fake-local-planner",
    approve_write=True,
    report_path=approve_path,
    poll_seconds=0.01,
    max_wait_seconds=1,
    run_validation=fake_run_validation,
)
check(approved["assessment"]["eligible_for_write_pilot"] is True, "approved evidence opens write pilot")
check(approved["assessment"]["proofs"]["write_execution"] is True, "approved event chain proves execution")

try:
    evidence.preflight_versions(FakeClient(worker_version="1.58.37"))
    mismatch_blocked = False
except evidence.EvidenceError as exc:
    mismatch_blocked = "versions differ" in str(exc)
check(mismatch_blocked, "backend/worker version mismatch fails before validation")

try:
    evidence.produce_evidence(
        FakeClient(),
        planner_model="   ",
        approve_write=False,
        report_path=root / "missing-model.json",
        run_validation=fake_run_validation,
    )
    missing_model_blocked = False
except evidence.EvidenceError:
    missing_model_blocked = True
check(missing_model_blocked, "unnamed planner model cannot produce promotion evidence")

check(evidence.main(["--token", ""]) == 2, "CLI requires a paired token")
check(
    evidence.main(["--token", "test-token", "--planner-model", ""]) == 2,
    "CLI requires an explicit planner model",
)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
