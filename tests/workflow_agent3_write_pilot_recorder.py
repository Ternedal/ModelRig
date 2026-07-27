from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("t022_recorder", SCRIPTS / "agent3_write_pilot_journal_cases.py")
rec = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rec
assert spec.loader
spec.loader.exec_module(rec)

report_spec = importlib.util.spec_from_file_location(
    "t022_report_for_recorder", SCRIPTS / "agent3_write_pilot_report.py"
)
report = importlib.util.module_from_spec(report_spec)
sys.modules[report_spec.name] = report
assert report_spec.loader
report_spec.loader.exec_module(report)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def manifest_value():
    pilot_id = "a" * 32
    prefix = f"KALIV-T022:{pilot_id}:P:"
    return {
        "schema": "kaliv-agent3-write-pilot-manifest/v1",
        "pilot_id": pilot_id,
        "created_at": "2026-07-27T11:00:00Z",
        "operator": "Anders",
        "target": {
            "version": "1.58.146",
            "git_sha": "b" * 40,
            "code_sha256": "c" * 64,
            "identity_source": "git",
            "rig_validation_report_sha256": "d" * 64,
        },
        "marker_prefix": prefix,
        "runs": [
            {
                "ordinal": i,
                "marker": f"{prefix}{i:02d}:{i:032x}",
                "run_id": f"run-{i}",
                "bound_at": "2026-07-27T11:10:00Z",
            }
            for i in range(1, 21)
        ],
    }


def write_json(path: Path, value):
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def build_complete(td: Path):
    manifest_path = td / "manifest.json"
    journal = td / "journal.db"
    output = td / "negative.json"
    write_json(manifest_path, manifest_value())
    rec._init(journal, manifest_path, now=NOW)

    specs = {
        "deny": ([200], 0, 0, 0, 0, None),
        "timeout": ([409], 0, 0, 0, 0, None),
        "changed_args": ([409], 0, 0, 0, 0, None),
        "stale_revision": ([409], 0, 0, 0, 0, None),
        "replay": ([409], 1, 1, 1, 1, 3),
        "concurrent_approval": ([200, 409], 0, 1, 0, 1, None),
        "stop_retry_replan": ([200, 202, 409], 1, 1, 1, 1, 4),
    }
    case_ids = {}
    minute = 1
    for name in rec._NEGATIVE_CASES:
        statuses, nb, na, ab, aa, ordinal = specs[name]
        case_id, marker = rec.begin_case(
            journal=journal,
            manifest_path=manifest_path,
            name=name,
            note_count=nb,
            approval_count=ab,
            positive_ordinal=ordinal,
            now=NOW.replace(minute=minute),
        )
        case_ids[name] = (case_id, marker)
        for index, status in enumerate(statuses):
            response = td / f"{name}-{index}.response"
            response.write_bytes(f"{name}:{status}:{index}".encode())
            rec.observe_request(
                journal=journal,
                case_id=case_id,
                status=status,
                response_path=response,
                run_id=("neg-concurrent" if name == "concurrent_approval" else f"{name}-run-{index}"),
                now=NOW.replace(minute=minute, second=10 + index),
            )
        rec.finish_case(
            journal=journal,
            case_id=case_id,
            note_count=na,
            approval_count=aa,
            now=NOW.replace(minute=minute, second=40),
        )
        minute += 1
    negative = rec.finalize(journal, manifest_path)
    rec._atomic_json(output, negative)
    return manifest_path, journal, output, negative, case_ids


passed = failed = 0


def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
        print("  PASS:", label)
    else:
        failed += 1
        print("  FAIL:", label)


with tempfile.TemporaryDirectory(prefix="t022-recorder-") as raw:
    td = Path(raw)
    manifest_path, journal, output, negative, cases = build_complete(td)
    rows, final_sha = rec.verify_journal(journal)
    check(len(final_sha) == 64, "journal final hash is a complete SHA-256")
    check([case["name"] for case in negative["cases"]] == list(rec._NEGATIVE_CASES), "all seven cases retain operator order")
    check(negative["cases"][4]["marker"] == manifest_value()["runs"][2]["marker"], "replay targets a positive marker")
    check(negative["cases"][6]["marker"] == manifest_value()["runs"][3]["marker"], "stop/retry/replan targets a positive marker")
    check(output.is_file() and output.read_text(encoding="utf-8").endswith("\n"), "negative evidence is written atomically as UTF-8 JSON")
    loaded = report.load_bound_negative_evidence(
        manifest_path=manifest_path,
        negative_path=output,
        negative_journal_path=journal,
    )
    check(loaded[-1] == final_sha, "collector accepts only the matching journal final hash")
    drifted = json.loads(output.read_text(encoding="utf-8"))
    drifted["cases"][0]["response_sha256s"][0] = "0" * 64
    write_json(output, drifted)
    error = None
    try:
        report.load_bound_negative_evidence(
            manifest_path=manifest_path,
            negative_path=output,
            negative_journal_path=journal,
        )
    except Exception as exc:
        error = exc
    check(isinstance(error, report.PilotEvidenceError), "collector rejects a negative file detached from its journal")

with tempfile.TemporaryDirectory(prefix="t022-recorder-tamper-") as raw:
    td = Path(raw)
    manifest_path, journal, _output, _negative, _cases = build_complete(td)
    conn = sqlite3.connect(journal)
    conn.execute("UPDATE records SET payload='{}' WHERE seq=2")
    conn.commit(); conn.close()
    error = None
    try:
        rec.verify_journal(journal)
    except Exception as exc:
        error = exc
    check(isinstance(error, rec.RecorderError) and "hash" in str(error), "payload tampering breaks the journal chain")

with tempfile.TemporaryDirectory(prefix="t022-recorder-order-") as raw:
    td = Path(raw)
    manifest_path = td / "manifest.json"; write_json(manifest_path, manifest_value())
    journal = td / "journal.db"; rec._init(journal, manifest_path, now=NOW)
    case_id, _marker = rec.begin_case(
        journal=journal, manifest_path=manifest_path, name="deny",
        note_count=0, approval_count=0, now=NOW,
    )
    error = None
    try:
        rec.finish_case(journal=journal, case_id=case_id, note_count=0, approval_count=0, now=NOW)
    except Exception as exc:
        error = exc
    check(isinstance(error, rec.RecorderError), "a case cannot finish before a response is observed")
    error = None
    try:
        rec.begin_case(
            journal=journal, manifest_path=manifest_path, name="deny",
            note_count=0, approval_count=0, now=NOW,
        )
    except Exception as exc:
        error = exc
    check(isinstance(error, rec.RecorderError) and "already" in str(error), "a negative case cannot be started twice")

with tempfile.TemporaryDirectory(prefix="t022-recorder-drift-") as raw:
    td = Path(raw)
    manifest_path = td / "manifest.json"; write_json(manifest_path, manifest_value())
    journal = td / "journal.db"; rec._init(journal, manifest_path, now=NOW)
    drifted = manifest_value(); drifted["operator"] = "Someone else"; write_json(manifest_path, drifted)
    error = None
    try:
        rec.begin_case(
            journal=journal, manifest_path=manifest_path, name="deny",
            note_count=0, approval_count=0, now=NOW,
        )
    except Exception as exc:
        error = exc
    check(isinstance(error, rec.RecorderError) and "another manifest" in str(error), "manifest drift is rejected before recording")

print(f"\n===== AGENT3 WRITE PILOT RECORDER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
