#!/usr/bin/env python3
"""Regression contract for the proof campaign's automatic pairing bootstrap.

The launcher may remove manual token-copying. It may not gain authority over
unrelated listeners, reuse the operator's normal pairing store, dirty the exact
checkout, bypass the real pair/start -> pair/claim protocol, weaken the core
proof gates, or persist the minted device token.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "START_PROOF_CAMPAIGN.cmd"
WRAPPER = ROOT / "scripts" / "run-proof-campaign-owned-pairing.ps1"
CORE = ROOT / "scripts" / "run-proof-campaign.ps1"
GITIGNORE = ROOT / ".gitignore"

passed = 0
failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        suffix = f" -- {detail}" if detail else ""
        print(f"  FAIL: {name}{suffix}")


def main() -> int:
    required = (LAUNCHER, WRAPPER, CORE, GITIGNORE)
    missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
    check("required proof files exist", not missing, f"missing={missing}")
    if missing:
        return 1

    launcher = LAUNCHER.read_text(encoding="utf-8")
    launcher_commands = "\n".join(
        line for line in launcher.splitlines()
        if not line.lstrip().lower().startswith("rem ")
    )
    wrapper = WRAPPER.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")
    gitignore = GITIGNORE.read_text(encoding="utf-8")
    lower = wrapper.lower()
    core_lower = core.lower()

    check(
        "double-click launcher uses the Windows admin role and routes through owned pairing wrapper",
        "WindowsPrincipal" in launcher_commands
        and "WindowsBuiltInRole]::Administrator" in launcher_commands
        and "-Verb RunAs" in launcher_commands
        and "net session" not in launcher_commands.lower()
        and "run-proof-campaign-owned-pairing.ps1" in launcher_commands
        and "run-proof-campaign.ps1\" %*" not in launcher_commands,
    )
    check(
        "bootstrap chooses an ephemeral loopback port instead of commandeering 8080",
        "TcpListener" in wrapper
        and "[Net.IPAddress]::Loopback, 0" in wrapper
        and "$bootstrapPort = Get-FreeLoopbackPort" in wrapper,
    )
    check(
        "bootstrap store is per-run and isolated under ignored stage-a-runtime",
        "validation\\stage-a-runtime\\proof-pairing" in wrapper
        and "/validation/stage-a-runtime/" in gitignore
        and "$pairingStore = Join-Path $bootstrapDir 'pairing-data.json'" in wrapper,
    )
    check(
        "bootstrap does not create the old unignored validation/proof-bootstrap path",
        "validation\\proof-bootstrap" not in wrapper,
    )
    check(
        "bootstrap authenticates pair/start with a process-local random admin key",
        "New-RandomHex 32" in wrapper
        and "'X-Admin-Key' = $bootstrapAdminKey" in wrapper
        and "/api/v1/pair/start" in wrapper,
    )
    check(
        "device token is minted only through the normal one-use claim endpoint",
        "/api/v1/pair/claim" in wrapper
        and "$proofToken = [string]$claim.token" in wrapper
        and "^[0-9a-fA-F]{64}$" in wrapper,
    )
    check(
        "wrapper never asks the operator to paste MODELRIG_TOKEN",
        "Read-Host 'MODELRIG_TOKEN" not in wrapper
        and "read-host \"modelrig_token" not in lower
        and "getpass" not in lower,
    )
    check(
        "bootstrap process ownership comes from Start-Process -PassThru",
        "$bootstrap = Start-Process" in wrapper and "-PassThru" in wrapper,
    )
    check(
        "bootstrap cleanup stops only the PID returned for its owned process",
        "Stop-Process -Id $bootstrap.Id" in wrapper
        and "Get-NetTCPConnection" not in wrapper
        and "taskkill" not in lower
        and "Win32_Process" not in wrapper,
    )
    check(
        "unrelated 8080/8099 listeners are not touched by bootstrap code",
        "Get-ListenerPid" not in wrapper
        and "LocalPort 8080" not in wrapper
        and "LocalPort 8099" not in wrapper,
    )
    check(
        "bootstrap host and admin settings are restored before the proof engine runs",
        "Restore-EnvValue 'MODELRIG_HOST'" in wrapper
        and "Restore-EnvValue 'MODELRIG_PORT'" in wrapper
        and "Restore-EnvValue 'MODELRIG_ADMIN_KEY'" in wrapper,
    )
    check(
        "isolated store and process-local token are passed to the existing proof engine",
        "$env:MODELRIG_DATA = $pairingStore" in wrapper
        and "$env:MODELRIG_TOKEN = $proofToken" in wrapper
        and "run-proof-campaign.ps1" in wrapper,
    )
    check(
        "all existing skip/reuse switches are forwarded instead of reimplemented",
        all(
            f"if (${name}) {{ $coreArgs += '-{name}' }}" in wrapper
            for name in ("SkipStageA", "SkipForcedRecovery", "SkipWorkflows", "SkipT023", "SkipT033")
        ),
    )
    check(
        "Agent 4 remains an explicit forwarded opt-in",
        "if ($IncludeAgent4) { $coreArgs += '-IncludeAgent4' }" in wrapper
        and "-Agent4OutputRoot" in wrapper
        and "-Agent4ApkPath" in wrapper
        and "-Agent4LanAddress" in wrapper,
    )
    check(
        "the existing core still initializes every release-critical proof gate red",
        "function New-ProofGate" in core
        and "passed = $false" in core
        and "Get-ProofCampaignPassed" in core,
    )
    check(
        "skip/reuse remains delegated to receipt validation in the core",
        "function Try-ReuseGate" in core
        and "Invoke-GateReceipt 'validate'" in core
        and "gaten forbliver rød" in core_lower,
    )
    check(
        "minted token is cleared/restored after the child proof process",
        "$proofToken = $null" in wrapper
        and "Restore-EnvValue 'MODELRIG_TOKEN'" in wrapper,
    )
    check(
        "isolated pairing store is removed after the proof child exits",
        "Remove-Item -LiteralPath $pairingStore" in wrapper,
    )
    check(
        "convenience layer cannot declare production activation",
        "production_activation=true" not in lower
        and "production_activation = true" not in lower,
    )

    print(f"owned proof pairing contract: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
