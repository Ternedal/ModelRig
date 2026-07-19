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
    "from dataclasses import dataclass\nfrom pathlib import Path",
    "from dataclasses import dataclass\nfrom datetime import datetime, timezone\nfrom pathlib import Path",
)
replace_once(
    script,
    '''def _claim_ids(value: Any, label: str, errors: list[str]) -> list[str]:''',
    '''def _iso_epoch(value: Any, label: str, errors: list[str]) -> float | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be an ISO-8601 datetime with offset")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label} must be an ISO-8601 datetime with offset")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{label} must include a timezone offset")
        return None
    return parsed.astimezone(timezone.utc).timestamp()


def _audit_epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def _within_window(value: Any, window: dict[str, float]) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and window["started_epoch"] <= float(value) <= window["finished_epoch"]
    )


def _claim_ids(value: Any, label: str, errors: list[str]) -> list[str]:''',
)
replace_once(
    script,
    '''    trials = value.get("trials")
    if not isinstance(trials, dict):''',
    '''    window_raw = value.get("window")
    if not isinstance(window_raw, dict):
        errors.append("manifest.window must be an object")
        window_raw = {}
    started_epoch = _iso_epoch(window_raw.get("started_at"), "window.started_at", errors)
    finished_epoch = _iso_epoch(window_raw.get("finished_at"), "window.finished_at", errors)
    if (
        started_epoch is not None
        and finished_epoch is not None
        and started_epoch >= finished_epoch
    ):
        errors.append("window.started_at must be before window.finished_at")

    trials = value.get("trials")
    if not isinstance(trials, dict):''',
)
replace_once(
    script,
    '''        "candidate": dict(candidate),
        "trials": normalized,
    }, errors''',
    '''        "candidate": dict(candidate),
        "window": {
            "started_at": window_raw.get("started_at"),
            "finished_at": window_raw.get("finished_at"),
            "started_epoch": started_epoch,
            "finished_epoch": finished_epoch,
        },
        "trials": normalized,
    }, errors''',
)
replace_once(
    script,
    '''    expected_confirmation: str | None,
    errors: list[str],
) -> dict[str, Any]:''',
    '''    expected_confirmation: str | None,
    expected_args_sha256: str | None,
    window: dict[str, float],
    errors: list[str],
) -> dict[str, Any]:''',
)
replace_once(
    script,
    '''    if status not in _TERMINAL_OCCURRENCES:
        errors.append(f"claim {claim_id}: occurrence is not terminal")

    job_id = occurrence.get("job_id")''',
    '''    if status not in _TERMINAL_OCCURRENCES:
        errors.append(f"claim {claim_id}: occurrence is not terminal")
    if not _within_window(occurrence.get("created"), window):
        errors.append(f"claim {claim_id}: occurrence was not created inside the pilot window")
    if not _within_window(occurrence.get("resolved"), window):
        errors.append(f"claim {claim_id}: occurrence was not resolved inside the pilot window")

    job_id = occurrence.get("job_id")''',
)
replace_once(
    script,
    '''        if job.get("status") not in _TERMINAL_JOBS:
            errors.append(f"claim {claim_id}: job is not terminal")
        if f"occ={claim_id}" not in str(job.get("detail") or ""):
            errors.append(f"claim {claim_id}: job detail is not occurrence-bound")

    conversation_id = f"schedule:{schedule_id}:occ:{claim_id}"''',
    '''        if job.get("status") not in _TERMINAL_JOBS:
            errors.append(f"claim {claim_id}: job is not terminal")
        expected_job_states = {
            "executed": {"completed"},
            "released": {"cancelled", "failed"},
            "abandoned": {"failed", "interrupted"},
        }[expected_status]
        if job.get("status") not in expected_job_states:
            errors.append(
                f"claim {claim_id}: job status {job.get('status')!r} "
                f"does not match occurrence status {expected_status!r}"
            )
        if not _within_window(job.get("created"), window):
            errors.append(f"claim {claim_id}: job was not created inside the pilot window")
        if not _within_window(job.get("updated"), window):
            errors.append(f"claim {claim_id}: job was not finalized inside the pilot window")

    conversation_id = f"schedule:{schedule_id}:occ:{claim_id}"''',
)
replace_once(
    script,
    '''            if row.get("confirmation_id") != expected_confirmation:
                errors.append(f"claim {claim_id}: audit confirmation binding mismatch")
    elif executed:''',
    '''            if row.get("confirmation_id") != expected_confirmation:
                errors.append(f"claim {claim_id}: audit confirmation binding mismatch")
            audit_epoch = _audit_epoch(row.get("ts"))
            if audit_epoch is None or not _within_window(audit_epoch, window):
                errors.append(f"claim {claim_id}: audit execution is outside the pilot window")
            try:
                audit_args = json.loads(row.get("args_json") or "")
            except json.JSONDecodeError:
                audit_args = None
            if (
                expected_args_sha256 is not None
                and (not isinstance(audit_args, dict) or _json_sha(audit_args) != expected_args_sha256)
            ):
                errors.append(f"claim {claim_id}: audit args hash mismatch")
    elif executed:''',
)
replace_once(
    script,
    '''    normalized, errors = validate_manifest(manifest)
    expected_candidate = normalized["candidate"]''',
    '''    normalized, errors = validate_manifest(manifest)
    window = normalized["window"]
    if not isinstance(window.get("started_epoch"), (int, float)) or not isinstance(
        window.get("finished_epoch"), (int, float)
    ):
        # Keep later checks deterministic even for a malformed manifest.
        window = {"started_epoch": math.inf, "finished_epoch": -math.inf}
    expected_candidate = normalized["candidate"]''',
)
replace_once(
    script,
    '''    if runtime.get("worker_code_sha256") != candidate["code_sha256"]:
        errors.append("worker code fingerprint does not match the checkout")
    if runtime.get("scheduler_configured") is not True:''',
    '''    if runtime.get("worker_code_sha256") != candidate["code_sha256"]:
        errors.append("worker code fingerprint does not match the checkout")
    if runtime.get("worker_frozen") is not True:
        errors.append("worker is not the packaged appliance build")
    if runtime.get("scheduler_configured") is not True:''',
)
replace_once(
    script,
    '''        if read_schedule is not None:
            if read_schedule.get("runs_used") != len(read_claims):''',
    '''        if read_schedule is not None:
            if not _within_window(read_schedule.get("created"), window):
                read_errors.append("read schedule was not created inside the pilot window")
            if read_schedule.get("runs_used") != len(read_claims):''',
)
# Add new claim arguments to every call.
text_path = Path(script)
text = text_path.read_text(encoding="utf-8")
text = text.replace(
    '''                expected_confirmation=None,
                errors=read_errors,''',
    '''                expected_confirmation=None,
                expected_args_sha256=read_spec["args_sha256"],
                window=window,
                errors=read_errors,''',
)
text = text.replace(
    '''                expected_confirmation=confirmation,
                errors=write_errors,''',
    '''                expected_confirmation=confirmation,
                expected_args_sha256=write_spec["args_sha256"],
                window=window,
                errors=write_errors,''',
)
text = text.replace(
    '''            expected_confirmation=None,
            errors=revoke_errors,''',
    '''            expected_confirmation=None,
            expected_args_sha256=None,
            window=window,
            errors=revoke_errors,''',
)
text = text.replace(
    '''            expected_confirmation=(
                None
                if (recovery_schedule or {}).get("approved_fingerprint") is None
                else f"schedule:{str((recovery_schedule or {}).get('approved_fingerprint'))[:12]}"
            ),
            errors=recovery_errors,''',
    '''            expected_confirmation=(
                None
                if (recovery_schedule or {}).get("approved_fingerprint") is None
                else f"schedule:{str((recovery_schedule or {}).get('approved_fingerprint'))[:12]}"
            ),
            expected_args_sha256=(
                _json_sha((recovery_schedule or {}).get("args_value"))
                if isinstance((recovery_schedule or {}).get("args_value"), dict)
                else None
            ),
            window=window,
            errors=recovery_errors,''',
)
text_path.write_text(text, encoding="utf-8")

replace_once(
    script,
    '''        if write_schedule is not None:
            args = write_schedule.get("args_value")''',
    '''        if write_schedule is not None:
            if not _within_window(write_schedule.get("created"), window):
                write_errors.append("write schedule was not created inside the pilot window")
            args = write_schedule.get("args_value")''',
)
replace_once(
    script,
    '''            if receipt.get("device_id") != write_spec["device_id"]:
                write_errors.append("write pilot receipt device mismatch")''',
    '''            if receipt.get("device_id") != write_spec["device_id"]:
                write_errors.append("write pilot receipt device mismatch")
            if not _within_window(receipt.get("consumed_at"), window):
                write_errors.append("write pilot receipt was not consumed inside the pilot window")''',
)
replace_once(
    script,
    '''        if revoke_schedule is None:
            revoke_errors.append("revocation schedule does not exist")
        elif bool(revoke_schedule.get("enabled")):''',
    '''        if revoke_schedule is None:
            revoke_errors.append("revocation schedule does not exist")
        elif not _within_window(revoke_schedule.get("created"), window):
            revoke_errors.append("revocation schedule was not created inside the pilot window")
        elif bool(revoke_schedule.get("enabled")):''',
)
replace_once(
    script,
    '''        if recovery_schedule is None:
            recovery_errors.append("recovery schedule does not exist")
        recovery_claim = _claim_evidence(''',
    '''        if recovery_schedule is None:
            recovery_errors.append("recovery schedule does not exist")
        elif not _within_window(recovery_schedule.get("created"), window):
            recovery_errors.append("recovery schedule was not created inside the pilot window")
        recovery_claim = _claim_evidence(''',
)
replace_once(
    script,
    '''        "candidate": dict(candidate),
        "runtime": {''',
    '''        "candidate": dict(candidate),
        "pilot_window": {
            "started_at": normalized["window"].get("started_at"),
            "finished_at": normalized["window"].get("finished_at"),
        },
        "runtime": {''',
)

# Manifest example.
example = Path("eval/scheduler_pilot_manifest.example.json")
data = __import__("json").loads(example.read_text(encoding="utf-8"))
data["window"] = {
    "started_at": "FILL_ME_ISO_8601_WITH_OFFSET",
    "finished_at": "FILL_ME_ISO_8601_WITH_OFFSET",
}
# Keep window near candidate before trials when serialized.
ordered = {
    "schema": data["schema"],
    "candidate": data["candidate"],
    "window": data["window"],
    "trials": data["trials"],
}
example.write_text(__import__("json").dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Test fixture and negative freshness case.
test = Path("tests/workflow_scheduler_pilot_evidence.py")
text = test.read_text(encoding="utf-8")
text = text.replace(
    '''        "candidate": dict(CANDIDATE),
        "trials": {''',
    '''        "candidate": dict(CANDIDATE),
        "window": {
            "started_at": "1970-01-01T00:15:00+00:00",
            "finished_at": "1970-01-01T00:42:00+00:00",
        },
        "trials": {''',
    1,
)
text = text.replace('"2026-07-19T01:00:00"', '"1970-01-01T00:20:00"')
text = text.replace('"2026-07-19T01:02:00"', '"1970-01-01T00:22:00"')
text = text.replace('"2026-07-19T01:02:01"', '"1970-01-01T00:22:01"')
anchor = '''    bad_runtime = dict(RUNTIME, worker_code_sha256="d" * 64)'''
addition = '''    stale_manifest = manifest()
    stale_manifest["window"]["started_at"] = "1970-01-01T00:30:00+00:00"
    stale, stale_exit = pilot.collect_evidence(
        stale_manifest, candidate=CANDIDATE, runtime=RUNTIME, paths=paths, now=3_000.0
    )
    check(stale_exit == 1, "claims outside the declared pilot window are rejected")
    check(any(
              "outside the pilot window" in error
              for error in stale["phases"]["read"]["errors"]),
          "stale claim explanation is explicit")

    bad_runtime = dict(RUNTIME, worker_code_sha256="d" * 64)'''
if text.count(anchor) != 1:
    raise SystemExit("test freshness anchor missing")
text = text.replace(anchor, addition)
# Add non-frozen runtime negative case.
anchor = '''    notes_original = paths.notes.read_text(encoding="utf-8")'''
addition = '''    source_runtime = dict(RUNTIME, worker_frozen=False)
    source_build, source_build_exit = pilot.collect_evidence(
        manifest(), candidate=CANDIDATE, runtime=source_runtime, paths=paths, now=3_000.0
    )
    check(source_build_exit == 1, "source-mode worker cannot satisfy appliance pilot evidence")
    check("worker is not the packaged appliance build" in source_build["gate"]["errors"],
          "packaged-worker requirement is explicit")

    notes_original = paths.notes.read_text(encoding="utf-8")'''
if text.count(anchor) != 1:
    raise SystemExit("test frozen anchor missing")
text = text.replace(anchor, addition)
test.write_text(text, encoding="utf-8")

# Runbook additions.
doc = Path("SCHEDULER_PILOT_EVIDENCE.md")
text = doc.read_text(encoding="utf-8")
text = text.replace(
    '''- candidate VERSION, `git rev-parse HEAD` and worker code fingerprint;
- exact schedule and claim ids from the inventory;''',
    '''- candidate VERSION, `git rev-parse HEAD` and worker code fingerprint;
- the UTC pilot start/end timestamps with offsets; every named schedule, claim,
  job, audit execution and write receipt must fall inside this window;
- exact schedule and claim ids from the inventory;''',
)
text = text.replace(
    '''- candidate and runtime identities match;
- read has zero receipts;''',
    '''- candidate and runtime identities match and `worker_frozen=true`;
- every evidence timestamp falls within the declared pilot window;
- read has zero receipts;''',
)
doc.write_text(text, encoding="utf-8")
