"""Contract checks for Consciousness restart capture."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "consciousness_restart_capture_test",
    ROOT / "scripts" / "consciousness_restart_capture.py",
)
assert SPEC and SPEC.loader
capture = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = capture
SPEC.loader.exec_module(capture)

SHA = "a" * 40


def identity():
    return {"git_sha": SHA, "branch": "main", "working_tree_clean": True}


def status(ch):
    return {
        "schema": capture.STATUS_SCHEMA,
        "runtime_instance_ref": "runtime-instance:" + ch * 32,
        "production_activation": False,
    }


def test_before_capture_is_not_restart_proof():
    with patch.object(capture, "candidate_identity", return_value=identity()), patch.object(
        capture, "fetch_status", return_value=status("1")
    ):
        result = capture.capture_before(root=ROOT, worker_url=capture.DEFAULT_WORKER_URL, timeout=1)
    assert result["phase"] == "before"
    assert result["restart_proven"] is False
    assert result["production_activation"] is False


def test_after_requires_new_runtime_instance():
    before = {
        "schema": capture.CAPTURE_SCHEMA,
        "phase": "before",
        "candidate": identity(),
        "status": status("1"),
    }
    with patch.object(capture, "candidate_identity", return_value=identity()), patch.object(
        capture, "fetch_status", return_value=status("2")
    ):
        result = capture.capture_after(
            root=ROOT,
            worker_url=capture.DEFAULT_WORKER_URL,
            timeout=1,
            before=before,
        )
    assert result["phase"] == "after"
    assert result["restart_proven"] is True
    assert result["before_runtime_instance_ref"] == status("1")["runtime_instance_ref"]
    assert result["status"]["runtime_instance_ref"] == status("2")["runtime_instance_ref"]
    assert result["production_activation"] is False


def test_same_runtime_instance_fails_closed():
    before = {
        "schema": capture.CAPTURE_SCHEMA,
        "phase": "before",
        "candidate": identity(),
        "status": status("1"),
    }
    with patch.object(capture, "candidate_identity", return_value=identity()), patch.object(
        capture, "fetch_status", return_value=status("1")
    ):
        try:
            capture.capture_after(
                root=ROOT,
                worker_url=capture.DEFAULT_WORKER_URL,
                timeout=1,
                before=before,
            )
        except capture.RestartCaptureError as exc:
            assert "did not change" in str(exc)
        else:
            raise AssertionError("same runtime instance must fail")


def test_sha_change_across_restart_fails_closed():
    before = {
        "schema": capture.CAPTURE_SCHEMA,
        "phase": "before",
        "candidate": identity(),
        "status": status("1"),
    }
    changed = {"git_sha": "b" * 40, "branch": "main", "working_tree_clean": True}
    with patch.object(capture, "candidate_identity", return_value=changed):
        try:
            capture.capture_after(
                root=ROOT,
                worker_url=capture.DEFAULT_WORKER_URL,
                timeout=1,
                before=before,
            )
        except capture.RestartCaptureError as exc:
            assert "Git SHA changed" in str(exc)
        else:
            raise AssertionError("candidate SHA drift must fail")


def test_non_loopback_url_is_rejected():
    try:
        capture.normalize_worker_url("http://192.168.1.20:8099")
    except capture.RestartCaptureError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback worker URL must fail")


if __name__ == "__main__":
    test_before_capture_is_not_restart_proof()
    test_after_requires_new_runtime_instance()
    test_same_runtime_instance_fails_closed()
    test_sha_change_across_restart_fails_closed()
    test_non_loopback_url_is_rejected()
    print("Consciousness restart capture contract: PASS")
