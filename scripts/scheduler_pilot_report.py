"""Scheduler-pilot evidence for the physical validation campaign (T-019).

Runs AFTER the DEVICE_TEST section 1.6 pilot and turns what the pilot left
behind into a campaign evidence file: the read schedule ran without any
approval (by design), the write schedule ran under a receipt that names the
approving device and times, and the operator confirms the two dynamic
observations a later API read cannot see -- the mid-flight revocation card and
the startup recovery line.

The machine half is read over loopback from the worker; the human half comes
from a small manual-observations JSON, mirroring the voice baseline's pattern.
The campaign aggregator (scripts/physical_validation_campaign.py) validates
the result against the frozen candidate like every other slot.

Usage (on the rig, after the 1.6 pilot):

    python scripts\\scheduler_pilot_report.py ^
        --worker-url http://127.0.0.1:8099 ^
        --read-schedule-id <ID> --write-schedule-id <ID> ^
        --manual-observations validation\\scheduler-manual-observations.json ^
        --report validation\\scheduler-pilot-latest.json

The manual-observations file:

    {"revocation_confirmed": true,
     "recovery_line": "scheduler: recovered 0 executed / 1 abandoned ...",
     "operator": "Anders"}
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "kaliv-scheduler-pilot/v2"
ROOT = Path(__file__).resolve().parent.parent


def _load_campaign():
    path = Path(__file__).resolve().parent / "physical_validation_campaign.py"
    spec = importlib.util.spec_from_file_location("pvc_for_pilot", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _ro(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def read_forensics(schedules_db: str, jobs_db: str, audit_db: str,
                   schedule_id: str) -> dict[str, Any]:
    """The durable rows behind ONE schedule's pilot run, read straight from
    the stores (read-only URIs). Aggregate counters prove that SOMETHING ran;
    a promotion proof must pin the exact occurrences, their jobs, their audit
    sequence and the receipt -- this is that pin (F-1206)."""
    sc = _ro(schedules_db)
    row = sc.execute(
        "SELECT tool, args, cadence, max_runs, runs_used, revision, enabled, "
        "approved_fingerprint FROM schedules WHERE id=?",
        (schedule_id,)).fetchone()
    schedule = dict(row) if row else None
    occs = [dict(r) for r in sc.execute(
        "SELECT claim_id, status, occurrence_due_at, created, resolved, "
        "job_id FROM occurrences WHERE schedule_id=? ORDER BY created",
        (schedule_id,))]
    receipts = [dict(r) for r in sc.execute(
        "SELECT kind, device_id, nonce, issued_at, consumed_at, revision, "
        "fingerprint FROM approval_receipts WHERE schedule_id=? ORDER BY id",
        (schedule_id,))]
    sc.close()

    jb = _ro(jobs_db)
    au = _ro(audit_db)
    for occ in occs:
        if occ.get("job_id"):
            j = jb.execute("SELECT status, detail FROM jobs WHERE id=?",
                           (occ["job_id"],)).fetchone()
            occ["job"] = dict(j) if j else None
        conv = f"schedule:{schedule_id}:occ:{occ['claim_id']}"
        occ["audit_outcomes"] = [
            r["outcome"] for r in au.execute(
                "SELECT outcome FROM audit WHERE conversation_id=? "
                "ORDER BY id", (conv,))]
    jb.close()
    au.close()

    created = [o["created"] for o in occs]
    resolved = [o["resolved"] for o in occs if o.get("resolved")]
    return {
        "schedule": schedule,
        "occurrences": occs,
        "receipts": receipts,
        "window": {
            "first_created": min(created) if created else None,
            "last_resolved": max(resolved) if resolved else None,
        },
    }


def fetch_json(url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def judge(read_detail: dict[str, Any], write_detail: dict[str, Any],
          manual: dict[str, Any],
          read_forensics_data: dict[str, Any] | None = None,
          write_forensics_data: dict[str, Any] | None = None) -> list[str]:
    """Every reason the pilot does NOT hold. Empty list == the pilot holds."""
    problems: list[str] = []

    if read_forensics_data is not None:
        r_occs = read_forensics_data.get("occurrences") or []
        if not any(o.get("status") == "executed" for o in r_occs):
            problems.append(
                "forensik: read-planen har ingen 'executed' occurrence -- "
                "aggregatet kan ikke pege på et bestemt forloeb")
        if not any(o.get("status") == "released"
                   and (o.get("job") or {}).get("status") == "cancelled"
                   for o in r_occs):
            problems.append(
                "forensik: pausens bevis mangler -- ingen released "
                "occurrence med et cancelled job paa read-planen")
    if write_forensics_data is not None:
        w_occs = write_forensics_data.get("occurrences") or []
        good = [o for o in w_occs if o.get("status") == "executed"
                and "attempt" in (o.get("audit_outcomes") or [])
                and "executed" in (o.get("audit_outcomes") or [])]
        if not good:
            problems.append(
                "forensik: ingen write-occurrence med baade attempt- og "
                "executed-audit -- kaeden claim->attempt->executed er ikke "
                "bevist for et konkret forloeb")
        elif not any((o.get("job") or {}).get("status") == "completed"
                     for o in good):
            problems.append(
                "forensik: den beviste write-occurrence er ikke bundet til "
                "et completed job")
        if not (write_forensics_data.get("receipts") or []):
            problems.append(
                "forensik: ingen receipt-raekke i storen for write-planen")

    r_sched = read_detail.get("schedule") or {}
    r_receipts = read_detail.get("approval_receipts")
    if not isinstance(r_sched.get("runs_used"), int) or r_sched["runs_used"] < 1:
        problems.append("read-planen har aldrig kørt (runs_used < 1)")
    if r_receipts != []:
        problems.append(
            "read-planen har approval_receipts -- reads skal pr. design "
            "ingen have")

    w_sched = write_detail.get("schedule") or {}
    w_receipts = write_detail.get("approval_receipts")
    if not isinstance(w_sched.get("runs_used"), int) or w_sched["runs_used"] < 1:
        problems.append("write-planen har aldrig kørt (runs_used < 1)")
    if not isinstance(w_receipts, list) or len(w_receipts) < 1:
        problems.append(
            "write-planen mangler sin receipt -- et godkendt write uden "
            "attributionsspor må ikke findes")
    else:
        r0 = w_receipts[0]
        if not (isinstance(r0.get("device_id"), str) and r0["device_id"]):
            problems.append("receipten navngiver ingen enhed (device_id)")
        issued = r0.get("issued_at")
        consumed = r0.get("consumed_at")
        if not isinstance(issued, (int, float)) \
                or not isinstance(consumed, (int, float)):
            problems.append("receipten mangler issued_at/consumed_at")
        elif consumed < issued:
            problems.append(
                "receipten er selvmodsigende (consumed_at før issued_at)")

    if manual.get("revocation_confirmed") is not True:
        problems.append(
            "operatoren har ikke bekræftet revocation-observationen "
            "(pausen -> cancelled-job med dansk grund + refunderet slot)")
    line = manual.get("recovery_line")
    if not (isinstance(line, str) and "recovered" in line):
        problems.append(
            "recovery-linjen fra worker-start mangler eller er ikke "
            "genkendelig ('recovered N executed / M abandoned ...')")
    return problems


def build_report(candidate: dict[str, Any], worker_url: str,
                 read_id: str, write_id: str,
                 read_detail: dict[str, Any], write_detail: dict[str, Any],
                 manual: dict[str, Any], now_iso: str,
                 read_forensics_data: dict[str, Any] | None = None,
                 write_forensics_data: dict[str, Any] | None = None
                 ) -> dict[str, Any]:
    problems = judge(read_detail, write_detail, manual,
                     read_forensics_data, write_forensics_data)
    r_sched = read_detail.get("schedule") or {}
    w_sched = write_detail.get("schedule") or {}
    w_receipts = write_detail.get("approval_receipts") or []
    first = w_receipts[0] if w_receipts else {}
    return {
        "schema": SCHEMA,
        "generated_at": now_iso,
        "candidate": {
            "version": candidate["version"],
            "git_sha": candidate["git_sha"],
            "code_sha256": candidate["code_sha256"],
        },
        "worker": {"base_url": worker_url},
        "read_schedule": {
            "schedule_id": read_id,
            "runs_used": r_sched.get("runs_used"),
            "receipts_count": len(read_detail.get("approval_receipts") or []),
        },
        "write_schedule": {
            "schedule_id": write_id,
            "runs_used": w_sched.get("runs_used"),
            "receipts_count": len(w_receipts),
            "first_receipt": {
                "kind": first.get("kind"),
                "device_id": first.get("device_id"),
                "issued_at": first.get("issued_at"),
                "consumed_at": first.get("consumed_at"),
            },
        },
        "forensics": {
            "read": read_forensics_data,
            "write": write_forensics_data,
        },
        "manual": {
            "revocation_confirmed": manual.get("revocation_confirmed"),
            "recovery_line": manual.get("recovery_line"),
            "operator": manual.get("operator"),
        },
        "pilot": {"passed": not problems, "problems": problems},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-url", default="http://127.0.0.1:8099")
    parser.add_argument("--read-schedule-id", required=True)
    parser.add_argument("--write-schedule-id", required=True)
    parser.add_argument("--manual-observations", type=Path, required=True)
    parser.add_argument(
        "--schedules-db",
        default=os.environ.get("KALIV_SCHEDULES_DB", "./kaliv-schedules.db"))
    parser.add_argument(
        "--jobs-db",
        default=os.environ.get("MODELRIG_JOBS_DB", "./modelrig-jobs.db"))
    parser.add_argument(
        "--audit-db",
        default=os.environ.get("KALIV_AUDIT_DB", "./kaliv-audit.db"))
    parser.add_argument(
        "--report", type=Path,
        default=Path("validation/scheduler-pilot-latest.json"))
    args = parser.parse_args(argv)

    try:
        manual = json.loads(args.manual_observations.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  FAIL  manual-observations kan ikke læses: {exc}")
        return 1

    campaign = _load_campaign()
    try:
        candidate = campaign.candidate_identity(ROOT)
    except campaign.CampaignError as exc:
        print(f"  FAIL  kandidat-identitet: {exc}")
        return 1

    base = args.worker_url.rstrip("/")
    details: dict[str, dict[str, Any]] = {}
    for label, sid in (("read", args.read_schedule_id),
                       ("write", args.write_schedule_id)):
        try:
            details[label] = fetch_json(f"{base}/schedules/{sid}")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            print(f"  FAIL  kunne ikke læse {label}-planen fra workeren: {exc}")
            return 1

    forensics: dict[str, dict[str, Any] | None] = {"read": None, "write": None}
    for label, sid in (("read", args.read_schedule_id),
                       ("write", args.write_schedule_id)):
        try:
            forensics[label] = read_forensics(
                args.schedules_db, args.jobs_db, args.audit_db, sid)
        except sqlite3.Error as exc:
            print(f"  FAIL  forensik for {label}-planen kunne ikke laeses "
                  f"fra storene: {exc}")
            print("         -> peg --schedules-db/--jobs-db/--audit-db paa "
                  "workerens filer (eller koer fra dens arbejdsmappe)")
            return 1

    now_iso = datetime.now(timezone.utc).isoformat()
    report = build_report(candidate, base, args.read_schedule_id,
                          args.write_schedule_id, details["read"],
                          details["write"], manual, now_iso,
                          forensics["read"], forensics["write"])

    args.report.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.report.with_suffix(args.report.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    tmp.replace(args.report)

    if report["pilot"]["passed"]:
        print(f"  OK    scheduler-piloten holder -- evidens skrevet til "
              f"{args.report}")
        return 0
    print("  FAIL  scheduler-piloten holder IKKE:")
    for p in report["pilot"]["problems"]:
        print(f"         - {p}")
    print(f"         (rapporten er stadig skrevet til {args.report} "
          "til inspektion)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
