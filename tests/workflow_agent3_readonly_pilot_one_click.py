#!/usr/bin/env python3
"""Run the retained Agent 3 pilot contract against candidate 1.58.145."""
from pathlib import Path

_source_path = Path(__file__).with_name("workflow_agent3_readonly_pilot_one_click.retained")
_source = _source_path.read_text(encoding="utf-8")
for _old, _new in (
    ("agent/unified-candidate-1.58.143", "agent/unified-candidate-1.58.145"),
    ("1.58.143", "1.58.145"),
    ("1.58.142", "1.58.144"),
    ("#150", "#161"),
):
    _source = _source.replace(_old, _new)

_source = _source.replace(
    "import tempfile\n",
    "import tempfile\nfrom datetime import datetime, timedelta, timezone\n",
)

_old_passing_report = """def passing_report(module, sha: str) -> dict:
    return {
        "schema": module.SCHEMA,
        "success": True,
        "candidate": {"git_sha": sha, "version": module.VERSION},
        "target": {"production_activation": False},
        "summary": {"tasks": 20, "successes": 20, "failures": 0, "error_types": {}},
        "stop_fallback": {"success": True, "fallback_path": "/api/v1/chat"},
    }
"""

_new_passing_report = """def passing_report(module, sha: str) -> dict:
    now = datetime.now(timezone.utc)
    code_sha256 = "b" * 64
    return {
        "schema": module.SCHEMA,
        "started_at": (now - timedelta(minutes=5)).isoformat(),
        "finished_at": now.isoformat(),
        "success": True,
        "candidate": {
            "git_sha": sha,
            "version": module.VERSION,
            "code_sha256": code_sha256,
        },
        "target": {
            "execution_mode": "experimental-read-only",
            "production_activation": False,
        },
        "backend": {
            "worker_version": module.VERSION,
            "code_sha256": code_sha256,
            "production_tools_path_untouched": True,
            "production_activation": False,
            "rig_validation": {
                "eligible_for_developer_preview": True,
                "version_match": True,
                "code_match": True,
            },
        },
        "task_set": {
            "schema": "kaliv-agent3-readonly-pilot-task-set/v1",
            "name": "agent3-readonly-developer-pilot-da",
            "version": "2026-07-19.1",
            "task_count": 20,
            "sha256": "d" * 64,
        },
        "summary": {
            "tasks": 20,
            "successes": 20,
            "failures": 0,
            "error_types": {},
            "retry_events": 0,
        },
        "stop_fallback": {
            "success": True,
            "fallback_path": "/api/v1/chat",
            "agent3_state": "cancelled",
            "completed_agent3_steps": 1,
            "pending_steps_after_stop": 1,
        },
        "results": [
            {"task_id": f"{index:02d}", "success": True}
            for index in range(1, 21)
        ],
    }
"""

if _old_passing_report not in _source:
    raise RuntimeError("retained Agent 3 passing report fixture changed unexpectedly")
_source = _source.replace(_old_passing_report, _new_passing_report)

_old_module_setup = """module = load_module()
check(module.BRANCH == "agent/unified-candidate-1.58.145", "operator is pinned to the combined physical branch")
check(module.VERSION == "1.58.145", "operator is pinned to version 1.58.145")
sha = "a" * 40
good = passing_report(module, sha)
check(module.report_passes(good, sha), "exact-SHA 20/20 report passes")
for label, mutate in (
    ("wrong SHA", lambda report: report["candidate"].update(git_sha="b" * 40)),
    ("19/20", lambda report: report["summary"].update(successes=19, failures=1)),
    ("production activation", lambda report: report["target"].update(production_activation=True)),
    ("missing fallback", lambda report: report["stop_fallback"].update(success=False)),
):
    changed = json.loads(json.dumps(good))
    mutate(changed)
    check(not module.report_passes(changed, sha), f"{label} is rejected")
"""

_new_module_setup = """module = load_module()
check(module.BRANCH == "agent/unified-candidate-1.58.145", "operator is pinned to the combined physical branch")
check(module.VERSION == "1.58.145", "operator is pinned to version 1.58.145")
sha = "a" * 40
identity = {
    "version": module.VERSION,
    "git_sha": sha,
    "code_sha256": "b" * 64,
    "branch": module.BRANCH,
    "working_tree_clean": True,
    "version_stamps_consistent": True,
}
task_identity = {
    "schema": "kaliv-agent3-readonly-pilot-task-set/v1",
    "name": "agent3-readonly-developer-pilot-da",
    "version": "2026-07-19.1",
    "task_count": 20,
    "sha256": "d" * 64,
    "task_ids": [f"{index:02d}" for index in range(1, 21)],
}
module._current_candidate_identity = lambda: dict(identity)
module._expected_task_set_identity = lambda: dict(task_identity)

minimal = {
    "schema": module.SCHEMA,
    "success": True,
    "candidate": {"git_sha": sha, "version": module.VERSION},
    "target": {"production_activation": False},
    "summary": {"tasks": 20, "successes": 20, "failures": 0, "error_types": {}},
    "stop_fallback": {"success": True, "fallback_path": "/api/v1/chat"},
}
check(not module.report_passes(minimal, sha), "minimal hand-written report is rejected")

good = passing_report(module, sha)
check(module.report_passes(good, sha), "fresh exact-identity 20/20 report passes")
for label, mutate in (
    ("wrong SHA", lambda report: report["candidate"].update(git_sha="b" * 40)),
    ("wrong code fingerprint", lambda report: report["candidate"].update(code_sha256="c" * 64)),
    ("19/20", lambda report: report["summary"].update(successes=19, failures=1)),
    ("retry event", lambda report: report["summary"].update(retry_events=1)),
    ("production activation", lambda report: report["target"].update(production_activation=True)),
    ("missing fallback", lambda report: report["stop_fallback"].update(success=False)),
    ("wrong task set", lambda report: report["task_set"].update(sha256="e" * 64)),
    (
        "stale report",
        lambda report: report.update(
            finished_at=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        ),
    ),
):
    changed = json.loads(json.dumps(good))
    mutate(changed)
    check(not module.report_passes(changed, sha), f"{label} is rejected")

identity["working_tree_clean"] = False
check(not module.report_passes(good, sha), "dirty current tree is rejected")
identity["working_tree_clean"] = True
"""

if _old_module_setup not in _source:
    raise RuntimeError("retained Agent 3 report contract changed unexpectedly")
_source = _source.replace(_old_module_setup, _new_module_setup)

exec(compile(_source, str(_source_path), "exec"), globals(), globals())
