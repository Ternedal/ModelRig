from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from kaliv_dev_control.catalog import IsolationBoundary, NetworkMode
from kaliv_dev_control.tier_a_authority import (
    TIER_A_APPLICATION_ENVIRONMENT,
    TierAExecutionLease,
    TierALaunchPlan as TierALaunchPlanV1,
    working_directory_authority_sha256,
)
from kaliv_dev_control.tier_a_plan import TierALaunchPlan as TierALaunchPlanV3
from kaliv_dev_control.tier_a_result import (
    TierAExecutionResult,
    TierAOutputStream,
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

    def test_v1_launch_plan_compatibility_schema_remains_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            plan = TierALaunchPlanV1(
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
                TierALaunchPlanV1.from_mapping(
                    plan.to_dict()
                ).canonical_json(),
                plan.canonical_json(),
            )

    def test_v3_launch_plan_schema_matches_canonical_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            plan = TierALaunchPlanV3(
                task_id="A9_SCHEMA",
                task_sha256=HASH_A,
                base_sha="1" * 40,
                command_id="modelrig.schema.probe",
                argv=(str((workspace / "probe.exe").resolve()), "--version"),
                cwd=".",
                max_timeout_seconds=30,
                max_output_bytes=4096,
                env=TIER_A_APPLICATION_ENVIRONMENT,
                catalog_sha256=HASH_B,
                toolchain_sha256=HASH_C,
                lease_sha256=HASH_D,
                signed_report_sha256=HASH_E,
                workspace_root=str(workspace),
                workspace_root_sha256=HASH_F,
                executable_sha256="0" * 64,
                toolhost_sha256="1" * 64,
                working_directory_sha256=working_directory_authority_sha256(
                    workspace, "."
                ),
                boundary=IsolationBoundary.OS_ISOLATED,
                network_mode=NetworkMode.DENY,
            )
            root = Path(__file__).resolve().parents[2]
            schema = json.loads(
                (
                    root
                    / "devcontrol/schemas/development-tier-a-launch-plan-v3.schema.json"
                ).read_text(encoding="utf-8")
            )
            fields = set(plan.to_dict())
            self.assertEqual(set(schema["required"]), fields)
            self.assertEqual(set(schema["properties"]), fields)
            self.assertFalse(
                schema["properties"]["env"]["additionalProperties"]
            )
            self.assertEqual(
                TierALaunchPlanV3.from_mapping(
                    plan.to_dict()
                ).canonical_json(),
                plan.canonical_json(),
            )

    def test_execution_result_schema_matches_canonical_artifact(self) -> None:
        stdout_bytes = b"captured stdout\n"
        stderr_bytes = b""
        stdout = TierAOutputStream(
            captured=stdout_bytes,
            sha256=hashlib.sha256(stdout_bytes).hexdigest(),
            total_bytes=len(stdout_bytes),
            truncated=False,
        )
        stderr = TierAOutputStream(
            captured=stderr_bytes,
            sha256=hashlib.sha256(stderr_bytes).hexdigest(),
            total_bytes=0,
            truncated=False,
        )
        result = TierAExecutionResult.create(
            task_id="A9_SCHEMA",
            task_sha256=HASH_A,
            base_sha="1" * 40,
            command_id="modelrig.schema.probe",
            plan_sha256=HASH_B,
            lease_sha256=HASH_C,
            signed_report_sha256=HASH_D,
            returncode=0,
            duration_ms=25,
            timed_out=False,
            max_output_bytes=4096,
            stdout=stdout,
            stderr=stderr,
        )
        root = Path(__file__).resolve().parents[2]
        schema = json.loads(
            (
                root
                / "devcontrol/schemas/development-tier-a-execution-result-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        fields = set(result.to_dict())
        self.assertEqual(set(schema["required"]), fields)
        self.assertEqual(set(schema["properties"]), fields)
        stream_fields = set(result.stdout.to_dict())
        self.assertEqual(
            set(schema["$defs"]["stream"]["required"]), stream_fields
        )
        self.assertEqual(
            set(schema["$defs"]["stream"]["properties"]), stream_fields
        )
        self.assertEqual(
            TierAExecutionResult.from_mapping(
                result.to_dict()
            ).canonical_json(),
            result.canonical_json(),
        )


if __name__ == "__main__":
    unittest.main()
