from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kaliv_dev_control.catalog import IsolationBoundary, NetworkMode
from kaliv_dev_control.tier_a_authority import (
    TierAExecutionLease,
    TierALaunchPlan,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64


class TierASchemaParityTests(unittest.TestCase):
    def test_execution_lease_schema_matches_canonical_artifact(self) -> None:
        lease = TierAExecutionLease(
            task_id="A9_SCHEMA",
            task_sha256=HASH_A,
            repository="Ternedal/ModelRig",
            base_sha="1" * 40,
            catalog_sha256=HASH_B,
            toolchain_sha256=HASH_C,
            boundary=IsolationBoundary.OS_ISOLATED,
            network_mode=NetworkMode.DENY,
            evidence_sha256=(HASH_D,),
            signed_report_sha256=HASH_D,
            report_id="report-schema-test",
            rig_id="rig-schema-test",
            rig_fingerprint_sha256=HASH_E,
            toolhost_sha256=HASH_F,
            workspace_root_sha256="0" * 64,
            completed_at="2026-08-03T12:00:00Z",
            key_id="operator-key-schema",
        )
        root = Path(__file__).resolve().parents[2]
        schema = json.loads(
            (
                root
                / "devcontrol/schemas/development-execution-lease-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        fields = set(lease.to_dict())
        self.assertEqual(set(schema["required"]), fields)
        self.assertEqual(set(schema["properties"]), fields)
        self.assertEqual(
            TierAExecutionLease.from_mapping(
                lease.to_dict()
            ).canonical_json(),
            lease.canonical_json(),
        )

    def test_v1_launch_plan_schema_matches_canonical_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            plan = TierALaunchPlan(
                task_id="A9_SCHEMA",
                task_sha256=HASH_A,
                base_sha="1" * 40,
                command_id="modelrig.schema.probe",
                argv=(str((workspace / "probe.exe").resolve()), "--version"),
                cwd=".",
                max_timeout_seconds=30,
                env={"CI": "1", "MODELRIG_DEVCONTROL": "1"},
                catalog_sha256=HASH_B,
                toolchain_sha256=HASH_C,
                lease_sha256=HASH_D,
                signed_report_sha256=HASH_E,
                workspace_root=str(workspace),
                workspace_root_sha256=HASH_F,
                executable_sha256="0" * 64,
                toolhost_sha256="1" * 64,
                boundary=IsolationBoundary.OS_ISOLATED,
                network_mode=NetworkMode.DENY,
            )
            root = Path(__file__).resolve().parents[2]
            schema = json.loads(
                (
                    root
                    / "devcontrol/schemas/"
                    "development-tier-a-launch-plan-v1.schema.json"
                ).read_text(encoding="utf-8")
            )
            fields = set(plan.to_dict())
            self.assertEqual(set(schema["required"]), fields)
            self.assertEqual(set(schema["properties"]), fields)
            self.assertFalse(
                schema["properties"]["env"]["additionalProperties"]
            )
            self.assertEqual(
                TierALaunchPlan.from_mapping(
                    plan.to_dict()
                ).canonical_json(),
                plan.canonical_json(),
            )

    def test_later_slice_schemas_remain_absent(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for relative in (
            "devcontrol/schemas/development-tier-a-launch-plan-v2.schema.json",
            "devcontrol/schemas/development-tier-a-launch-plan-v3.schema.json",
            "devcontrol/schemas/development-tier-a-execution-result-v1.schema.json",
        ):
            self.assertFalse((root / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
