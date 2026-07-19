#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one target, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


script = "scripts/scheduler_pilot_evidence.py"
replace_once(
    script,
    '''MAX_JSON_BYTES = 256 * 1024
_HEX_32''',
    '''MAX_JSON_BYTES = 256 * 1024
MAX_PILOT_WINDOW_SECONDS = 12 * 60 * 60
MAX_EVIDENCE_AGE_SECONDS = 24 * 60 * 60
FUTURE_TOLERANCE_SECONDS = 5 * 60
_HEX_32''',
)
replace_once(
    script,
    '''    clean_claims = [item for item in all_claims if isinstance(item, str)]
    if len(clean_claims) != len(set(clean_claims)):
        errors.append("claim ids must be unique across all pilot trials")

    return {''',
    '''    clean_claims = [item for item in all_claims if isinstance(item, str)]
    if len(clean_claims) != len(set(clean_claims)):
        errors.append("claim ids must be unique across all pilot trials")
    schedule_ids = [
        normalized[name].get("schedule_id")
        for name in ("read", "write", "revoke", "recovery")
        if isinstance(normalized[name].get("schedule_id"), str)
    ]
    if len(schedule_ids) != len(set(schedule_ids)):
        errors.append("pilot trials must use four distinct schedule ids")

    return {''',
)
replace_once(
    script,
    '''def _audits(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT ts, conversation_id, tool, args_json, risk, outcome, "
        "confirmation_id, origin FROM audit WHERE conversation_id=? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _receipts''',
    '''def _audits(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT ts, conversation_id, tool, args_json, risk, outcome, "
        "confirmation_id, origin FROM audit WHERE conversation_id=? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _schedule_occurrence_ids(conn: sqlite3.Connection, schedule_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT claim_id FROM occurrences WHERE schedule_id=? ORDER BY created, claim_id",
        (schedule_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _blocked_schedule_audit(
    conn: sqlite3.Connection,
    schedule: dict[str, Any],
    *,
    window: dict[str, float],
    errors: list[str],
) -> dict[str, Any]:
    schedule_id = str(schedule.get("id") or "")
    rows = [
        row
        for row in _audits(conn, f"schedule:{schedule_id}")
        if row.get("outcome") == "blocked"
    ]
    result = {
        "binding": "schedule",
        "blocked_rows": len(rows),
        "claim_bound": False,
    }
    if len(rows) != 1:
        errors.append("revocation requires exactly one schedule-level blocked audit row")
        return result
    row = rows[0]
    if row.get("tool") != schedule.get("tool"):
        errors.append("revocation blocked audit tool mismatch")
    if row.get("origin") != "schedule":
        errors.append("revocation blocked audit origin is not schedule")
    try:
        audit_args = json.loads(row.get("args_json") or "")
    except json.JSONDecodeError:
        audit_args = None
    if not isinstance(audit_args, dict) or _json_sha(audit_args) != _json_sha(
        schedule.get("args_value")
    ):
        errors.append("revocation blocked audit args hash mismatch")
    audit_epoch = _audit_epoch(row.get("ts"))
    if audit_epoch is None or not _within_window(audit_epoch, window):
        errors.append("revocation blocked audit is outside the pilot window")
    return result


def _receipts''',
)
replace_once(
    script,
    '''    expected_candidate = normalized["candidate"]
    for key in ("version", "git_sha", "code_sha256"):''',
    '''    started_epoch = float(window["started_epoch"])
    finished_epoch = float(window["finished_epoch"])
    if finished_epoch - started_epoch > MAX_PILOT_WINDOW_SECONDS:
        errors.append("pilot window exceeds the 12-hour maximum")
    if finished_epoch > generated + FUTURE_TOLERANCE_SECONDS:
        errors.append("pilot window finishes in the future")
    if generated - finished_epoch > MAX_EVIDENCE_AGE_SECONDS:
        errors.append("pilot window is older than the 24-hour evidence limit")

    expected_candidate = normalized["candidate"]
    for key in ("version", "git_sha", "code_sha256"):''',
)
# Exact occurrence-set checks for each phase.
replace_once(
    script,
    '''        if read_schedule is not None:
            if not _within_window(read_schedule.get("created"), window):''',
    '''        if set(_schedule_occurrence_ids(schedules, read_spec["schedule_id"])) != set(
            read_spec["claim_ids"]
        ):
            read_errors.append("read schedule occurrence set does not match the manifest")
        if read_schedule is not None:
            if not _within_window(read_schedule.get("created"), window):''',
)
replace_once(
    script,
    '''        if write_schedule is not None:
            if not _within_window(write_schedule.get("created"), window):''',
    '''        if set(_schedule_occurrence_ids(schedules, write_spec["schedule_id"])) != set(
            write_spec["claim_ids"]
        ):
            write_errors.append("write schedule occurrence set does not match the manifest")
        if write_schedule is not None:
            if not _within_window(write_schedule.get("created"), window):''',
)
replace_once(
    script,
    '''            if not _within_window(receipt.get("consumed_at"), window):
                write_errors.append("write pilot receipt was not consumed inside the pilot window")
            nonce = receipt.get("nonce")''',
    '''            if not _within_window(receipt.get("issued_at"), window):
                write_errors.append("write pilot receipt was not issued inside the pilot window")
            if not _within_window(receipt.get("consumed_at"), window):
                write_errors.append("write pilot receipt was not consumed inside the pilot window")
            if write_schedule is not None and receipt.get("revision") != write_schedule.get("revision"):
                write_errors.append("write pilot receipt revision does not match the schedule")
            nonce = receipt.get("nonce")''',
)
replace_once(
    script,
    '''        revoke_claim = _claim_evidence(
            schedules,''',
    '''        if _schedule_occurrence_ids(schedules, revoke_spec["schedule_id"]) != [
            revoke_spec["claim_id"]
        ]:
            revoke_errors.append("revocation schedule occurrence set does not match the manifest")
        revoke_claim = _claim_evidence(
            schedules,''',
)
replace_once(
    script,
    '''        phases["revoke"] = {
            "passed": not revoke_errors,
            "errors": revoke_errors,
            "schedule_id": revoke_spec["schedule_id"],
            "claim": revoke_claim,
        }''',
    '''        revoke_audit = (
            _blocked_schedule_audit(
                audit, revoke_schedule, window=window, errors=revoke_errors
            )
            if revoke_schedule is not None
            else {"binding": "schedule", "blocked_rows": 0, "claim_bound": False}
        )
        phases["revoke"] = {
            "passed": not revoke_errors,
            "errors": revoke_errors,
            "schedule_id": revoke_spec["schedule_id"],
            "claim": revoke_claim,
            "audit": revoke_audit,
        }''',
)
replace_once(
    script,
    '''        recovery_claim = _claim_evidence(
            schedules,''',
    '''        if _schedule_occurrence_ids(schedules, recovery_spec["schedule_id"]) != [
            recovery_spec["claim_id"]
        ]:
            recovery_errors.append("recovery schedule occurrence set does not match the manifest")
        recovery_claim = _claim_evidence(
            schedules,''',
)

# Test: add the schedule-level blocked audit and negative cases.
test_path = Path("tests/workflow_scheduler_pilot_evidence.py")
test = test_path.read_text(encoding="utf-8")
anchor = '''    audit.execute(
        "INSERT INTO audit (ts,conversation_id,tool,args_json,risk,outcome,confirmation_id,origin) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            "1970-01-01T00:22:00",
            "schedule:write-schedule:occ:write-claim-1",
            "note_append",
            json.dumps(WRITE_ARGS),
            "write",
            "executed",
            f"schedule:{WRITE_FP[:12]}",
            "schedule",
        ),
    )
    audit.commit()'''
replacement = anchor.replace(
    "    audit.commit()",
    '''    audit.execute(
        "INSERT INTO audit (ts,conversation_id,tool,args_json,risk,outcome,confirmation_id,origin) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            "1970-01-01T00:23:22",
            "schedule:revoke-schedule",
            "rig_status",
            "{}",
            "read",
            "blocked",
            None,
            "schedule",
        ),
    )
    audit.commit()''',
)
if test.count(anchor) != 1:
    raise SystemExit("blocked-audit fixture anchor missing")
test = test.replace(anchor, replacement)
anchor = '''    bad_runtime = dict(RUNTIME, worker_code_sha256="d" * 64)'''
addition = '''    broad_manifest = manifest()
    broad_manifest["window"]["started_at"] = "1969-12-31T00:00:00+00:00"
    broad, broad_exit = pilot.collect_evidence(
        broad_manifest, candidate=CANDIDATE, runtime=RUNTIME, paths=paths, now=3_000.0
    )
    check(broad_exit == 1, "an over-broad pilot window is rejected")
    check("pilot window exceeds the 12-hour maximum" in broad["gate"]["errors"],
          "broad-window reason is explicit")

    future_manifest = manifest()
    future_manifest["window"]["finished_at"] = "1970-01-01T01:30:00+00:00"
    future, future_exit = pilot.collect_evidence(
        future_manifest, candidate=CANDIDATE, runtime=RUNTIME, paths=paths, now=3_000.0
    )
    check(future_exit == 1, "a future pilot window is rejected")
    check("pilot window finishes in the future" in future["gate"]["errors"],
          "future-window reason is explicit")

    bad_runtime = dict(RUNTIME, worker_code_sha256="d" * 64)'''
if test.count(anchor) != 1:
    raise SystemExit("window negative anchor missing")
test = test.replace(anchor, addition)
anchor = '''    inventory = pilot.inventory(paths)'''
addition = '''    schedules = sqlite3.connect(paths.schedules)
    schedules.execute(
        "INSERT INTO occurrences VALUES (?,?,?,?,?,?,?)",
        ("unexpected-read-claim", "read-schedule", 1_600.0, "released", 1_601.0, 1_602.0, "revoke-job-1"),
    )
    schedules.commit()
    schedules.close()
    extra, extra_exit = pilot.collect_evidence(
        manifest(), candidate=CANDIDATE, runtime=RUNTIME, paths=paths, now=3_000.0
    )
    check(extra_exit == 1, "an unlisted occurrence blocks pilot evidence")
    check(any("occurrence set" in error for error in extra["phases"]["read"]["errors"]),
          "unlisted occurrence explanation is explicit")

    inventory = pilot.inventory(paths)'''
if test.count(anchor) != 1:
    raise SystemExit("occurrence-set anchor missing")
test = test.replace(anchor, addition)
test_path.write_text(test, encoding="utf-8")

# Document the schedule-level audit limitation honestly.
doc = Path("SCHEDULER_PILOT_EVIDENCE.md")
text = doc.read_text(encoding="utf-8")
text = text.replace(
    '''- a revoked occurrence is released, terminal and has no executed audit;
- a recovered occurrence is exactly `executed` or `abandoned` as declared;''',
    '''- a revoked occurrence is released, terminal and has no executed audit;
- exactly one blocked audit exists for the revoked schedule inside the pilot
  window; current runtime records blocked audit at schedule scope, so the report
  explicitly states `claim_bound=false` rather than pretending claim-level binding;
- a recovered occurrence is exactly `executed` or `abandoned` as declared;''',
)
text = text.replace(
    '''- every named claim has one terminal occurrence and bound job;
- each executed claim has exactly one matching audit execution;''',
    '''- each pilot trial uses a distinct schedule and its complete occurrence set
  matches the manifest exactly;
- every named claim has one terminal occurrence and a job status consistent with
  the occurrence outcome;
- each executed claim has exactly one matching audit execution and args hash;''',
)
doc.write_text(text, encoding="utf-8")
