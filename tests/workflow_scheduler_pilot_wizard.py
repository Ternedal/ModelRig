#!/usr/bin/env python3
"""Run the retained scheduler pilot contract against candidate 1.58.145."""
from pathlib import Path

_source_path = Path(__file__).with_name("workflow_scheduler_pilot_wizard.retained")
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

_old_resume_contract = """module.REPORT_PATH.write_text(
    json.dumps({"candidate": {"git_sha": "a" * 40}, "pilot": {"passed": True}}),
    encoding="utf-8",
)
check(module.existing_report_passed("a" * 40), "passed report resumes on the same SHA")
check(not module.existing_report_passed("b" * 40), "report cannot cross SHA")
"""

_new_resume_contract = """identity = {
    "version": module.VERSION,
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "branch": module.BRANCH,
    "working_tree_clean": True,
    "version_stamps_consistent": True,
}
module._current_candidate_identity = lambda: dict(identity)
now = datetime.now(timezone.utc)

module.REPORT_PATH.write_text(
    json.dumps({"candidate": {"git_sha": "a" * 40}, "pilot": {"passed": True}}),
    encoding="utf-8",
)
check(
    not module.existing_report_passed("a" * 40),
    "minimal hand-written passed report is rejected",
)

valid_report = {
    "schema": "kaliv-scheduler-pilot/v4",
    "generated_at": now.isoformat(),
    "candidate": {
        "version": module.VERSION,
        "git_sha": "a" * 40,
        "code_sha256": "b" * 64,
    },
    "pilot": {"passed": True, "problems": []},
}
module.REPORT_PATH.write_text(json.dumps(valid_report), encoding="utf-8")
check(
    module.existing_report_passed("a" * 40),
    "fresh full report resumes on the exact current identity",
)
check(not module.existing_report_passed("b" * 40), "report cannot cross SHA")

valid_report["candidate"]["version"] = "0.0.0"
module.REPORT_PATH.write_text(json.dumps(valid_report), encoding="utf-8")
check(not module.existing_report_passed("a" * 40), "version mismatch is rejected")
valid_report["candidate"]["version"] = module.VERSION

valid_report["candidate"]["code_sha256"] = "c" * 64
module.REPORT_PATH.write_text(json.dumps(valid_report), encoding="utf-8")
check(not module.existing_report_passed("a" * 40), "code fingerprint mismatch is rejected")
valid_report["candidate"]["code_sha256"] = "b" * 64

valid_report["generated_at"] = (now - timedelta(hours=25)).isoformat()
module.REPORT_PATH.write_text(json.dumps(valid_report), encoding="utf-8")
check(not module.existing_report_passed("a" * 40), "stale report is rejected")
valid_report["generated_at"] = now.isoformat()

valid_report["pilot"]["problems"] = ["tampered"]
module.REPORT_PATH.write_text(json.dumps(valid_report), encoding="utf-8")
check(not module.existing_report_passed("a" * 40), "non-empty problems are rejected")
valid_report["pilot"]["problems"] = []

identity["working_tree_clean"] = False
module.REPORT_PATH.write_text(json.dumps(valid_report), encoding="utf-8")
check(not module.existing_report_passed("a" * 40), "dirty current tree is rejected")
identity["working_tree_clean"] = True
"""

if _old_resume_contract not in _source:
    raise RuntimeError("retained scheduler resume contract changed unexpectedly")
_source = _source.replace(_old_resume_contract, _new_resume_contract)

exec(compile(_source, str(_source_path), "exec"), globals(), globals())
