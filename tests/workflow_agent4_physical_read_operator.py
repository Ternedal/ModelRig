#!/usr/bin/env python3
"""A4-18 physical operator, safety gate and receipt contracts."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
COMMON = SCRIPTS / "agent4-physical-read-common.ps1"
PROCESS = SCRIPTS / "agent4-physical-read-process.ps1"
RECORD = SCRIPTS / "agent4-physical-read-record.ps1"
FINALIZE = SCRIPTS / "agent4-physical-read-finalize.ps1"
WRAPPER = SCRIPTS / "agent4-physical-read-operator.ps1"
CORE_COMPAT = SCRIPTS / "agent4-physical-read-operator-core.ps1"
SAFETY_GATE = SCRIPTS / "agent4-physical-read-safety-gate.ps1"


class Agent4PhysicalReadOperatorTests(unittest.TestCase):
    def sources(self) -> dict[str, str]:
        return {
            path.name: path.read_text(encoding="utf-8")
            for path in (
                COMMON,
                PROCESS,
                RECORD,
                FINALIZE,
                WRAPPER,
                CORE_COMPAT,
                SAFETY_GATE,
            )
        }

    def test_admin_key_is_read_at_runtime_and_never_embedded(self) -> None:
        sources = self.sources()
        common = sources[COMMON.name]
        combined = "\n".join(sources.values())
        self.assertIn(
            'for /f "usebackq delims=" %%A in ("$escapedKeyFile")',
            common,
        )
        self.assertIn('set "MODELRIG_ADMIN_KEY=%%A"', common)
        self.assertIn("if not defined MODELRIG_ADMIN_KEY exit /b 41", common)
        self.assertNotIn("$escapedAdminKey", combined)
        self.assertNotRegex(
            combined,
            r'set\s+"MODELRIG_ADMIN_KEY=\$\([^)]*Get-AdminKey',
        )
        self.assertIn("Remove-Item -LiteralPath $script:adminKeyFile", common)
        self.assertIn("icacls $script:adminKeyFile /inheritance:r", common)

    def test_active_scripts_are_windows_powershell_51_compatible(self) -> None:
        combined = "\n".join(self.sources().values())
        for forbidden in (
            "[Security.Cryptography.SHA256]::HashData",
            "[Convert]::ToHexString",
            "[IO.Path]::GetRelativePath",
            "[Nullable[int]]",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertIn("[Security.Cryptography.SHA256]::Create()", combined)
        self.assertIn("[BitConverter]::ToString", combined)
        self.assertIn('$PSBoundParameters.ContainsKey("HttpStatus")', combined)

    def test_process_network_and_cleanup_are_fail_closed(self) -> None:
        common = COMMON.read_text(encoding="utf-8")
        self.assertIn(
            "python -u -m uvicorn app.entrypoint:app --host 127.0.0.1 --port 8099",
            common,
        )
        self.assertIn('set "MODELRIG_WORKER_URL=http://127.0.0.1:8099"', common)
        self.assertIn("-RemoteAddress LocalSubnet", common)
        self.assertNotIn("KALIV_WORKER_ALLOW_LAN=1", common)
        self.assertIn("Test-ExpectedProcess", common)
        self.assertIn("unknown_process_preserved", common)
        self.assertIn("Stop-CurrentExpectedListeners", common)
        self.assertIn("Assert-PortFree -Port 8080", common)
        self.assertIn("Assert-PortFree -Port 8099", common)

    def test_phase_transitions_require_physical_observations(self) -> None:
        process = PROCESS.read_text(encoding="utf-8")
        finalize = FINALIZE.read_text(encoding="utf-8")
        self.assertIn(
            'Assert-CheckpointsPassed -Names @("default_off_feature_locked", "default_off_no_worker_fallback")',
            process,
        )
        self.assertIn(
            'Assert-CheckpointsPassed -Names @("paired_without_grant_403", "paired_without_grant_locked_no_stale")',
            process,
        )
        for required in (
            '"campaign_paging_no_loss"',
            '"timeline_paging_no_loss"',
            '"evidence_paging_no_loss"',
            '"stale_campaign_record_422"',
            '"stale_summary_422"',
            '"revoke_same_token_403"',
            '"restart_does_not_restore_grant"',
        ):
            self.assertIn(required, process)
        self.assertIn('Assert-StatePhase -State $state -Allowed @("granted")', process)
        self.assertIn('Assert-StatePhase -State $state -Allowed @("revoked")', process)
        self.assertIn('if ([string]$state.phase -ne "regranted")', finalize)

    def test_recording_binds_expected_http_and_redacts_credentials(self) -> None:
        record = RECORD.read_text(encoding="utf-8")
        expected = {
            "default_off_feature_locked": 404,
            "paired_without_grant_403": 403,
            "grant_same_token_200": 200,
            "stale_campaign_record_422": 422,
            "stale_summary_422": 422,
            "revoke_same_token_403": 403,
            "not_found_fail_closed": 404,
        }
        for name, status in expected.items():
            self.assertRegex(record, rf"{re.escape(name)}\s*=\s*{status}")
        self.assertIn("authorization\\s*:", record)
        self.assertIn("x-admin-key\\s*:", record)
        self.assertIn("bearer\\s+", record)
        self.assertIn('Route -match "[?]"', record)
        self.assertIn('^sha256:[0-9a-f]{64}$', record)
        self.assertIn("validation/agent4-physical-runtime", record)
        self.assertIn("Get-ScreenshotReceipt", record)

    def test_final_receipt_cannot_go_without_all_checks_and_cleanup(self) -> None:
        finalize = FINALIZE.read_text(encoding="utf-8")
        self.assertIn('[string]$Decision = "NO-GO"', finalize)
        self.assertIn('if ($Decision -eq "GO" -and -not $allPassed)', finalize)
        self.assertIn('if ([string]$state.phase -ne "regranted")', finalize)
        self.assertIn("Stop-RecordedStack", finalize)
        self.assertIn("ports_free = $portsFree", finalize)
        self.assertIn("admin_key_deleted", finalize)
        self.assertIn("credential_data_included = $false", finalize)
        self.assertIn("public_network = $false", finalize)
        self.assertIn("production_activation = $false", finalize)
        self.assertIn('$receipt["receipt_sha256"]', finalize)
        self.assertNotIn("pairing_code", finalize)
        self.assertNotIn("MODELRIG_ADMIN_KEY", finalize)

    def test_wrapper_routes_responsibilities_to_single_entrypoints(self) -> None:
        wrapper = WRAPPER.read_text(encoding="utf-8")
        core = CORE_COMPAT.read_text(encoding="utf-8")
        self.assertIn(
            '"Record" { Join-Path $PSScriptRoot "agent4-physical-read-record.ps1" }',
            wrapper,
        )
        self.assertIn(
            '"Finalize" { Join-Path $PSScriptRoot "agent4-physical-read-finalize.ps1" }',
            wrapper,
        )
        self.assertIn(
            'default { Join-Path $PSScriptRoot "agent4-physical-read-operator-core.ps1" }',
            wrapper,
        )
        self.assertIn("agent4-physical-read-safety-gate.ps1", wrapper)
        self.assertIn("-Target $target", wrapper)
        self.assertIn("-ActionName $action", wrapper)
        self.assertIn("-ForwardArgs $forward", wrapper)
        self.assertIn("agent4-physical-read-process.ps1", core)
        self.assertNotIn("MODELRIG_ADMIN_KEY", wrapper + core)
        self.assertNotIn("receipt_sha256", wrapper + core)

    def test_launchers_only_call_stable_operator_and_start_requires_sha(self) -> None:
        launchers = {
            path.name: path.read_text(encoding="utf-8")
            for path in ROOT.glob("*AGENT4*PHYSICAL*TEST.cmd")
        }
        launchers.update(
            {
                path.name: path.read_text(encoding="utf-8")
                for path in ROOT.glob("MUTATE_AGENT4_*_SNAPSHOT.cmd")
            }
        )
        launchers.update(
            {
                path.name: path.read_text(encoding="utf-8")
                for path in ROOT.glob("RESTART_AGENT4_PHYSICAL_*.cmd")
            }
        )
        expected_names = {
            "START_AGENT4_PHYSICAL_READ_TEST.cmd",
            "ENABLE_AGENT4_PHYSICAL_READ_TEST.cmd",
            "GRANT_AGENT4_PHYSICAL_READ_TEST.cmd",
            "REVOKE_AGENT4_PHYSICAL_READ_TEST.cmd",
            "REGRANT_AGENT4_PHYSICAL_READ_TEST.cmd",
            "FINALIZE_AGENT4_PHYSICAL_READ_TEST.cmd",
            "STOP_AGENT4_PHYSICAL_READ_TEST.cmd",
            "STATUS_AGENT4_PHYSICAL_READ_TEST.cmd",
            "MUTATE_AGENT4_CAMPAIGN_SNAPSHOT.cmd",
            "MUTATE_AGENT4_SUMMARY_SNAPSHOT.cmd",
            "RESTART_AGENT4_PHYSICAL_WORKER.cmd",
            "RESTART_AGENT4_PHYSICAL_BACKEND.cmd",
        }
        self.assertTrue(expected_names.issubset(launchers))
        for name in expected_names:
            self.assertIn("agent4-physical-read-operator.ps1", launchers[name])
        start = launchers["START_AGENT4_PHYSICAL_READ_TEST.cmd"]
        self.assertIn("40-tegns-exact-SHA", start)
        self.assertIn("-ExpectedSha", start)
        self.assertIn("exit /b 2", start)

    def test_transition_block_prevents_wildcard_exposure(self) -> None:
        gate = SAFETY_GATE.read_text(encoding="utf-8")
        self.assertIn("Add-SafetyTransitionBlock", gate)
        self.assertIn("-Action Block", gate)
        self.assertIn("-LocalPort 8080", gate)
        self.assertIn("-Profile Any", gate)
        self.assertIn("Remove-SafetyTransitionBlock", gate)
        self.assertLess(
            gate.index("Add-SafetyTransitionBlock", gate.index('"PrepareOff"')),
            gate.index("& $Target @ForwardArgs", gate.index('"PrepareOff"')),
        )
        self.assertLess(
            gate.index("Add-SafetyTransitionBlock", gate.index('"Enable"')),
            gate.index("& $Target @ForwardArgs", gate.index('"Enable"')),
        )

    def test_backend_is_rebound_to_one_private_nonvirtual_interface(self) -> None:
        gate = SAFETY_GATE.read_text(encoding="utf-8")
        self.assertIn("Test-PrivateIpv4Strict", gate)
        self.assertIn(
            "tailscale|vethernet|wsl|hyper-v|docker|loopback|vmware|virtualbox",
            gate,
        )
        self.assertIn('NetworkCategory -eq "Public"', gate)
        self.assertIn('set "MODELRIG_HOST=0.0.0.0"', gate)
        self.assertIn('set "MODELRIG_HOST=', gate)
        self.assertIn("-LocalAddress $lan.address", gate)
        self.assertIn("-RemoteAddress LocalSubnet", gate)
        self.assertIn("-Profile Private,Domain", gate)
        self.assertIn("Test-ExpectedBackend", gate)
        self.assertIn("Test-ExpectedWorker", gate)
        self.assertIn('LocalAddress -eq "127.0.0.1"', gate)

    def test_only_same_physical_google_pixel_is_accepted(self) -> None:
        gate = SAFETY_GATE.read_text(encoding="utf-8")
        for required in (
            "Get-PhysicalPixel",
            "ro.kernel.qemu",
            "ro.boot.qemu",
            '$manufacturer -ine "Google"',
            '$model -notmatch "^Pixel\\b"',
            "ADB-enheden skiftede",
            "A4-18 accepterer ikke en Android-emulator",
            "Assert-SamePhysicalPixel",
            "adb_serial_sha256",
        ):
            self.assertIn(required, gate)

    def test_grant_cli_uses_only_a_transient_loopback_bridge(self) -> None:
        gate = SAFETY_GATE.read_text(encoding="utf-8")
        self.assertIn("Invoke-WithLoopbackAdminBridge", gate)
        self.assertIn("listenaddress=127.0.0.1 listenport=8080", gate)
        self.assertIn("connectaddress=$ConnectAddress connectport=8080", gate)
        self.assertIn("finally", gate)
        self.assertIn("Remove-LoopbackAdminBridge", gate)

    def test_cleanup_and_final_receipt_are_fail_closed(self) -> None:
        gate = SAFETY_GATE.read_text(encoding="utf-8")
        self.assertIn("Stop-StackBeforeTransition", gate)
        self.assertIn("Assert-PortsFree", gate)
        self.assertIn("Ukendte processer bevares", gate)
        finalize_block = gate[gate.index('"Finalize"') :]
        self.assertLess(
            finalize_block.index("Stop-StackBeforeTransition"),
            finalize_block.index("& $Target @ForwardArgs"),
        )
        self.assertIn("Patch-FinalReceipt", finalize_block)
        self.assertIn("artifacts_hashed_after_prestop = $true", gate)
        self.assertIn("physical_pixel = $true", gate)
        self.assertIn("wildcard_binding = $false", gate)
        self.assertIn("public_network = $false", gate)
        self.assertIn("production_activation = $false", gate)
        self.assertNotIn("MODELRIG_ADMIN_KEY", gate)


if __name__ == "__main__":
    unittest.main()
