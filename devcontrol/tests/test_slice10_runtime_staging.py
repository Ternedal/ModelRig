from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from kaliv_dev_control.catalog import (
    IsolationAttestation,
    IsolationBoundary,
    ModelRigCommandCatalog,
    NetworkMode,
    ProjectCommandSpec,
    ToolBinding,
    Toolchain,
)
from kaliv_dev_control.commands import CommandRegistry, CommandTemplate
from kaliv_dev_control.contract import DevelopmentTask
from kaliv_dev_control.runtime_staging import (
    RUNTIME_STAGING_SCHEMA,
    RuntimeStagingError,
    RuntimeStagingReceipt,
    TrustedRuntimeStager,
)
from kaliv_dev_control.tier_a_execution import (
    LeasedCommandRegistry,
    TierAExecutionLease,
    workspace_root_authority_sha256,
)

BASE_SHA = "a" * 40
COMMAND_ID = "modelrig.runtime.probe"
TOOL_ID = "probe"


def development_task(command_id: str = COMMAND_ID) -> DevelopmentTask:
    return DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "A10_STAGE",
            "repository": "Ternedal/ModelRig",
            "base_sha": BASE_SHA,
            "goal": "Stage one reviewed runtime without granting execution.",
            "acceptance_criteria": [
                "The staged executable is deterministic and hash bound."
            ],
            "risk": "low",
            "allowed_paths": ["devcontrol/**"],
            "protected_paths": ["devcontrol/secrets/**"],
            "allowed_command_ids": [command_id],
            "required_tests": [command_id],
            "budget": {
                "max_changed_files": 20,
                "max_added_lines": 5000,
                "max_deleted_lines": 5000,
                "max_attempts": 2,
                "max_runtime_seconds": 3600,
                "max_output_bytes": 1000000,
            },
            "merge_authority": "human",
        }
    )


def make_authority(
    root: Path,
    *,
    payload: bytes = b"trusted standalone runtime\n",
    source_outside_trusted_root: bool = False,
):
    trusted = root / "trusted"
    workspace = root / "workspace"
    outside = root / "outside"
    trusted.mkdir()
    workspace.mkdir()
    outside.mkdir()
    source_root = outside if source_outside_trusted_root else trusted
    source = source_root / "probe.exe"
    source.write_bytes(payload)
    executable_sha256 = hashlib.sha256(payload).hexdigest()

    task = development_task()
    catalog = ModelRigCommandCatalog(
        (
            ProjectCommandSpec(
                COMMAND_ID,
                TOOL_ID,
                ("--version",),
                ".",
                30,
                {},
            ),
        )
    )
    toolchain = Toolchain(
        (
            ToolBinding(
                TOOL_ID,
                str(source.resolve()),
                executable_sha256,
            ),
        )
    )
    task_sha256 = hashlib.sha256(task.canonical_json().encode()).hexdigest()
    evidence_sha256 = "d" * 64
    attestation = IsolationAttestation(
        task_id=task.task_id,
        task_sha256=task_sha256,
        repository=task.repository,
        base_sha=task.base_sha,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        evidence_sha256=(evidence_sha256,),
    )
    lease = TierAExecutionLease(
        task_id=task.task_id,
        task_sha256=task_sha256,
        repository=task.repository,
        base_sha=task.base_sha,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        evidence_sha256=(evidence_sha256,),
        signed_report_sha256=evidence_sha256,
        report_id="runtime-staging-test",
        rig_id="runtime-staging-rig",
        rig_fingerprint_sha256="e" * 64,
        toolhost_sha256="f" * 64,
        workspace_root_sha256=workspace_root_authority_sha256(workspace.resolve()),
        completed_at="2026-08-03T12:00:00Z",
        key_id="operator-key-test",
    )
    registry = LeasedCommandRegistry(
        CommandRegistry(
            (
                CommandTemplate(
                    COMMAND_ID,
                    (str(source.resolve()), "--version"),
                    ".",
                    30,
                    {},
                ),
            )
        ),
        lease,
        task=task,
        catalog=catalog,
        toolchain=toolchain,
        attestation=attestation,
    )
    return task, registry, trusted.resolve(), workspace.resolve(), source.resolve()


class TrustedRuntimeStagingTests(unittest.TestCase):
    def test_stage_is_deterministic_and_schema_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, source = make_authority(
                Path(directory)
            )
            stager = TrustedRuntimeStager(trusted, workspace)
            first = stager.stage(registry, task, COMMAND_ID)
            second = stager.stage(registry, task, COMMAND_ID)

            self.assertEqual(first, second)
            staged = stager.verify(first, registry, task, COMMAND_ID)
            self.assertEqual(staged.read_bytes(), source.read_bytes())
            self.assertEqual(
                first.staged_relative_path,
                f".kaliv/runtime/{TOOL_ID}/{first.executable_sha256}/probe.exe",
            )
            self.assertEqual(first.schema, RUNTIME_STAGING_SCHEMA)
            self.assertEqual(
                RuntimeStagingReceipt.from_mapping(first.to_dict()).canonical_json(),
                first.canonical_json(),
            )
            self.assertNotIn(str(source), first.canonical_json())

    def test_source_outside_operator_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _ = make_authority(
                Path(directory), source_outside_trusted_root=True
            )
            with self.assertRaisesRegex(
                RuntimeStagingError, "outside the operator-controlled root"
            ):
                TrustedRuntimeStager(trusted, workspace).stage(
                    registry, task, COMMAND_ID
                )

    def test_source_hash_change_is_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, source = make_authority(
                Path(directory)
            )
            source.write_bytes(b"changed after toolchain binding")
            with self.assertRaisesRegex(RuntimeStagingError, "hash mismatch"):
                TrustedRuntimeStager(trusted, workspace).stage(
                    registry, task, COMMAND_ID
                )

    def test_source_change_invalidates_a_persisted_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, source = make_authority(
                Path(directory)
            )
            stager = TrustedRuntimeStager(trusted, workspace)
            receipt = stager.stage(registry, task, COMMAND_ID)
            source.write_bytes(b"operator source changed later")
            with self.assertRaisesRegex(RuntimeStagingError, "source hash mismatch"):
                stager.verify(receipt, registry, task, COMMAND_ID)

    def test_staged_tamper_is_rejected_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _ = make_authority(Path(directory))
            stager = TrustedRuntimeStager(trusted, workspace)
            receipt = stager.stage(registry, task, COMMAND_ID)
            staged = workspace.joinpath(*Path(receipt.staged_relative_path).parts)
            os.chmod(staged, 0o755)
            staged.write_bytes(b"tampered staged bytes")

            with self.assertRaisesRegex(RuntimeStagingError, "no longer match"):
                stager.verify(receipt, registry, task, COMMAND_ID)
            with self.assertRaisesRegex(
                RuntimeStagingError, "already exists with different bytes"
            ):
                stager.stage(registry, task, COMMAND_ID)
            self.assertEqual(staged.read_bytes(), b"tampered staged bytes")

    def test_receipt_cannot_be_rebound_to_another_task(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _ = make_authority(Path(directory))
            stager = TrustedRuntimeStager(trusted, workspace)
            receipt = stager.stage(registry, task, COMMAND_ID)
            other = DevelopmentTask.from_mapping(
                {**task.to_dict(), "task_id": "OTHER_A10"}
            )
            with self.assertRaisesRegex(Exception, "another task"):
                stager.verify(receipt, registry, other, COMMAND_ID)

    def test_nested_authority_roots_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            trusted = root / "trusted"
            workspace = trusted / "workspace"
            workspace.mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeStagingError, "separate trees"):
                TrustedRuntimeStager(trusted, workspace)

    def test_staging_budget_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _ = make_authority(
                Path(directory), payload=b"1234567890"
            )
            with self.assertRaisesRegex(RuntimeStagingError, "staging budget"):
                TrustedRuntimeStager(
                    trusted, workspace, max_executable_bytes=4
                ).stage(registry, task, COMMAND_ID)

    def test_schema_matches_canonical_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _ = make_authority(Path(directory))
            receipt = TrustedRuntimeStager(trusted, workspace).stage(
                registry, task, COMMAND_ID
            )
            root = Path(__file__).resolve().parents[2]
            schema = json.loads(
                (
                    root
                    / "devcontrol/schemas/development-runtime-staging-receipt-v1.schema.json"
                ).read_text(encoding="utf-8")
            )
            fields = set(receipt.to_dict())
            self.assertEqual(set(schema["required"]), fields)
            self.assertEqual(set(schema["properties"]), fields)
            self.assertFalse(schema["additionalProperties"])

    def test_linked_source_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task, _, trusted, workspace, source = make_authority(root)
            linked = trusted / "linked.exe"
            try:
                linked.symlink_to(source)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")

            payload = source.read_bytes()
            catalog = ModelRigCommandCatalog(
                (
                    ProjectCommandSpec(
                        COMMAND_ID, TOOL_ID, ("--version",), ".", 30, {}
                    ),
                )
            )
            toolchain = Toolchain(
                (
                    ToolBinding(
                        TOOL_ID,
                        str(linked.absolute()),
                        hashlib.sha256(payload).hexdigest(),
                    ),
                )
            )
            task_sha256 = hashlib.sha256(task.canonical_json().encode()).hexdigest()
            evidence_sha256 = "d" * 64
            attestation = IsolationAttestation(
                task_id=task.task_id,
                task_sha256=task_sha256,
                repository=task.repository,
                base_sha=task.base_sha,
                catalog_sha256=catalog.sha256,
                toolchain_sha256=toolchain.sha256,
                boundary=IsolationBoundary.OS_ISOLATED,
                network_mode=NetworkMode.DENY,
                evidence_sha256=(evidence_sha256,),
            )
            lease = TierAExecutionLease(
                task_id=task.task_id,
                task_sha256=task_sha256,
                repository=task.repository,
                base_sha=task.base_sha,
                catalog_sha256=catalog.sha256,
                toolchain_sha256=toolchain.sha256,
                boundary=IsolationBoundary.OS_ISOLATED,
                network_mode=NetworkMode.DENY,
                evidence_sha256=(evidence_sha256,),
                signed_report_sha256=evidence_sha256,
                report_id="runtime-staging-link-test",
                rig_id="runtime-staging-rig",
                rig_fingerprint_sha256="e" * 64,
                toolhost_sha256="f" * 64,
                workspace_root_sha256=workspace_root_authority_sha256(workspace),
                completed_at="2026-08-03T12:00:00Z",
                key_id="operator-key-test",
            )
            registry = LeasedCommandRegistry(
                CommandRegistry(
                    (
                        CommandTemplate(
                            COMMAND_ID,
                            (str(linked.absolute()), "--version"),
                            ".",
                            30,
                            {},
                        ),
                    )
                ),
                lease,
                task=task,
                catalog=catalog,
                toolchain=toolchain,
                attestation=attestation,
            )
            with self.assertRaisesRegex(RuntimeStagingError, "links or junctions"):
                TrustedRuntimeStager(trusted, workspace).stage(
                    registry, task, COMMAND_ID
                )


if __name__ == "__main__":
    unittest.main()
