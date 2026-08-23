#!/usr/bin/env python3
"""Static safety/authority contracts for the current-main A4-18R harness."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class A418rOperatorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.operator = read("scripts/agent4_a4_18r_physical_operator.ps1")
        self.fault_window = read("scripts/agent4_a4_18r_fault_window.ps1")
        self.fault_host = read("scripts/agent4_a4_18r_fault_host.py")
        self.runbook = read("docs/agent4/A4-18R_PHYSICAL_READ_PRODUCT.md")
        self.workflow = read(".github/workflows/agent4-a4-18r-harness.yml")

    def test_operator_is_exact_head_external_output_and_never_wildcard_bound(self) -> None:
        self.assertIn("status --porcelain", self.operator)
        self.assertIn("Forkert checkout", self.operator)
        self.assertIn("output må ikke ligge i repositoryet", self.operator)
        self.assertIn("filesystem-roden", self.operator)
        self.assertNotIn("0.0.0.0", self.operator)
        self.assertNotIn("netsh", self.operator.lower())
        self.assertNotIn("portproxy", self.operator.lower())
        self.assertNotRegex(self.operator, re.compile(r"(?i)taskkill|Get-NetTCPConnection[^\n]+\|[^\n]+Stop-Process"))

    def test_lan_boundary_is_one_private_interface_and_one_physical_pixel(self) -> None:
        self.assertIn("RFC1918", self.operator)
        self.assertIn('NetworkCategory -ne "Private"', self.operator)
        self.assertIn("RemoteAddress $PixelIp", self.operator)
        self.assertIn("LocalAddress $Address", self.operator)
        self.assertIn("-Profile Private", self.operator)
        self.assertIn("ro.kernel.qemu", self.operator)
        self.assertIn("ro.boot.qemu", self.operator)
        self.assertIn('manufacturer -ne "Google"', self.operator)
        self.assertIn('model -notmatch "^Pixel', self.operator)
        self.assertIn("Der skal være præcis én online ADB-enhed", self.operator)

    def test_worker_is_loopback_and_grant_mutation_uses_backend_single_writer_on_loopback(self) -> None:
        self.assertIn('"--host", "127.0.0.1"', self.operator)
        self.assertIn("KALIV_AGENT4_DATA_ROOT", self.operator)
        self.assertIn('Start-Backend -HostAddress "127.0.0.1" -OperatorEnabled:$true -GrantAdmin:$true', self.operator)
        self.assertIn('-url "http://127.0.0.1:$backendPort"', self.operator)
        self.assertIn("MODELRIG_DATA = $pairingData", self.operator)
        self.assertIn("Stop-RecordedProcess -ProcessId ([int]$State.backend_pid) -Kind backend", self.operator)
        self.assertNotRegex(self.operator, re.compile(r"(?i)(Set-Content|WriteAllText)[^\n]*\$pairingData"))
        self.assertNotIn("SetAgent4ReadGrant", self.operator)

    def test_isolated_android_variant_still_compiles_current_product_sources(self) -> None:
        self.assertIn('dk.ternedal.modelrig.a425f', self.operator)
        self.assertIn(':app:assembleA425f', self.operator)
        for path in (
            "Agent4OperatorClient.kt",
            "Agent4OperatorScreen.kt",
            "Agent4CampaignDetailScreen.kt",
        ):
            self.assertIn(path, self.operator)
        self.assertIn(':app:compileA425fKotlin', self.workflow)
        self.assertIn(':app:processA425fMainManifest', self.workflow)
        self.assertIn("current product sources", self.workflow.lower())

    def test_malformed_wire_case_is_reproducible_and_reversible(self) -> None:
        self.assertIn("operator-api/unknown-physical-fault", self.fault_host)
        self.assertIn("application/vnd.modelrig.agent4.operator+json", self.fault_host)
        self.assertNotIn("Authorization", self.fault_host)
        self.assertIn("no credential", self.fault_host.lower())
        self.assertIn("Read-Host", self.fault_window)
        self.assertIn("agent4_a4_18r_fault_host.py", self.fault_window)
        self.assertIn("Start-RealBackend", self.fault_window)
        self.assertIn("KALIV_AGENT4_GRANT_ADMIN = \"0\"", self.fault_window)
        self.assertIn("malformed_schema_fail_closed", self.runbook)

    def test_receipt_contract_has_no_screenshot_or_credential_acceptance_path(self) -> None:
        self.assertNotIn("ScreenshotPath", self.operator)
        self.assertNotIn("screenshot", self.operator.lower())
        self.assertIn("credential_data_included = $false", self.operator)
        self.assertIn("public_network = $false", self.operator)
        self.assertIn("production_activation = $false", self.operator)
        self.assertIn("admin-key.txt", self.operator)
        self.assertIn("Remove-Item -LiteralPath $adminKeyFile", self.operator)
        self.assertIn("Remove-Item -LiteralPath $pairingData", self.operator)

    def test_replace_refuses_foreign_workspace_and_cleanup_proves_original_pids(self) -> None:
        self.assertIn("eksisterende A4-18R workspace tilhører en anden exact SHA", self.operator)
        self.assertIn("$recordedBackendPid", self.operator)
        self.assertIn("$recordedWorkerPid", self.operator)
        self.assertIn("unknown_process_preserved", self.operator)

    def test_runbook_uses_fresh_current_main_authority_not_historical_a4_18_heads(self) -> None:
        self.assertIn("fresh current-main exact SHA", self.runbook)
        self.assertIn("agent4-a4-18r-harness", self.runbook)
        self.assertIn("exact-head-qualification", self.runbook)
        self.assertIn("#421", self.runbook)
        self.assertNotIn("ae353bb851f557195920969a7bb087742840d5e5", self.runbook)
        self.assertNotIn("218019fd47ea90b046a334253ab5fd84485f772a", self.runbook)
        self.assertNotIn("agent/a4-18-physical-read-product", self.runbook)
        full_sha = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
        self.assertIsNone(full_sha.search(self.runbook), "runbook must not hard-code a launch SHA")

    def test_special_workflow_qualifies_exact_head_and_all_harness_layers(self) -> None:
        self.assertIn("Assert exact checkout authority", self.workflow)
        self.assertIn("workflow_agent4_a4_18r_fixture.py", self.workflow)
        self.assertIn("workflow_agent4_a4_18r_operator_contract.py", self.workflow)
        self.assertIn("workflow_agent4_a4_18r_audit.py", self.workflow)
        self.assertIn("go test ./cmd/modelrig-server ./cmd/modelrig-agent4-grants ./internal/httpapi", self.workflow)
        self.assertIn("Parse A4-18R PowerShell harness", self.workflow)


if __name__ == "__main__":
    unittest.main()
