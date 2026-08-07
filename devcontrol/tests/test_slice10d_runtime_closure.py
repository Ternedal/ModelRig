from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

import kaliv_dev_control.tier_a_authority as tier_a_authority
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
from kaliv_dev_control.runtime_closure import (
    HmacRuntimeClosureSigner,
    RuntimeClosureError,
    RuntimeClosureFile,
    RuntimeClosureManifest,
    RuntimeClosureStagingReceipt,
    RuntimeClosureVerifier,
    SignedRuntimeClosureManifest,
    TrustedRuntimeClosureStager,
    trusted_runtime_root_sha256,
)
from kaliv_dev_control.tier_a_authority import (
    LeasedCommandRegistry,
    TierAExecutionError,
    TierAExecutionLease,
    tier_a_toolhost_sha256,
    working_directory_authority_sha256,
    workspace_root_authority_sha256,
)
from kaliv_dev_control.tier_a_plan import build_tier_a_launch_plan
from test_slice9 import create_control_plane

BASE_SHA = "a" * 40
COMMAND_ID = "modelrig.runtime.cwd-probe"
TOOL_ID = "closure-probe"
KEY_ID = "runtime-closure-test-key"
SECRET = b"runtime-closure-test-secret-0001"


def file_entry(root: Path, relative: str) -> RuntimeClosureFile:
    payload = root.joinpath(*Path(relative).parts).read_bytes()
    return RuntimeClosureFile(
        relative_path=relative,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def make_authority(root: Path):
    trusted = root / "trusted"
    workspace = root / "workspace"
    control = root / "control"
    (trusted / "bin").mkdir(parents=True)
    (trusted / "lib").mkdir()
    (workspace / "backend").mkdir(parents=True)
    control.mkdir()
    create_control_plane(control)

    executable = trusted / "bin" / "probe.exe"
    support = trusted / "lib" / "support.dat"
    executable.write_bytes(b"signed closure executable\n")
    support.write_bytes(b"signed closure support data\n")
    executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()

    task = DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "A10D_CLOSURE",
            "repository": "Ternedal/ModelRig",
            "base_sha": BASE_SHA,
            "goal": "Prove one signed runtime closure and exact nested cwd.",
            "acceptance_criteria": [
                "Only the signed exact runtime tree can be planned."
            ],
            "risk": "low",
            "allowed_paths": ["devcontrol/**"],
            "protected_paths": ["devcontrol/secrets/**"],
            "allowed_command_ids": [COMMAND_ID],
            "required_tests": [COMMAND_ID],
            "budget": {
                "max_changed_files": 20,
                "max_added_lines": 5000,
                "max_deleted_lines": 5000,
                "max_attempts": 2,
                "max_runtime_seconds": 120,
                "max_output_bytes": 4096,
            },
            "merge_authority": "human",
        }
    )
    catalog = ModelRigCommandCatalog(
        (
            ProjectCommandSpec(
                COMMAND_ID,
                TOOL_ID,
                ("cwd",),
                "backend",
                30,
                {"CI": "1"},
            ),
        )
    )
    toolchain = Toolchain(
        (ToolBinding(TOOL_ID, str(executable.resolve()), executable_hash),)
    )
    task_sha = hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()
    evidence_sha = "d" * 64
    attestation = IsolationAttestation(
        task_id=task.task_id,
        task_sha256=task_sha,
        repository=task.repository,
        base_sha=task.base_sha,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        evidence_sha256=(evidence_sha,),
    )
    lease = TierAExecutionLease(
        task_id=task.task_id,
        task_sha256=task_sha,
        repository=task.repository,
        base_sha=task.base_sha,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        evidence_sha256=(evidence_sha,),
        signed_report_sha256=evidence_sha,
        report_id="slice-10d-runtime-closure",
        rig_id="slice-10d-test-rig",
        rig_fingerprint_sha256="e" * 64,
        toolhost_sha256=tier_a_toolhost_sha256(control.resolve()),
        workspace_root_sha256=workspace_root_authority_sha256(workspace.resolve()),
        completed_at="2026-08-03T19:00:00Z",
        key_id="operator-key-test",
    )
    registry = LeasedCommandRegistry(
        CommandRegistry(
            (
                CommandTemplate(
                    COMMAND_ID,
                    (str(executable.resolve()), "cwd"),
                    "backend",
                    30,
                    {"CI": "1"},
                ),
            )
        ),
        lease,
        task=task,
        catalog=catalog,
        toolchain=toolchain,
        attestation=attestation,
    )
    files = tuple(
        sorted(
            (
                file_entry(trusted, "bin/probe.exe"),
                file_entry(trusted, "lib/support.dat"),
            ),
            key=lambda item: item.relative_path,
        )
    )
    manifest = RuntimeClosureManifest(
        task_id=task.task_id,
        task_sha256=task_sha,
        repository=task.repository,
        base_sha=task.base_sha,
        command_id=COMMAND_ID,
        tool_id=TOOL_ID,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        lease_sha256=lease.sha256,
        workspace_root_sha256=lease.workspace_root_sha256,
        trusted_runtime_root_sha256=trusted_runtime_root_sha256(trusted.resolve()),
        entrypoint_relative_path="bin/probe.exe",
        working_directory="backend",
        files=files,
        total_bytes=sum(item.size_bytes for item in files),
    )
    signed = HmacRuntimeClosureSigner(KEY_ID, SECRET).sign(manifest)
    verifier = RuntimeClosureVerifier({KEY_ID: SECRET})
    return (
        task,
        registry,
        trusted.resolve(),
        workspace.resolve(),
        control.resolve(),
        executable.resolve(),
        signed,
        verifier,
    )


class RuntimeClosureTests(unittest.TestCase):
    def test_signed_manifest_round_trips_canonically(self):
        with tempfile.TemporaryDirectory() as directory:
            *_, signed, _ = make_authority(Path(directory))
            reloaded = SignedRuntimeClosureManifest.from_mapping(signed.to_dict())
            self.assertEqual(reloaded.canonical_json(), signed.canonical_json())
            self.assertEqual(reloaded.sha256, signed.sha256)
            self.assertEqual(
                tuple(item.relative_path for item in reloaded.manifest.files),
                ("bin/probe.exe", "lib/support.dat"),
            )

    def test_exact_multifile_closure_stages_and_rebinds_only_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _, source, signed, verifier = (
                make_authority(Path(directory))
            )
            stager = TrustedRuntimeClosureStager(trusted, workspace)
            receipt = stager.stage(signed, verifier, registry, task, COMMAND_ID)
            rebound = stager.bind_for_launch(
                receipt, signed, verifier, registry, task, COMMAND_ID
            )
            template = rebound.resolve(task, COMMAND_ID)
            staged = Path(template.argv[0])

            self.assertNotEqual(staged, source)
            self.assertTrue(staged.is_relative_to(workspace))
            self.assertEqual(staged.read_bytes(), source.read_bytes())
            self.assertEqual(template.argv[1:], ("cwd",))
            self.assertEqual(template.cwd, "backend")
            staged_root = workspace.joinpath(
                *Path(receipt.staged_root_relative_path).parts
            )
            observed = sorted(
                path.relative_to(staged_root).as_posix()
                for path in staged_root.rglob("*")
                if path.is_file()
            )
            self.assertEqual(observed, ["bin/probe.exe", "lib/support.dat"])

    def test_tampered_signature_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, _, _, _, signed, verifier = make_authority(
                Path(directory)
            )
            payload = signed.to_dict()
            payload["signature_sha256"] = "0" * 64
            forged = SignedRuntimeClosureManifest.from_mapping(payload)
            with self.assertRaisesRegex(RuntimeClosureError, "signature"):
                verifier.verify(
                    forged,
                    registry,
                    task,
                    COMMAND_ID,
                    trusted_runtime_root=trusted,
                )

    def test_source_change_after_signature_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, _, _, source, signed, verifier = make_authority(
                Path(directory)
            )
            source.write_bytes(b"changed after manifest signature")
            with self.assertRaisesRegex(RuntimeClosureError, "changed"):
                verifier.verify(
                    signed,
                    registry,
                    task,
                    COMMAND_ID,
                    trusted_runtime_root=trusted,
                )

    def test_unmanifested_staged_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _, _, signed, verifier = (
                make_authority(Path(directory))
            )
            stager = TrustedRuntimeClosureStager(trusted, workspace)
            receipt = stager.stage(signed, verifier, registry, task, COMMAND_ID)
            root = workspace.joinpath(*Path(receipt.staged_root_relative_path).parts)
            (root / "extra.dll").write_bytes(b"not in signed closure")
            with self.assertRaisesRegex(RuntimeClosureError, "unmanifested"):
                stager.verify(receipt, signed, verifier, registry, task, COMMAND_ID)

    def test_runtime_paths_reject_traversal_and_windows_device_names(self):
        common = {
            "sha256": hashlib.sha256(b"x").hexdigest(),
            "size_bytes": 1,
        }
        with self.assertRaises(RuntimeClosureError):
            RuntimeClosureFile(relative_path="../escape.dll", **common)
        with self.assertRaises(RuntimeClosureError):
            RuntimeClosureFile(relative_path="bin/CON.txt", **common)

    def test_manifest_rejects_case_collisions_and_parent_file_conflicts(self):
        common = {
            "task_id": "A10D_CLOSURE",
            "task_sha256": "1" * 64,
            "repository": "Ternedal/ModelRig",
            "base_sha": BASE_SHA,
            "command_id": COMMAND_ID,
            "tool_id": TOOL_ID,
            "catalog_sha256": "2" * 64,
            "toolchain_sha256": "3" * 64,
            "lease_sha256": "4" * 64,
            "workspace_root_sha256": "5" * 64,
            "trusted_runtime_root_sha256": "6" * 64,
            "entrypoint_relative_path": "bin/probe.exe",
            "working_directory": "backend",
        }
        one = RuntimeClosureFile("bin/probe.exe", "7" * 64, 1)
        collision = RuntimeClosureFile("BIN/PROBE.EXE", "8" * 64, 1)
        with self.assertRaisesRegex(RuntimeClosureError, "case-insensitive"):
            RuntimeClosureManifest(
                **common,
                files=tuple(
                    sorted((one, collision), key=lambda item: item.relative_path)
                ),
                total_bytes=2,
            )
        parent = RuntimeClosureFile("lib", "8" * 64, 1)
        child = RuntimeClosureFile("lib/support.dat", "9" * 64, 1)
        with self.assertRaisesRegex(RuntimeClosureError, "parent file"):
            RuntimeClosureManifest(
                **common,
                files=tuple(
                    sorted((one, parent, child), key=lambda item: item.relative_path)
                ),
                total_bytes=3,
            )

    def test_hardlinked_staged_file_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _, _, signed, verifier = (
                make_authority(Path(directory))
            )
            stager = TrustedRuntimeClosureStager(trusted, workspace)
            receipt = stager.stage(signed, verifier, registry, task, COMMAND_ID)
            root = workspace.joinpath(*Path(receipt.staged_root_relative_path).parts)
            entrypoint = root / "bin" / "probe.exe"
            sibling = root / "bin" / "probe-hardlink.exe"
            try:
                os.link(entrypoint, sibling)
            except OSError:
                self.skipTest("hardlinks are unavailable")
            sibling.unlink()
            outside = workspace / "hardlink-alias.exe"
            os.link(entrypoint, outside)
            with self.assertRaisesRegex(RuntimeClosureError, "hardlink"):
                stager.verify(receipt, signed, verifier, registry, task, COMMAND_ID)

    def test_manifest_wrong_working_directory_cannot_rebind(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, _, _, _, signed, verifier = make_authority(
                Path(directory)
            )
            payload = signed.manifest.to_dict()
            payload["working_directory"] = "."
            wrong = HmacRuntimeClosureSigner(KEY_ID, SECRET).sign(
                RuntimeClosureManifest.from_mapping(payload)
            )
            with self.assertRaisesRegex(RuntimeClosureError, "exact command authority"):
                verifier.verify(
                    wrong,
                    registry,
                    task,
                    COMMAND_ID,
                    trusted_runtime_root=trusted,
                )

    def test_plan_binds_verified_closure_and_nested_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, control, _, signed, verifier = (
                make_authority(Path(directory))
            )
            stager = TrustedRuntimeClosureStager(trusted, workspace)
            receipt = stager.stage(signed, verifier, registry, task, COMMAND_ID)
            rebound = stager.bind_for_launch(
                receipt, signed, verifier, registry, task, COMMAND_ID
            )
            plan = build_tier_a_launch_plan(
                rebound,
                task,
                COMMAND_ID,
                workspace_root=workspace,
                control_plane_root=control,
                runtime_closure_receipt=receipt,
            )

            self.assertTrue(plan.runtime_closure_verified)
            self.assertEqual(plan.cwd, "backend")
            self.assertEqual(plan.runtime_closure_sha256, signed.manifest.sha256)
            self.assertEqual(plan.signed_runtime_closure_sha256, signed.sha256)
            self.assertEqual(
                plan.runtime_closure_staging_receipt_sha256, receipt.sha256
            )
            self.assertEqual(
                plan.working_directory_sha256,
                working_directory_authority_sha256(workspace, "backend"),
            )

    def test_review_only_plan_without_closure_stays_non_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, _, workspace, control, _, _, _ = make_authority(
                Path(directory)
            )
            staged_source = workspace / "probe.exe"
            staged_source.write_bytes(b"signed closure executable\n")
            original = registry.resolve(task, COMMAND_ID)
            rebound = LeasedCommandRegistry(
                CommandRegistry(
                    (
                        CommandTemplate(
                            COMMAND_ID,
                            (str(staged_source.resolve()), *original.argv[1:]),
                            original.cwd,
                            original.max_timeout_seconds,
                            original.env,
                        ),
                    )
                ),
                registry.lease,
                task=task,
                catalog=registry.catalog,
                toolchain=registry.toolchain,
                attestation=registry.attestation,
            )
            plan = build_tier_a_launch_plan(
                rebound,
                task,
                COMMAND_ID,
                workspace_root=workspace,
                control_plane_root=control,
            )
            self.assertFalse(plan.runtime_closure_verified)
            self.assertFalse(
                hasattr(tier_a_authority, "run_verified_tier_a_command")
            )
            self.assertFalse(hasattr(tier_a_authority, "_run_tier_a_launch_plan"))

    def test_working_directory_link_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            linked = workspace / "backend"
            try:
                linked.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            with self.assertRaisesRegex(TierAExecutionError, "unsafe"):
                working_directory_authority_sha256(workspace, "backend")

    def test_dc_l07_exposes_closure_authorities_without_process_launch(self):
        self.assertTrue(callable(RuntimeClosureVerifier))
        self.assertTrue(callable(TrustedRuntimeClosureStager))
        self.assertFalse(hasattr(tier_a_authority, "run_verified_tier_a_command"))
        self.assertFalse(hasattr(tier_a_authority, "_run_tier_a_launch_plan"))

    def test_receipt_mapping_rejects_extra_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _, _, signed, verifier = (
                make_authority(Path(directory))
            )
            receipt = TrustedRuntimeClosureStager(trusted, workspace).stage(
                signed, verifier, registry, task, COMMAND_ID
            )
            with self.assertRaises(RuntimeClosureError):
                RuntimeClosureStagingReceipt.from_mapping(
                    {**receipt.to_dict(), "unexpected": True}
                )

    def test_runtime_closure_schemas_match_canonical_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _, _, signed, verifier = (
                make_authority(Path(directory))
            )
            receipt = TrustedRuntimeClosureStager(trusted, workspace).stage(
                signed, verifier, registry, task, COMMAND_ID
            )
            repo = Path(__file__).resolve().parents[2]
            cases = (
                (
                    signed.manifest.to_dict(),
                    "development-runtime-closure-manifest-v1.schema.json",
                ),
                (
                    signed.to_dict(),
                    "development-signed-runtime-closure-manifest-v1.schema.json",
                ),
                (
                    receipt.to_dict(),
                    "development-runtime-closure-staging-receipt-v1.schema.json",
                ),
            )
            for payload, filename in cases:
                with self.subTest(filename=filename):
                    schema = json.loads(
                        (repo / "devcontrol" / "schemas" / filename).read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(set(schema["required"]), set(payload))
                    self.assertEqual(set(schema["properties"]), set(payload))
                    self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
