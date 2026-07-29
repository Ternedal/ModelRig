#!/usr/bin/env python3
"""Exercise only the scheduler pilot's physical revocation proof.

Requires the isolated scheduler phone stack and a completed read checkpoint.
The helper uses the retained wizard's deterministic JobStore backpressure seam
to catch a real durable claim, pauses the grant, and verifies the resulting
released occurrence, cancelled job, Danish reason, and refunded run budget.
It does not create a write schedule, crash a worker, or generate a pilot report.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMMON_PATH = ROOT / "scripts" / "stage_a_scheduler_read.py"


class RevocationError(RuntimeError):
    pass


def load_common():
    spec = importlib.util.spec_from_file_location(
        "stage_a_scheduler_revocation_common", COMMON_PATH
    )
    if spec is None or spec.loader is None:
        raise RevocationError("Schedulerens fælles Stage A-helper kunne ikke indlæses.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RevocationError(f"Stage A-helperen kunne ikke indlæses: {exc}") from exc
    return module


def main() -> int:
    if os.name != "nt":
        print("  STOP  Revocation-testen må kun køres på Windows-riggen.")
        return 1

    common = None
    wizard = None
    try:
        common = load_common()
        phone = common.load_json(common.PHONE_STATE)
        if phone.get("schema") != "kaliv-stage-a-phone-test-state/v2":
            raise RevocationError("Telefon-status er ikke scheduler-kompatibel.")
        wizard, data_dir = common.bind_wizard(phone)

        status = wizard.schedule_status()
        if not (
            status.get("configured") is True
            and status.get("running") is True
            and status.get("resources_open") is True
            and not status.get("last_error")
        ):
            raise RevocationError(f"Scheduler-endpointet er ikke klart: {status!r}")

        state = wizard.load_state()
        if state.get("schema") != "kaliv-stage-a-scheduler-read-checkpoint/v1":
            raise RevocationError(
                "Read-checkpointet mangler. Kør PREPARE_STAGE_A_SCHEDULER_READ.cmd først."
            )
        read_id = str(state.get("read_schedule_id") or "")
        if not read_id or state.get("read_executed") is not True:
            raise RevocationError("Read-checkpointet indeholder ingen udført read-plan.")
        if state.get("revocation_confirmed") is True:
            print("  OK  Revocation-beviset er allerede gemt for dette isolerede run.")
            return 0
        if state.get("write_pending") is not True:
            raise RevocationError("Write-status er uventet; revocation skal køres før write-halvdelen.")

        detail = wizard.schedule_view(wizard.detail(read_id))
        if not wizard.matches_manifest(detail, wizard.READ_SPEC):
            raise RevocationError("Read-planen matcher ikke det kanoniske pilotmanifest.")

        print("\n===============================================================")
        print("  AUTOMATISK SCHEDULER-REVOCATION")
        print("===============================================================")
        print("  Venter på næste kanoniske read-occurrence og pauser den i claim-vinduet.")

        due, before, prior_runs = wizard.prepare_aligned_schedule(read_id)
        claim = wizard.catch_claim_and_pause(read_id, due, before)
        claim_id = str(claim.get("claim_id") or "")
        if not claim_id:
            raise RevocationError("Den fangede occurrence mangler claim_id.")

        resolved = wizard.wait_occurrence(claim_id, "released")
        job_id = str(resolved.get("job_id") or "")
        if not job_id:
            raise RevocationError("Revocation-occurrencen blev released uden job-binding.")
        job = wizard.job_row(job_id)
        if not job or job.get("status") != "cancelled":
            raise RevocationError("Revocation-jobbet blev ikke cancelled.")
        reason = str(job.get("detail") or "")
        reason_lower = reason.lower()
        if "pauset" not in reason_lower and "ændret eller slettet" not in reason_lower:
            raise RevocationError("Revocation-jobbet mangler den forventede danske grund.")

        runs_after = int(
            wizard.schedule_view(wizard.detail(read_id)).get("runs_used") or 0
        )
        if runs_after != prior_runs:
            raise RevocationError(
                f"Revocation refunderede ikke budgettet ({prior_runs} -> {runs_after})."
            )

        state.update(
            {
                "revocation_pending": False,
                "revocation_confirmed": True,
                "revocation_claim_id": claim_id,
                "revocation_job_id": job_id,
                "revocation_reason": reason,
                "revocation_runs_before": prior_runs,
                "revocation_runs_after": runs_after,
                "crash_recovery_pending": True,
                "write_pending": True,
                "pilot_report_generated": False,
                "production_activation": False,
            }
        )
        wizard.save_state(state)

        print("\n===============================================================")
        print("  REVOCATION-BEVISET ER GEMT")
        print("===============================================================")
        print(f"  Claim: {claim_id}")
        print(f"  Job:   {job_id} (cancelled)")
        print(f"  Grund: {reason}")
        print(f"  Budget: {prior_runs} -> {runs_after} (refunderet)")
        print(f"  Checkpoint: {data_dir / 'scheduler-pilot-state.json'}")
        print("  Crash-recovery, write og samlet pilotrapport er fortsat pending.")
        print("  production_activation=false")
        return 0
    except Exception as exc:
        expected = isinstance(exc, RevocationError) or (
            common is not None
            and isinstance(exc, common.ReadPilotError)
        ) or (
            wizard is not None
            and isinstance(exc, wizard.PilotError)
        )
        if not expected:
            raise
        print(f"\n  STOP  {exc}")
        print("  Der er ikke skrevet noget revocation- eller pilotresultat som bestået.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
