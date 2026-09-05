#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PHONE = ROOT / "scripts" / "stage-a-phone-test.ps1"
STACK = ROOT / "scripts" / "start-stage-a-validation-stack.ps1"
READ_HELPER = ROOT / "scripts" / "stage_a_scheduler_read.py"
REVOCATION_HELPER = ROOT / "scripts" / "stage_a_scheduler_revocation.py"
CRASH_HELPER = ROOT / "scripts" / "stage_a_scheduler_crash_recovery.py"
START = ROOT / "START_STAGE_A_PHONE_TEST.cmd"
SCHEDULER_START = ROOT / "START_STAGE_A_SCHEDULER_TEST.cmd"
READ_START = ROOT / "PREPARE_STAGE_A_SCHEDULER_READ.cmd"
REVOCATION_START = ROOT / "RUN_STAGE_A_SCHEDULER_REVOCATION.cmd"
CRASH_START = ROOT / "RUN_STAGE_A_SCHEDULER_CRASH_RECOVERY.cmd"
STOP = ROOT / "STOP_STAGE_A_PHONE_TEST.cmd"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


phone = code_of(PHONE)
phone_lower = phone.lower()
stack = code_of(STACK)
read_helper = code_of(READ_HELPER)
read_helper_lower = read_helper.lower()
revocation_helper = code_of(REVOCATION_HELPER)
revocation_helper_lower = revocation_helper.lower()
crash_helper = code_of(CRASH_HELPER)
crash_helper_lower = crash_helper.lower()
start = code_of(START)
scheduler_start = code_of(SCHEDULER_START)
read_start = code_of(READ_START)
revocation_start = code_of(REVOCATION_START)
crash_start = code_of(CRASH_START)
stop = code_of(STOP)

check('string]$BackendHost = $(if ($env:MODELRIG_HOST) { $env:MODELRIG_HOST } else { "127.0.0.1" })' in stack,
      "the shared stack remains loopback-only by default (LAN needs explicit -BackendHost or MODELRIG_HOST)")
check('if ($BackendHost -eq "127.0.0.1") {' in stack and "telefonen kan ikke naa en loopback-bundet backend" in stack,
      "a loopback binding warns visibly that the phone cannot reach it")
check('[switch]$EnableSchedulerApi' in stack and '[string]$PairingData' in stack,
      "LAN/scheduler/pairing changes are explicit opt-ins")
check('set "MODELRIG_HOST=$escapedHost"' in stack,
      "the selected binding reaches the candidate backend process")
check(
    '$schedulerApiValue = if ($EnableSchedulerApi) { "1" } else { "0" }' in stack
    and 'set "KALIV_SCHEDULER_API=$schedulerApiValue"' in stack,
    "the scheduler API remains disabled unless explicitly requested",
)
check('GetFullPath($PairingData, $repoRoot)' not in stack,
      "the stack avoids a .NET overload missing from Windows PowerShell 5.1")
check(
    'function Resolve-RepoPath' in stack
    and '[IO.Path]::IsPathRooted($Value)' in stack
    and 'Resolve-RepoPath -Value $PairingData' in stack,
    "relative pairing stores are resolved compatibly on Windows PowerShell 5.1",
)
check(
    '$schedulerValue = if ($EnableScheduler) { "1" } else { "0" }' in stack
    and 'set "KALIV_SCHEDULER=$schedulerValue"' in stack,
    "the scheduler runtime remains disabled unless explicitly requested",
)
check(
    'KALIV_SCHEDULES_DB=' in stack
    and 'MODELRIG_JOBS_DB=' in stack
    and 'KALIV_AUDIT_DB=' in stack,
    "an enabled scheduler is bound to explicit isolated stores",
)
check(
    '[string]$WorkerLog' in stack
    and 'python -u -m uvicorn' in stack
    and '2>&1' in stack,
    "the scheduler worker can write an unbuffered recovery log",
)

check('BackendHost = "0.0.0.0"' in phone,
      "the phone helper deliberately exposes only its test backend to LAN")
check('-RemoteAddress LocalSubnet' in phone and '-LocalPort 8080' in phone,
      "the temporary firewall rule is restricted to the local subnet and port 8080")
check('http://127.0.0.1:8080/api/v1/pair/start' in phone,
      "the pairing code is minted through the live backend from loopback")
check('phone-test-modelrig-data.json' in phone,
      "phone pairing is isolated from the normal rig device store")
check('Indtast koden i appen' in phone,
      "the operator is told to replace a stale app token with the issued code")
check('Test-RecordedProcess' in phone and 'listenerPid -eq $entry.ProcessId' in phone,
      "cleanup stops only PIDs recorded for this exact test stack")
check('Remove-TestFirewall' in phone,
      "the temporary firewall rule has an explicit cleanup path")
check('production_activation = $false' in phone,
      "the runtime state records that production activation remains false")
check('192\\.168\\.' in phone and 'tailscale|vethernet|wsl|hyper-v|docker|loopback' in phone,
      "RFC1918 physical LAN addresses are preferred over virtual adapters")
check('LAN-healthcheck' in phone and 'Invoke-RestMethod -Uri "$lanUrl/healthz"' in phone,
      "the advertised phone URL is verified before a pairing code is shown")

check(
    '[switch]$EnableSchedulerPilot' in phone
    and 'if ($EnableSchedulerPilot)' in phone,
    "scheduler mode is an explicit phone-helper opt-in",
)
check(
    '$stackArgs["EnableSchedulerApi"] = $true' in phone
    and '$stackArgs["EnableScheduler"] = $true' in phone
    and '$stackArgs["HeadlessWorker"] = $true' in phone,
    "the scheduler launcher composes the full isolated runtime only in opt-in mode",
)
check(
    'New-SchedulerApprovalSecret' in phone
    and 'RandomNumberGenerator]::Create()' in phone
    and 'approval-secret.txt' in phone,
    "the backend and worker receive one fresh per-run approval secret",
)
check(
    'scheduler-pilot-$runId' in phone
    and 'worker.log' in phone
    and 'SchedulerDataDir' in phone,
    "each scheduler run receives a fresh isolated data directory and log",
)
check(
    'http://127.0.0.1:8099/schedules/status' in phone
    and '$schedulerStatus.configured' in phone
    and '$schedulerStatus.running' in phone
    and '$schedulerStatus.resources_open' in phone,
    "the scheduler is proven ready before the pairing code is shown",
)
check(
    'approval_secret_file = $schedulerSecretPath' in phone
    and 'scheduler = [ordered]@{' in phone,
    "restart metadata stores only the secret path and scheduler runtime paths",
)

check('phone-test-state.json' in read_helper,
      "the read helper consumes the phone stack's own runtime state")
check(
    'kaliv-stage-a-phone-test-state/v2' in read_helper
    and 'scheduler.get("enabled") is True' in read_helper
    and 'scheduler.get("configured") is True' in read_helper
    and 'scheduler.get("running") is True' in read_helper,
    "the read helper refuses a stale or inactive scheduler stack",
)
check(
    'under_runtime(data_dir)' in read_helper
    and 'under_runtime(worker_log)' in read_helper
    and 'worker_log.parent.resolve() != data_dir.resolve()' in read_helper,
    "the read helper accepts only one isolated runtime directory",
)
check(
    'wizard.SCHEDULES_DB = data_dir / "kaliv-schedules.db"' in read_helper
    and 'wizard.JOBS_DB = data_dir / "modelrig-jobs.db"' in read_helper
    and 'wizard.AUDIT_DB = data_dir / "kaliv-audit.db"' in read_helper,
    "the read helper reuses the exact stores started by the phone stack",
)
check(
    'wizard.create_read(state)' in read_helper
    and 'wizard.wait_runs(read_id, 1' in read_helper
    and 'wizard.set_enabled(read_id, False)' in read_helper,
    "the exact read plan must execute once and is then paused",
)
check(
    'write_pending": True' in read_helper
    and 'revocation_pending": True' in read_helper
    and 'crash_recovery_pending": True' in read_helper
    and 'pilot_report_generated": False' in read_helper,
    "the read checkpoint keeps every remaining physical proof pending",
)
check(
    'wait_for_write' not in read_helper
    and 'generate_report' not in read_helper
    and 'scheduler_pilot_report.py' not in read_helper,
    "the read helper cannot create write evidence or a final pilot report",
)
check('input(' not in read_helper and 'getpass' not in read_helper,
      "the read half has no copy/paste or manual JSON prompt")
for forbidden in ("git push", "git tag", "gh release", "production_activation=true"):
    check(forbidden not in read_helper_lower,
          f"read helper has no forbidden promotion action: {forbidden}")

check('stage_a_scheduler_read.py' in revocation_helper,
      "revocation reuses the validated scheduler-stack binding")
check(
    'kaliv-stage-a-scheduler-read-checkpoint/v1' in revocation_helper
    and 'state.get("read_executed") is not True' in revocation_helper,
    "revocation refuses to run without the physical read checkpoint",
)
check(
    'wizard.matches_manifest(detail, wizard.READ_SPEC)' in revocation_helper,
    "revocation is bound to the exact canonical read plan",
)
check(
    'wizard.prepare_aligned_schedule(read_id)' in revocation_helper
    and 'wizard.catch_claim_and_pause(read_id, due, before)' in revocation_helper
    and 'wizard.wait_occurrence(claim_id, "released")' in revocation_helper,
    "revocation catches and resolves a real durable occurrence",
)
check(
    'job.get("status") != "cancelled"' in revocation_helper
    and '"pauset" not in reason_lower' in revocation_helper
    and 'runs_after != prior_runs' in revocation_helper,
    "revocation verifies cancelled job, Danish reason, and refunded budget",
)
check(
    'revocation_confirmed": True' in revocation_helper
    and 'crash_recovery_pending": True' in revocation_helper
    and 'write_pending": True' in revocation_helper
    and 'pilot_report_generated": False' in revocation_helper,
    "revocation checkpoint leaves crash, write, and report pending",
)
check(
    'wait_for_write' not in revocation_helper
    and 'run_crash_recovery' not in revocation_helper
    and 'generate_report' not in revocation_helper,
    "revocation cannot create write, crash-recovery, or final evidence",
)
check('input(' not in revocation_helper and 'getpass' not in revocation_helper,
      "revocation has no copy/paste or manual JSON prompt")
for forbidden in ("git push", "git tag", "gh release", "production_activation=true"):
    check(forbidden not in revocation_helper_lower,
          f"revocation helper has no forbidden promotion action: {forbidden}")

check('stage_a_scheduler_read.py' in crash_helper,
      "crash recovery reuses the validated isolated stack binding")
check(
    'state.get("revocation_confirmed") is not True' in crash_helper
    and 'state.get("write_pending") is not True' in crash_helper,
    "crash recovery requires revocation and still-pending write state",
)
check(
    'listener_pid(8099) != expected_pid' in crash_helper
    and 'kill_recorded_worker(expected_pid)' in crash_helper
    and 'Get-CimInstance Win32_Process' in crash_helper,
    "only the stack-recorded uvicorn worker may be killed",
)
check(
    'wizard.lock_job_store()' in crash_helper
    and 'wizard.reserved_after(read_id, before)' in crash_helper
    and 'kill_recorded_worker(expected_pid)' in crash_helper,
    "the worker crash happens only after a real durable reserved claim",
)
check(
    'wizard.wait_for_lease_expiry()' in crash_helper
    and 'KALIV_SCHEDULER_APPROVAL_SECRET' in crash_helper
    and 'wizard.wait_for_recovery_line(offset' in crash_helper
    and 'wizard.wait_occurrence(claim_id, "abandoned"' in crash_helper,
    "restart reuses the secret/stores and requires real recovery evidence",
)
check(
    'phone["worker_pid"] = new_pid' in crash_helper
    and 'save_json(common.PHONE_STATE, phone)' in crash_helper,
    "safe cleanup follows the restarted worker PID",
)
check(
    'crash_recovery_confirmed": True' in crash_helper
    and 'write_pending": True' in crash_helper
    and 'pilot_report_generated": False' in crash_helper,
    "crash checkpoint leaves write and final report pending",
)
check(
    'wait_for_write' not in crash_helper
    and 'generate_report' not in crash_helper
    and 'scheduler_pilot_report.py' not in crash_helper,
    "crash helper cannot create write or final pilot evidence",
)
check('input(' not in crash_helper and 'getpass' not in crash_helper,
      "crash recovery has no copy/paste or manual JSON prompt")
for forbidden in ("git push", "git tag", "gh release", "production_activation=true"):
    check(forbidden not in crash_helper_lower,
          f"crash helper has no forbidden promotion action: {forbidden}")

check('stage-a-phone-test.ps1' in start and '-EnableSchedulerPilot' not in start,
      "the ordinary phone/voice launcher keeps the scheduler off")
check('stage-a-phone-test.ps1" -EnableSchedulerPilot' in scheduler_start,
      "the scheduler launcher selects the explicit scheduler path")
check('gennemfoerer endnu ikke selve scheduler-pilotbeviset' in scheduler_start.lower(),
      "the scheduler launcher does not claim that physical evidence already exists")
check('stage_a_scheduler_read.py' in read_start,
      "the read launcher invokes only the bounded read helper")
check('samlet pilotrapport forbliver pending' in read_start.lower(),
      "the read launcher labels the remaining pilot work honestly")
check('stage_a_scheduler_revocation.py' in revocation_start,
      "the revocation launcher invokes only the bounded revocation helper")
check('crash-recovery, write og samlet pilotrapport forbliver pending' in revocation_start.lower(),
      "the revocation launcher labels remaining work honestly")
check('stage_a_scheduler_crash_recovery.py' in crash_start,
      "the crash launcher invokes only the bounded crash-recovery helper")
check('write-godkendelse og samlet pilotrapport forbliver pending' in crash_start.lower(),
      "the crash launcher labels remaining work honestly")
check('stage-a-phone-test.ps1" -Stop' in stop,
      "the stop launcher invokes the safe cleanup path")

for forbidden in (
    "git push",
    "git tag",
    "gh release",
    "merge_pull_request",
    "production_activation=true",
    "modelrig_admin_key",
):
    check(forbidden not in phone_lower,
          f"phone helper has no forbidden action or remote admin bypass: {forbidden}")

check('token"' not in phone_lower and "token_hash" not in phone_lower,
      "the helper neither reads nor prints device tokens")
check('Write-Host $schedulerSecret' not in phone,
      "the scheduler approval secret is never printed")

print(f"Stage A phone-test contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
