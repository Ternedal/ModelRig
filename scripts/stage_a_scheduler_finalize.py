#!/usr/bin/env python3
"""Finish the isolated Stage A scheduler pilot after one Android approval.

Requires the real read, revocation, and crash-recovery checkpoints produced by
the preceding bounded helpers. This finalizer verifies their durable rows, waits
for exactly one new canonical Android-approved write grant, waits for one real
execution, derives the manual-observation file from the already verified
physical evidence, and invokes the authoritative scheduler_pilot_report.py.

It cannot mint or copy an approval token, approve on the operator's behalf,
merge, push, tag, release, or activate production.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMMON_PATH = ROOT / "scripts" / "stage_a_scheduler_read.py"
RECOVERY_RE = re.compile(
    r"scheduler: recovered \d+ executed / \d+ abandoned / \d+ unknown occurrence\(s\) at startup"
)


class FinalizeError(RuntimeError):
    pass


def load_common():
    spec = importlib.util.spec_from_file_location(
        "stage_a_scheduler_finalize_common", COMMON_PATH
    )
    if spec is None or spec.loader is None:
        raise FinalizeError("Schedulerens fælles Stage A-helper kunne ikke indlæses.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise FinalizeError(f"Stage A-helperen kunne ikke indlæses: {exc}") from exc
    return module


def report_passed(path: Path, identity: dict[str, Any]) -> bool:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(report, dict):
        return False
    candidate = report.get("candidate")
    pilot = report.get("pilot")
    return (
        report.get("schema") == "kaliv-scheduler-pilot/v4"
        and isinstance(candidate, dict)
        and candidate.get("version") == identity.get("version")
        and candidate.get("git_sha") == identity.get("git_sha")
        and candidate.get("code_sha256") == identity.get("code_sha256")
        and isinstance(pilot, dict)
        and pilot.get("passed") is True
        and pilot.get("problems") == []
    )


def occurrence(wizard: Any, claim_id: str) -> dict[str, Any] | None:
    rows = wizard.db_rows(
        "SELECT claim_id, schedule_id, status, job_id, resolved "
        "FROM occurrences WHERE claim_id=?",
        (claim_id,),
    )
    return rows[0] if rows else None


def verify_prior_evidence(wizard: Any, state: dict[str, Any], read_id: str) -> str:
    if state.get("schema") != "kaliv-stage-a-scheduler-read-checkpoint/v1":
        raise FinalizeError(
            "Read-checkpointet mangler. Kør scheduler-trinnene i den viste rækkefølge."
        )
    if state.get("read_executed") is not True:
        raise FinalizeError("Read-halvdelen er ikke dokumenteret som udført.")
    if state.get("revocation_confirmed") is not True:
        raise FinalizeError("Revocation-beviset mangler.")
    if state.get("crash_recovery_confirmed") is not True:
        raise FinalizeError("Crash-recovery-beviset mangler.")
    if state.get("write_pending") is not True:
        raise FinalizeError("Write-status er ikke pending; checkpointet er selvmodsigende.")

    read_view = wizard.schedule_view(wizard.detail(read_id))
    if not wizard.matches_manifest(read_view, wizard.READ_SPEC):
        raise FinalizeError("Read-planen matcher ikke det kanoniske pilotmanifest.")

    revocation_claim = str(state.get("revocation_claim_id") or "")
    revocation_job = str(state.get("revocation_job_id") or "")
    if not revocation_claim or not revocation_job:
        raise FinalizeError("Revocation-checkpointet mangler claim- eller jobbinding.")
    revocation_occ = occurrence(wizard, revocation_claim)
    if not revocation_occ or revocation_occ.get("status") != "released":
        raise FinalizeError("Revocation-occurrencen er ikke durable 'released'.")
    if str(revocation_occ.get("job_id") or "") != revocation_job:
        raise FinalizeError("Revocation-occurrence og job-checkpoint matcher ikke.")
    job = wizard.job_row(revocation_job)
    if not job or job.get("status") != "cancelled":
        raise FinalizeError("Revocation-jobbet er ikke durable 'cancelled'.")
    reason = str(job.get("detail") or "").lower()
    if "pauset" not in reason and "ændret eller slettet" not in reason:
        raise FinalizeError("Revocation-jobbet mangler den forventede danske grund.")
    if int(state.get("revocation_runs_before") or -1) != int(
        state.get("revocation_runs_after") or -2
    ):
        raise FinalizeError("Revocation-checkpointet beviser ikke refunderet budget.")

    crash_claim = str(state.get("crash_claim_id") or "")
    if not crash_claim:
        raise FinalizeError("Crash-recovery-checkpointet mangler claim_id.")
    crash_occ = occurrence(wizard, crash_claim)
    if not crash_occ or crash_occ.get("status") != "abandoned":
        raise FinalizeError("Crash-occurrencen er ikke durable 'abandoned'.")

    recovery_line = str(state.get("recovery_line") or "")
    if RECOVERY_RE.fullmatch(recovery_line) is None:
        raise FinalizeError("Checkpointet mangler den faktiske scheduler-recovery-linje.")
    try:
        worker_log = wizard.LOG_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise FinalizeError(f"Worker-loggen kunne ikke læses: {exc}") from exc
    if recovery_line not in worker_log:
        raise FinalizeError("Recovery-linjen findes ikke i dette isolerede runs worker-log.")
    return recovery_line


def verify_inventory_before_write(wizard: Any, read_id: str, known_write: str) -> None:
    allowed = {read_id}
    if known_write:
        allowed.add(known_write)
    unexpected = sorted(
        {
            wizard.schedule_id(row)
            for row in wizard.schedules()
            if wizard.schedule_id(row) and wizard.schedule_id(row) not in allowed
        }
    )
    if unexpected:
        raise FinalizeError(
            "Den isolerede pilotstore indeholder uventede planer: "
            + ", ".join(unexpected)
        )


def main() -> int:
    if os.name != "nt":
        print("  STOP  Scheduler-finaliseringen må kun køres på Windows-riggen.")
        return 1

    common = None
    wizard = None
    try:
        common = load_common()
        phone = common.load_json(common.PHONE_STATE)
        if phone.get("schema") != "kaliv-stage-a-phone-test-state/v2":
            raise FinalizeError("Telefon-status er ikke scheduler-kompatibel.")
        wizard, data_dir = common.bind_wizard(phone)

        status = wizard.schedule_status()
        if not (
            status.get("configured") is True
            and status.get("running") is True
            and status.get("resources_open") is True
            and not status.get("last_error")
        ):
            raise FinalizeError(f"Scheduler-endpointet er ikke klart: {status!r}")

        state = wizard.load_state()
        read_id = str(state.get("read_schedule_id") or "")
        if not read_id:
            raise FinalizeError("Checkpointet indeholder ingen read-plan.")

        identity = wizard._current_candidate_identity()
        if not (
            identity.get("working_tree_clean") is True
            and identity.get("version_stamps_consistent") is True
            and identity.get("version") == wizard.VERSION
            and isinstance(identity.get("git_sha"), str)
            and len(str(identity.get("git_sha"))) == 40
            and isinstance(identity.get("code_sha256"), str)
            and len(str(identity.get("code_sha256"))) == 64
        ):
            raise FinalizeError("Den aktuelle checkout har ikke en ren, konsistent kandidat-identitet.")

        if state.get("pilot_report_generated") is True:
            if report_passed(wizard.REPORT_PATH, identity):
                print("  OK  Scheduler-pilotrapporten er allerede bestået for denne eksakte checkout.")
                print(f"  Rapport: {wizard.REPORT_PATH}")
                return 0
            raise FinalizeError("Checkpointet siger rapport genereret, men rapporten består ikke.")

        recovery_line = verify_prior_evidence(wizard, state, read_id)
        known_write = str(state.get("write_schedule_id") or "")
        verify_inventory_before_write(wizard, read_id, known_write)

        print("\n===============================================================")
        print("  SIDSTE MANUELLE HANDLING: GODKEND WRITE-PLANEN I ANDROID")
        print("===============================================================")
        print("  Opret præcis denne plan i Kaliv:")
        print('    tool: note_append')
        print('    args: {"text":"pilot"}')
        print('    cadence: every:60')
        print('    max_runs: 2')
        print('    ttl_days: 1')
        print('    timezone: Europe/Copenhagen')
        print('    misfire_policy: run_once')
        print("  Bekræft kortet i appen. Du skal ikke kopiere ID eller token tilbage.")
        print("  Denne proces finder automatisk den device-bundne receipt.")

        write_id = wizard.wait_for_write(state, timeout=900.0)
        write_detail = wizard.detail(write_id)
        write_view = wizard.schedule_view(write_detail)
        if not wizard.matches_manifest(write_view, wizard.WRITE_SPEC):
            raise FinalizeError("Den fundne write-plan matcher ikke pilotmanifestet.")
        receipts = write_detail.get("approval_receipts")
        if not isinstance(receipts, list) or len(receipts) < 1:
            raise FinalizeError("Write-planen mangler sin device-bundne approval receipt.")

        wizard.wait_runs(write_id, 1, timeout=150.0)
        wizard.write_manual(recovery_line)
        wizard.generate_report(read_id, write_id)

        if not report_passed(wizard.REPORT_PATH, identity):
            raise FinalizeError(
                "Den autoritative scheduler-evaluator skrev en rapport, men piloten bestod ikke."
            )

        wizard.set_enabled(write_id, False)
        state.update(
            {
                "write_schedule_id": write_id,
                "write_pending": False,
                "write_executed": True,
                "pilot_report_generated": True,
                "pilot_report_passed": True,
                "pilot_report": str(wizard.REPORT_PATH),
                "candidate_version": identity.get("version"),
                "candidate_git_sha": identity.get("git_sha"),
                "candidate_code_sha256": identity.get("code_sha256"),
                "production_activation": False,
            }
        )
        wizard.save_state(state)

        print("\n===============================================================")
        print("  SCHEDULER-PILOTEN BESTOD DEN AUTORITATIVE EVALUATOR")
        print("===============================================================")
        print(f"  Write-plan: {write_id}")
        print(f"  Rapport: {wizard.REPORT_PATH}")
        print(f"  Exact SHA: {identity.get('git_sha')}")
        print("  Write-planen er pauset efter rapporten.")
        print("  Dette er kun scheduler-slotten; ingen merge, release eller aktivering er udført.")
        print("  production_activation=false")
        return 0
    except Exception as exc:
        expected = isinstance(exc, FinalizeError) or (
            common is not None and isinstance(exc, common.ReadPilotError)
        ) or (
            wizard is not None and isinstance(exc, wizard.PilotError)
        )
        if not expected:
            raise
        print(f"\n  STOP  {exc}")
        print("  Eventuelle delresultater og ID'er er bevaret i den isolerede run-mappe.")
        print("  Intet scheduler- eller pilotresultat er blevet fremstillet som bestået.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
