#!/usr/bin/env python3
"""Static safety/authority contracts for the A4-25f physical operator."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class A425fPhysicalOperatorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.operator = _read("scripts/agent4_a4_25f_physical_operator.ps1")
        self.cursor = _read("scripts/agent4_a4_25f_cursor_matrix.ps1")
        self.host = _read("scripts/agent4_a4_25f_physical_host.py")
        self.mutate = _read("scripts/agent4_a4_25f_physical_mutate.py")
        self.backend = _read("backend/cmd/modelrig-a4-25f-backend/main.go")
        self.gradle = _read("android/app/build.gradle.kts")
        self.main_manifest = _read("android/app/src/main/AndroidManifest.xml")
        self.physical_manifest = _read("android/app/src/a425f/AndroidManifest.xml")
        self.workflow = _read(".github/workflows/agent4-a4-25f-harness.yml")

    def test_physical_app_has_a_separate_application_identity_and_source_set(self) -> None:
        self.assertIn('create("a425f")', self.gradle)
        self.assertIn('applicationIdSuffix = ".a425f"', self.gradle)
        self.assertIn('isDebuggable = true', self.gradle)
        self.assertNotIn("Agent4SnapshotPhysicalProbeActivity", self.main_manifest)
        for activity in (
            "Agent4PhysicalDeviceInfoActivity",
            "Agent4PhysicalCursorProbeActivity",
            "Agent4PhysicalFailureProbeActivity",
            "Agent4SnapshotPhysicalProbeActivity",
        ):
            self.assertIn(activity, self.physical_manifest)
        self.assertIn('dk.ternedal.modelrig.a425f', self.operator)
        self.assertNotIn('src/debug', self.operator)

    def test_worker_is_read_only_loopback_and_retention_clock_is_bounded(self) -> None:
        self.assertIn('LOOPBACK = "127.0.0.1"', self.host)
        self.assertIn("worker_authority", self.host.replace("writer_authority", "worker_authority", 1))
        self.assertIn('"writer_authority": False', self.host)
        self.assertIn('"publication_authority": False', self.host)
        self.assertIn('MAX_CLOCK_OFFSET_MINUTES = 120', self.host)
        self.assertIn('if args.host != LOOPBACK', self.host)
        self.assertNotIn("compose_agent4_runtime", self.host)

    def test_backend_has_exact_private_lan_and_separate_loopback_admin_boundary(self) -> None:
        self.assertIn('net.Listen("tcp4", net.JoinHostPort(lanHost', self.backend)
        self.assertIn('net.Listen("tcp4", net.JoinHostPort("127.0.0.1"', self.backend)
        self.assertIn('ip.IsLoopback() || ip.IsUnspecified() || !ip.IsPrivate()', self.backend)
        self.assertIn('r.URL.Path == "/api/v1/pair/start"', self.backend)
        self.assertIn('strings.HasPrefix(r.URL.Path, "/api/v1/admin/")', self.backend)
        self.assertIn('MODELRIG_ADMIN_KEY', self.backend)
        self.assertIn('KALIV_AGENT4_OPERATOR_API', self.backend)
        self.assertIn('KALIV_AGENT4_GRANT_ADMIN', self.backend)
        self.assertNotIn('0.0.0.0', self.backend)

    def test_windows_operator_uses_exact_clean_head_and_narrow_firewall(self) -> None:
        self.assertIn('status --porcelain', self.operator)
        self.assertIn('Forkert checkout', self.operator)
        self.assertIn('RemoteAddress = $PixelIp', self.operator)
        self.assertIn('LocalAddress = $Address', self.operator)
        self.assertIn('Profile = "Private"', self.operator)
        self.assertIn('Program = $backendExe', self.operator)
        self.assertIn('Remove-A4FirewallRule', self.operator)
        self.assertIn('uninstall $packageName', self.operator)
        self.assertIn('Remove-Item -LiteralPath $backendData', self.operator)
        self.assertNotIn('0.0.0.0', self.operator)

    def test_credentials_are_ephemeral_and_never_part_of_receipt_schema(self) -> None:
        self.assertIn('New-EphemeralAdminKey', self.operator)
        self.assertIn('$env:MODELRIG_ADMIN_KEY = $key', self.operator)
        self.assertIn('Remove-Item Env:MODELRIG_ADMIN_KEY', self.operator)
        self.assertNotRegex(self.operator, re.compile(r'(?i)putString\([^\n]*token'))
        self.assertNotIn('pairing_code', self.operator.lower())
        self.assertNotRegex(self.operator, re.compile(r'(?im)^\s*admin_key\s*='))
        self.assertNotIn('"admin_key"', self.operator.lower())
        for text in (self.operator, self.cursor):
            self.assertIn('credential_in_receipt = $false', text)
            self.assertIn('raw_cursor_in_receipt = $false', text)
            self.assertIn('production_activation = $false', text)

    def test_mutation_matrix_targets_a_second_page_delete_and_never_dispatches(self) -> None:
        self.assertIn('DELETE_CAMPAIGN_ID = "a4-25f-physical-030"', self.mutate)
        self.assertIn('A4-25f mutation forbids dispatch', self.mutate)
        self.assertIn('A4-25f mutation forbids signal', self.mutate)
        self.assertIn('second-page delete-target', self.operator.lower())
        self.assertIn('campaign-add', self.operator)
        self.assertIn('campaign-delete', self.operator)
        self.assertIn('campaign-transition', self.operator)
        self.assertGreaterEqual(self.operator.count('evidence-append'), 2)

    def test_physical_matrix_exercises_restart_retention_and_wire_fail_closed_cases(self) -> None:
        for marker in (
            'worker_restart_tested = $true',
            'backend_restart_tested = $true',
            'android_process_restart_tested = $true',
            'expired_retained_root_tested = $true',
            'selected_root_404_tested = $true',
            'server_422_tested = $true',
            'unavailable_503_tested = $true',
            'ClockOffsetMinutes 16',
            'current-unavailable-503',
            'expired-retained-410',
            'unknown-root',
            'fresh-root',
        ):
            self.assertIn(marker, self.operator)
        for stage in (
            'root-mismatch',
            'resource-mismatch',
            'filter-mismatch',
            'campaign-mismatch',
        ):
            self.assertIn(stage, self.cursor)

    def test_old_a4_18_physical_harness_is_not_reused(self) -> None:
        for text in (self.operator, self.cursor):
            self.assertNotIn('agent4-physical-read-', text)
            self.assertNotIn('ae353bb851f557195920969a7bb087742840d5e5', text)
        self.assertFalse((ROOT / "scripts" / "agent4-physical-read-common.ps1").exists())

    def test_special_workflow_compiles_physical_variant_and_runs_offline_harness(self) -> None:
        self.assertIn(':app:compileA425fKotlin', self.workflow)
        self.assertIn(':app:processA425fMainManifest', self.workflow)
        self.assertIn('workflow_agent4_a4_25f_physical_snapshot_harness.py', self.workflow)
        self.assertIn('Assert exact checkout authority', self.workflow)


if __name__ == "__main__":
    unittest.main()
