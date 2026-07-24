#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHONE = ROOT / "scripts" / "stage-a-phone-test.ps1"
STACK = ROOT / "scripts" / "start-stage-a-validation-stack.ps1"
START = ROOT / "START_STAGE_A_PHONE_TEST.cmd"
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


phone = PHONE.read_text(encoding="utf-8")
phone_lower = phone.lower()
stack = STACK.read_text(encoding="utf-8")
start = START.read_text(encoding="utf-8")
stop = STOP.read_text(encoding="utf-8")

check('string]$BackendHost = "127.0.0.1"' in stack,
      "the shared stack remains loopback-only by default")
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

check('-BackendHost "0.0.0.0"' in phone,
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

check('stage-a-phone-test.ps1' in start and '-Stop' not in start,
      "the start launcher invokes only the phone-test start path")
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

print(f"Stage A phone-test contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
