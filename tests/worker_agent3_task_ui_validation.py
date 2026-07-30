#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("task_ui_validation_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


module = load_module(ROOT / "scripts" / "agent3_task_ui_validation.py")
passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


CANDIDATE = {
    "version": "1.test",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "working_tree_clean": True,
    "version_stamps_consistent": True,
}
BINDING = {
    "pilot_report_sha256": "c" * 64,
    "pilot_candidate_git_sha": CANDIDATE["git_sha"],
    "rig_validation_report_sha256": "d" * 64,
}
RECEIPT = {
    "schema": "kaliv-agent3-capability-receipt/v1",
    "graph_sha256": "e" * 64,
    "plan_sha256": "f" * 64,
    "route": "rig_tools_local",
    "allowed": True,
    "blockers": [],
    "production_activation": False,
}


def readiness() -> dict:
    return {
        "schema": "kaliv-agent3-task-readiness/v1",
        "selected_surface": "agent3_readonly",
        "candidate_surface": "agent3_readonly",
        "fallback_surface": "agent2",
        "eligible_for_task_ui": True,
        "operator_enabled": True,
        "normal_chat_route_unchanged": True,
        "production_activation": False,
        "reason": "agent3_readonly_selected",
        "reasons": [],
        "pilot": {
            "configured": True,
            "present": True,
            "structurally_valid": True,
            "fresh": True,
            "version_match": True,
            "code_match": True,
            "candidate_git_sha": CANDIDATE["git_sha"],
            "report_sha256": BINDING["pilot_report_sha256"],
            "tasks": 20,
            "successes": 20,
            "failures": 0,
            "replans": 2,
            "retry_events": 0,
            "stop_fallback_proven": True,
        },
        "rig_validation": {
            "eligible_for_developer_preview": True,
            "version_match": True,
            "code_match": True,
            "report_sha256": BINDING["rig_validation_report_sha256"],
        },
        "ui_contract": {
            "route_source": "server_authoritative",
            "stop_visible": True,
            "fallback_visible": True,
            "receipts_visible": True,
            "replans_visible": True,
            "outcomes_visible": True,
        },
    }


def preview() -> dict:
    return {
        "task_surface": "agent3_readonly",
        "selected_surface": "agent3_readonly",
        "fallback_surface": "agent2",
        "reason": "agent3_readonly_selected",
        "route": {
            "kind": "rig_tools_local",
            "uses_cloud": False,
            "uses_rig": True,
            "uses_tools": True,
            "uses_rag": False,
        },
        "rationale": "read status",
        "plan": [{
            "tool": "rig_status",
            "args": {},
            "risk": "read",
            "sensitivity": "public",
            "egress": "local",
            "idempotent": True,
            "summary": "Læs rigstatus",
        }],
        "plan_id": "plan_1",
        "expires_in_seconds": 300,
        "executed": False,
        "readiness_binding": BINDING,
        "capability_receipt": RECEIPT,
        "production_activation": False,
        "normal_chat_route_unchanged": True,
    }


def snapshot(state: str, terminal: bool) -> dict:
    return {
        "task_surface": "agent3_readonly",
        "selected_surface": "agent3_readonly",
        "fallback_surface": "agent2",
        "reason": "agent3_readonly_selected",
        "run": {
            "id": "run_1",
            "state": state,
            "route": {"kind": "rig_tools_local"},
            "current_step": 1 if terminal else 0,
            "steps": [{
                "id": "step_1",
                "tool": "rig_status",
                "args": {},
                "risk": "read",
                "sensitivity": "public",
                "egress": "local",
                "idempotent": True,
                "summary": "Læs rigstatus",
                "state": "succeeded" if terminal else "pending",
                "error": None,
            }],
            "answer": "Riggen er klar" if terminal else None,
            "error": None,
        },
        "events": [
            {"kind": "run_created", "payload": {}},
            *([{"kind": "run_completed", "payload": {}}] if terminal else []),
        ],
        "readiness_binding": BINDING,
        "capability_receipt": RECEIPT,
        "terminal": terminal,
        "production_activation": False,
        "normal_chat_route_unchanged": True,
    }


class Fixture:
    def __init__(self, invalid_status: bool = False):
        self.requests: list[tuple[str, str, str, str]] = []
        self.cancelled = False
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status: int, value: dict):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _handle(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode() if length else ""
                fixture.requests.append((
                    self.command,
                    self.path,
                    self.headers.get("Authorization", ""),
                    body,
                ))
                if self.path.endswith("/task-readiness"):
                    self._send(200, readiness())
                elif self.path.endswith("/task/plan"):
                    self._send(200, preview())
                elif self.path.endswith("/plans/plan_1/start"):
                    self._send(202, snapshot("running", False))
                elif self.path.endswith("/runs/run_1/cancel"):
                    fixture.cancelled = True
                    self._send(200, snapshot("cancelled", True))
                elif self.path.endswith("/runs/run_1"):
                    value = (
                        snapshot("waiting_confirmation", False)
                        if invalid_status else snapshot("completed", True)
                    )
                    self._send(200, value)
                else:
                    self._send(404, {"error": "not found"})

            do_GET = _handle
            do_POST = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_address[1]}", self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def observations(root: Path, now: datetime) -> Path:
    evidence = root / "validation" / "agent3-task-ui-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in ("android", "desktop"):
        path = evidence / f"{name}.txt"
        path.write_text(f"physical {name} proof", encoding="utf-8")
        files[name] = (path, hashlib.sha256(path.read_bytes()).hexdigest())
    checks = {key: True for key in module.REQUIRED_CLIENT_CHECKS}
    value = {
        "schema": module.OBSERVATIONS_SCHEMA,
        "observed_at": now.isoformat(),
        "operator": "Anders",
        "clients": {},
    }
    for name, expected_platform in (("android", "android"), ("desktop", "windows")):
        path, digest = files[name]
        value["clients"][name] = {
            "platform": expected_platform,
            "device": "Pixel 6a" if name == "android" else "ModelRig Windows",
            "candidate": {
                "version": CANDIDATE["version"],
                "git_sha": CANDIDATE["git_sha"],
                "code_sha256": CANDIDATE["code_sha256"],
            },
            "selected_surface": "agent3_readonly",
            "fallback_surface": "agent2",
            "server_reason": "agent3_readonly_selected",
            "stop_terminal_state": "cancelled",
            "normal_chat_surface": "agent2",
            "checks": checks.copy(),
            "evidence_path": path.relative_to(root).as_posix(),
            "evidence_sha256": digest,
        }
    target = root / "validation" / "observations.json"
    target.write_text(json.dumps(value), encoding="utf-8")
    return target


print("Agent 3 task UI physical validation")
now = datetime.now(timezone.utc).replace(microsecond=0)
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    path = observations(root, now)
    loaded = module.load_observations(
        path,
        root=root,
        candidate=CANDIDATE,
        now=now,
        max_observation_age_hours=24.0,
    )
    check(
        set(loaded["clients"]) == {"android", "desktop"},
        "valid physical observations accepted",
    )
    check(
        loaded["clients"]["android"]["artifact"]["bytes"] > 0,
        "artifact is re-read and summarized",
    )

    raw = json.loads(path.read_text())
    raw["clients"]["android"]["checks"]["stop_after_fallback"] = False
    path.write_text(json.dumps(raw))
    error = None
    try:
        module.load_observations(
            path,
            root=root,
            candidate=CANDIDATE,
            now=now,
            max_observation_age_hours=24.0,
        )
    except Exception as exc:
        error = exc
    check(isinstance(error, module.TaskUiValidationError), "false physical check is rejected")

    path = observations(root, now)
    raw = json.loads(path.read_text())
    raw["observed_at"] = (now - timedelta(hours=25)).isoformat()
    path.write_text(json.dumps(raw))
    error = None
    try:
        module.load_observations(
            path,
            root=root,
            candidate=CANDIDATE,
            now=now,
            max_observation_age_hours=24.0,
        )
    except Exception as exc:
        error = exc
    check(isinstance(error, module.TaskUiValidationError), "stale physical observation is rejected")

    path = observations(root, now)
    artifact = root / "validation" / "agent3-task-ui-evidence" / "android.txt"
    artifact.write_text("tampered", encoding="utf-8")
    error = None
    try:
        module.load_observations(
            path,
            root=root,
            candidate=CANDIDATE,
            now=now,
            max_observation_age_hours=24.0,
        )
    except Exception as exc:
        error = exc
    check(isinstance(error, module.TaskUiValidationError), "tampered artifact hash is rejected")

with Fixture() as (base, fixture):
    result = module.live_probe(
        base_url=base,
        token="secret-token",
        candidate=CANDIDATE,
        message="Læs rigstatus",
        timeout_s=3.0,
        poll_interval_s=0.001,
    )
    check(result["completed"] is True, "live task probe completes")
    check(result["run"]["state"] == "completed", "terminal run is completed")
    check(result["preview"]["executed"] is False, "preview proves no execution")
    check(
        result["readiness"]["stop_fallback_proven"] is True,
        "readiness retains stop/fallback proof",
    )
    serialized = json.dumps(result)
    check(
        "secret-token" not in serialized and "run_1" not in serialized,
        "token and raw run id are not persisted",
    )
    expected_paths = [
        ("GET", "/api/v1/experimental/agent3/task-readiness"),
        ("POST", "/api/v1/experimental/agent3/task/plan"),
        ("POST", "/api/v1/experimental/agent3/task/plans/plan_1/start"),
        ("GET", "/api/v1/experimental/agent3/task/runs/run_1"),
    ]
    check(
        [(method, path) for method, path, _, _ in fixture.requests] == expected_paths,
        "only normal task routes are called",
    )
    check(
        all(auth == "Bearer secret-token" for _, _, auth, _ in fixture.requests),
        "every live request is authenticated",
    )

with Fixture(invalid_status=True) as (base, fixture):
    error = None
    try:
        module.live_probe(
            base_url=base,
            token="secret-token",
            candidate=CANDIDATE,
            message="Læs rigstatus",
            timeout_s=3.0,
            poll_interval_s=0.001,
        )
    except Exception as exc:
        error = exc
    check(isinstance(error, module.TaskUiValidationError), "confirmation drift fails closed")
    check(fixture.cancelled, "failed live probe best-effort cancels persisted run")

bad = readiness()
bad["selected_surface"] = "agent2"
error = None
try:
    module._validate_readiness(bad, CANDIDATE)
except Exception as exc:
    error = exc
check(
    isinstance(error, module.TaskUiValidationError),
    "Agent 2 readiness cannot run the machine probe",
)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
