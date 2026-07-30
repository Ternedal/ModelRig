from __future__ import annotations

import copy
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "t022_preflight",
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "agent3_write_pilot_preflight.py",
)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
assert spec.loader
spec.loader.exec_module(mod)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
PILOT_ID = "a" * 32
PREFIX = f"KALIV-T022:{PILOT_ID}:P:"
RIG_SHA = "d" * 64
NOTES = Path("/tmp/kaliv-tools/notes.md")
IDENTITY = {
    "version": "1.58.146",
    "git_sha": "b" * 40,
    "code_sha256": "c" * 64,
    "identity_source": "git",
    "working_tree_clean": True,
    "version_stamps_consistent": True,
}


def manifest() -> dict:
    return {
        "schema": mod.MANIFEST_SCHEMA,
        "pilot_id": PILOT_ID,
        "created_at": mod._iso(NOW - timedelta(minutes=10)),
        "operator": "Anders",
        "target": {
            "version": IDENTITY["version"],
            "git_sha": IDENTITY["git_sha"],
            "code_sha256": IDENTITY["code_sha256"],
            "identity_source": IDENTITY["identity_source"],
            "rig_validation_report_sha256": RIG_SHA,
        },
        "marker_prefix": PREFIX,
        "runs": [
            {
                "ordinal": ordinal,
                "marker": f"{PREFIX}{ordinal:02d}:{ordinal:032x}",
                "run_id": None,
                "bound_at": None,
            }
            for ordinal in range(1, 21)
        ],
    }


def live_status() -> dict:
    return {
        "enabled": True,
        "experimental": True,
        "write_approval": "backend-issued-device-bound-single-use",
        "write_approval_required": True,
        "production_tools_path_untouched": True,
        "production_activation": False,
        "worker_version": IDENTITY["version"],
        "code_sha256": IDENTITY["code_sha256"],
        "rig_validation": {
            "eligible_for_write_pilot": True,
            "version_match": True,
            "code_match": True,
            "report_sha256": RIG_SHA,
        },
    }


def live_tools() -> dict:
    return {
        "enabled": True,
        "tools_dir": str(NOTES.parent),
        "tools": [
            {
                "name": "note_append",
                "enabled": True,
                "risk": "write",
                "impact": "write",
                "network": "none",
                "idempotent": False,
            },
            {
                "name": "rig_status",
                "enabled": True,
                "risk": "read",
                "impact": "read",
                "network": "none",
                "idempotent": True,
            },
            {
                "name": "delete_model",
                "enabled": False,
                "risk": "write",
                "impact": "destructive",
                "network": "configured_service",
                "idempotent": False,
            },
        ],
    }


def judge(
    *,
    m: dict | None = None,
    identity: dict | None = None,
    status: dict | None = None,
    tools: dict | None = None,
    runs: list[dict] | None = None,
    audits: list[dict] | None = None,
    notes: str = "",
    journal_exists: bool = False,
    notes_path: Path = NOTES,
    notes_writable: bool = True,
    journal_parent_writable: bool = True,
):
    return mod.judge_preflight(
        manifest=m or manifest(),
        identity=identity or copy.deepcopy(IDENTITY),
        rig_validation_assessment={"eligible_for_write_pilot": True},
        rig_validation_sha256=RIG_SHA,
        live_status=status or live_status(),
        live_tools=tools or live_tools(),
        run_records=runs or [],
        approval_rows=[],
        audit_rows=audits or [],
        notes_text=notes,
        notes_path=notes_path,
        negative_journal_exists=journal_exists,
        notes_writable=notes_writable,
        journal_parent_writable=journal_parent_writable,
        now=NOW,
    )


passed = failed = 0


def check(condition: bool, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print("  PASS:", label)
    else:
        failed += 1
        print("  FAIL:", label)


errors, details = judge()
check(errors == [], "clean exact preflight is green")
check(details.get("production_activation") is False, "preflight can never activate production")

m = manifest()
m["runs"][0]["run_id"] = "already-used"
m["runs"][0]["bound_at"] = mod._iso(NOW)
errors, _ = judge(m=m)
check(any("already in use" in error for error in errors), "bound manifest is red")

identity = copy.deepcopy(IDENTITY)
identity["git_sha"] = "e" * 40
errors, _ = judge(identity=identity)
check(any("git_sha" in error for error in errors), "candidate SHA drift is red")

status = live_status()
status["write_approval_required"] = False
errors, _ = judge(status=status)
check(any("write_approval_required" in error for error in errors), "approval-required off is red")

tools = live_tools()
tools["tools"].append(
    {
        "name": "pull_model",
        "enabled": True,
        "risk": "write",
        "impact": "admin",
        "network": "configured_service",
        "idempotent": False,
    }
)
errors, _ = judge(tools=tools)
check(any("other write" in error for error in errors), "another enabled write tool is red")

marker = manifest()["runs"][0]["marker"]
errors, _ = judge(notes=marker + "\n")
check(any("notes.md already contains" in error for error in errors), "pre-existing note marker is red")

record = {
    "id": "hidden-run",
    "state": "completed",
    "payload": {"steps": [{"args": {"text": marker}}]},
    "events": [],
}
errors, _ = judge(runs=[record])
check(any("ledger already contains" in error for error in errors), "pre-existing pilot run is red")

active = {
    "id": "other-running",
    "state": "running",
    "payload": {"steps": [{"args": {"text": "other"}}]},
    "events": [],
}
errors, _ = judge(runs=[active])
check(any("not idle" in error for error in errors), "unrelated active Agent 3 run is red")

m = manifest()
m["created_at"] = mod._iso(NOW - timedelta(hours=13))
errors, _ = judge(m=m)
check(any("older than" in error for error in errors), "stale manifest is red")

errors, _ = judge(journal_exists=True)
check(any("journal already exists" in error for error in errors), "stale negative journal path is red")

errors, _ = judge(notes_path=Path("/tmp/other/notes.md"))
check(any("notes path" in error for error in errors), "notes path drift is red")

errors, _ = judge(notes_writable=False)
check(any("notes file/directory" in error for error in errors), "unwritable notes target is red")

errors, _ = judge(journal_parent_writable=False)
check(any("journal directory" in error for error in errors), "unwritable journal directory is red")

class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps({"ok": True}).encode()


observed = {}
original_urlopen = mod.urllib.request.urlopen


def fake_urlopen(request, timeout):
    observed["method"] = request.get_method()
    observed["authorization"] = request.get_header("Authorization")
    observed["timeout"] = timeout
    return FakeResponse()


try:
    mod.urllib.request.urlopen = fake_urlopen
    payload = mod._get_json("http://127.0.0.1:8080", "/status", "secret")
finally:
    mod.urllib.request.urlopen = original_urlopen

check(
    payload == {"ok": True}
    and observed == {
        "method": "GET",
        "authorization": "Bearer secret",
        "timeout": 8.0,
    },
    "live preflight transport is authenticated GET-only",
)

print(
    f"\n===== AGENT3 WRITE PILOT PREFLIGHT: "
    f"{passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)
