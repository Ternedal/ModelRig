from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.task_readiness import (
    PILOT_SCHEMA,
    READINESS_SCHEMA,
    assess_task_readiness,
    build_task_readiness_router,
    evaluate_configured_task_readiness,
)

NOW = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc).timestamp()
VERSION = "1.58.125"
CODE = "a" * 64


def validation(**overrides):
    value = {
        "eligible_for_developer_preview": True,
        "version_match": True,
        "code_match": True,
        "production_activation": False,
        "report_sha256": "b" * 64,
    }
    value.update(overrides)
    return value


def valid_result(index: int) -> dict:
    return {
        "task_id": f"{index:02d}",
        "category": "read",
        "success": True,
        "route": "rig_tools_local",
        "retry_events": 0,
        "event_kinds": [
            "run_created",
            "policy_decision",
            "step_started",
            "step_succeeded",
            "run_completed",
        ],
    }


def report(**overrides) -> dict:
    value = {
        "schema": PILOT_SCHEMA,
        "finished_at": "2026-07-19T09:00:00+00:00",
        "success": True,
        "candidate": {
            "version": VERSION,
            "git_sha": "1" * 40,
            "code_sha256": CODE,
        },
        "target": {
            "execution_mode": "experimental-read-only",
            "production_activation": False,
        },
        "backend": {
            "production_tools_path_untouched": True,
            "production_activation": False,
        },
        "summary": {
            "tasks": 20,
            "successes": 20,
            "failures": 0,
            "task_success_rate": 1.0,
            "replans": 2,
            "retry_events": 0,
            "error_types": {},
        },
        "stop_fallback": {
            "success": True,
            "agent3_state": "cancelled",
            "completed_agent3_steps": 1,
            "pending_steps_after_stop": 1,
            "fallback_path": "/api/v1/chat",
        },
        "results": [valid_result(index) for index in range(1, 21)],
    }
    value.update(overrides)
    return value


def assess(value=None, *, operator=True, validation_value=None, now=NOW):
    payload = report() if value is None else value
    return assess_task_readiness(
        payload,
        validation=validation() if validation_value is None else validation_value,
        current_version=VERSION,
        current_code=CODE,
        operator_enabled=operator,
        now=now,
        report_sha256=hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
    )


def test_valid_evidence_selects_readonly_task_surface() -> None:
    value = assess()
    assert value["schema"] == READINESS_SCHEMA
    assert value["eligible_for_task_ui"] is True
    assert value["operator_enabled"] is True
    assert value["selected_surface"] == "agent3_readonly"
    assert value["candidate_surface"] == "agent3_readonly"
    assert value["fallback_surface"] == "agent2"
    assert value["reason"] == "agent3_readonly_selected"
    assert value["reasons"] == []
    assert value["production_activation"] is False
    assert value["normal_chat_route_unchanged"] is True
    assert value["pilot"]["replans"] == 2
    assert value["pilot"]["stop_fallback_proven"] is True


def test_operator_off_keeps_evidence_visible_and_selects_agent2() -> None:
    value = assess(operator=False)
    assert value["eligible_for_task_ui"] is True
    assert value["selected_surface"] == "agent2"
    assert value["reason"] == "operator_disabled"
    assert value["normal_chat_route_unchanged"] is True


def test_stale_report_fails_closed() -> None:
    value = assess(now=datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp())
    assert value["eligible_for_task_ui"] is False
    assert value["selected_surface"] == "agent2"
    assert "pilot_report_stale" in value["reasons"]


def test_version_and_code_are_both_bound() -> None:
    bad = report()
    bad["candidate"] = dict(bad["candidate"], version="1.58.124", code_sha256="c" * 64)
    value = assess(bad)
    assert value["selected_surface"] == "agent2"
    assert value["pilot"]["version_match"] is False
    assert value["pilot"]["code_match"] is False
    assert "pilot_candidate_version_mismatch" in value["reasons"]
    assert "pilot_candidate_code_mismatch" in value["reasons"]


def test_failed_task_or_retry_blocks_readiness() -> None:
    bad = report()
    bad["results"] = list(bad["results"])
    bad["results"][6] = dict(bad["results"][6], success=False, retry_events=1)
    value = assess(bad)
    assert value["eligible_for_task_ui"] is False
    assert value["selected_surface"] == "agent2"
    assert "pilot_result_not_successful_read_route" in value["reasons"]


def test_confirmation_event_blocks_readonly_promotion() -> None:
    bad = report()
    bad["results"] = list(bad["results"])
    bad["results"][0] = dict(
        bad["results"][0],
        event_kinds=["run_created", "confirmation_required", "run_cancelled"],
    )
    value = assess(bad)
    assert value["eligible_for_task_ui"] is False
    assert value["selected_surface"] == "agent2"
    assert "pilot_result_confirmation_present" in value["reasons"]


def test_stop_fallback_is_mandatory() -> None:
    bad = report(stop_fallback={"success": False})
    value = assess(bad)
    assert value["pilot"]["stop_fallback_proven"] is False
    assert value["selected_surface"] == "agent2"
    assert "pilot_stop_fallback_not_proven" in value["reasons"]


def test_rig_validation_must_still_match_candidate() -> None:
    value = assess(validation_value=validation(code_match=False))
    assert value["eligible_for_task_ui"] is False
    assert value["selected_surface"] == "agent2"
    assert "rig_validation_code_mismatch" in value["reasons"]


def test_configured_reader_requires_explicit_path() -> None:
    value = evaluate_configured_task_readiness(
        current_version=VERSION,
        current_code=CODE,
        validation=validation(),
        environ={"KALIV_AGENT3_TASK_UI": "1"},
        now=NOW,
    )
    assert value["selected_surface"] == "agent2"
    assert value["reason"] == "pilot_report_path_not_configured"
    assert value["pilot"]["configured"] is False


def test_configured_reader_hashes_redacts_and_selects_surface() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "pilot.json"
        payload = report(secret="must-not-escape")
        raw = json.dumps(payload).encode("utf-8")
        path.write_bytes(raw)
        value = evaluate_configured_task_readiness(
            current_version=VERSION,
            current_code=CODE,
            validation=validation(),
            environ={
                "KALIV_AGENT3_TASK_UI": "1",
                "KALIV_AGENT3_PILOT_REPORT": str(path),
            },
            now=NOW,
        )
    assert value["eligible_for_task_ui"] is True
    assert value["selected_surface"] == "agent3_readonly"
    assert value["pilot"]["report_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "must-not-escape" not in json.dumps(value)


def test_unknown_or_malformed_report_never_selects_agent3() -> None:
    value = assess({"schema": "future/v9"})
    assert value["selected_surface"] == "agent2"
    assert value["eligible_for_task_ui"] is False
    assert value["production_activation"] is False


def test_api_rejects_a_provider_that_claims_activation() -> None:
    app = FastAPI()
    app.include_router(
        build_task_readiness_router(
            lambda: {
                "selected_surface": "agent3_readonly",
                "candidate_surface": "agent3_readonly",
                "fallback_surface": "agent2",
                "eligible_for_task_ui": True,
                "operator_enabled": True,
                "normal_chat_route_unchanged": True,
                "production_activation": True,
                "reason": "agent3_readonly_selected",
            }
        )
    )
    response = TestClient(app, raise_server_exceptions=False).get(
        "/experimental/agent3/task-readiness"
    )
    assert response.status_code == 500


def test_api_rejects_unready_agent3_selection() -> None:
    app = FastAPI()
    app.include_router(
        build_task_readiness_router(
            lambda: {
                "selected_surface": "agent3_readonly",
                "candidate_surface": "agent3_readonly",
                "fallback_surface": "agent2",
                "eligible_for_task_ui": False,
                "operator_enabled": True,
                "normal_chat_route_unchanged": True,
                "production_activation": False,
                "reason": "agent3_readonly_selected",
            }
        )
    )
    response = TestClient(app, raise_server_exceptions=False).get(
        "/experimental/agent3/task-readiness"
    )
    assert response.status_code == 500


def test_api_returns_typed_selected_contract() -> None:
    expected = assess()
    app = FastAPI()
    app.include_router(build_task_readiness_router(lambda: expected))
    response = TestClient(app).get("/experimental/agent3/task-readiness")
    assert response.status_code == 200
    assert response.json() == expected
    assert response.json()["selected_surface"] == "agent3_readonly"


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_")]

if __name__ == "__main__":
    for test_case in TESTS:
        test_case()
    print(f"agent3 task readiness: {len(TESTS)} passed")
