#!/usr/bin/env python3
"""A4-18 safety gate hardens the physical harness before hardware use."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
GATE = SCRIPTS / "agent4-physical-read-safety-gate.ps1"
WRAPPER = SCRIPTS / "agent4-physical-read-operator.ps1"


class Agent4PhysicalReadSafetyGateTests(unittest.TestCase):
    def test_all_launchers_are_forced_through_the_safety_gate(self) -> None:
        wrapper = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("agent4-physical-read-safety-gate.ps1", wrapper)
        self.assertIn("-Target $target", wrapper)
        self.assertIn("-ActionName $action", wrapper)
        self.assertIn("-ForwardArgs $forward", wrapper)
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

    def test_transition_block_prevents_wildcard_exposure(self) -> None:
        gate = GATE.read_text(encoding="utf-8")
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
        gate = GATE.read_text(encoding="utf-8")
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
        gate = GATE.read_text(encoding="utf-8")
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
        gate = GATE.read_text(encoding="utf-8")
        self.assertIn("Invoke-WithLoopbackAdminBridge", gate)
        self.assertIn(
            "listenaddress=127.0.0.1 listenport=8080",
            gate,
        )
        self.assertIn("connectaddress=$ConnectAddress connectport=8080", gate)
        self.assertIn("finally", gate)
        self.assertIn("Remove-LoopbackAdminBridge", gate)

    def test_cleanup_and_final_receipt_are_fail_closed(self) -> None:
        gate = GATE.read_text(encoding="utf-8")
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
