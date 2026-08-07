from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from kaliv_dev_control.catalog import (
    CatalogError,
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
    RuntimeClosureVerifier,
    TrustedRuntimeClosureStager,
)
from kaliv_dev_control.runtime_closure_builder import (
    ModelRigVersionCheckClosureBuilder,
    VERSION_CHECK_COMMAND_ID,
    VERSION_CHECK_TOOL_ID,
    modelrig_version_check_closure_catalog,
)
from kaliv_dev_control.tier_a_authority import (
    LeasedCommandRegistry,
    TierAExecutionLease,
    tier_a_toolhost_sha256,
    workspace_root_authority_sha256,
)
from test_slice9 import create_control_plane

BASE_SHA = "a" * 40
KEY_ID = "version-check-closure-key"
SECRET = b"version-check-closure-secret-0001"


def make_authority(root: Path, *, legacy_profile: bool = False):
    trusted = root / "trusted"
    workspace = root / "workspace"
    control = root / "control"
    (trusted / "bin").mkdir(parents=True)
    workspace.mkdir()
    control.mkdir()
    create_control_plane(control)

    executable = trusted / "bin" / "modelrig-version-check.exe"
    executable.write_bytes(b"standalone version check executable\n")
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()

    task = DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "A10E_VERSION",
            "repository": "Ternedal/ModelRig",
            "base_sha": BASE_SHA,
            "goal": "Build one reviewed self-contained runtime closure.",
            "acceptance_criteria": [
                "Only the exact standalone version checker is manifested."
            ],
            "risk": "low",
            "allowed_paths": ["devcontrol/**", "backend/cmd/**"],
            "protected_paths": ["devcontrol/secrets/**"],
            "allowed_command_ids": [VERSION_CHECK_COMMAND_ID],
            "required_tests": [VERSION_CHECK_COMMAND_ID],
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
    if legacy_profile:
        catalog = ModelRigCommandCatalog(
            (
                ProjectCommandSpec(
                    VERSION_CHECK_COMMAND_ID,
                    "python",
                    ("scripts/version_tool.py", "check"),
                    ".",
                    120,
                    {"CI": "1", "MODELRIG_DEVCONTROL": "1"},
                ),
            )
        )
        binding = ToolBinding(
            "python", str(executable.resolve()), executable_sha256
        )
    else:
        catalog = modelrig_version_check_closure_catalog()
        binding = ToolBinding(
            VERSION_CHECK_TOOL_ID,
            str(executable.resolve()),
            executable_sha256,
        )
    toolchain = Toolchain((binding,))
    task_sha256 = hashlib.sha256(
        task.canonical_json().encode("utf-8")
    ).hexdigest()
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
        report_id="slice-10e-version-check",
        rig_id="slice-10e-test-rig",
        rig_fingerprint_sha256="e" * 64,
        toolhost_sha256=tier_a_toolhost_sha256(control.resolve()),
        workspace_root_sha256=workspace_root_authority_sha256(
            workspace.resolve()
        ),
        completed_at="2026-08-04T00:30:00Z",
        key_id="operator-key-test",
    )
    spec = catalog.resolve(VERSION_CHECK_COMMAND_ID)
    registry = LeasedCommandRegistry(
        CommandRegistry(
            (
                CommandTemplate(
                    spec.command_id,
                    (str(executable.resolve()), *spec.args),
                    spec.cwd,
                    spec.max_timeout_seconds,
                    spec.env,
                ),
            )
        ),
        lease,
        task=task,
        catalog=catalog,
        toolchain=toolchain,
        attestation=attestation,
    )
    return (
        task,
        registry,
        trusted.resolve(),
        workspace.resolve(),
        executable.resolve(),
    )


class VersionCheckClosureBuilderTests(unittest.TestCase):
    def test_builds_signable_single_file_manifest_and_stages_it(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, executable = make_authority(
                Path(directory)
            )
            builder = ModelRigVersionCheckClosureBuilder(trusted, workspace)
            manifest = builder.build(registry, task)

            self.assertEqual(manifest.command_id, VERSION_CHECK_COMMAND_ID)
            self.assertEqual(manifest.tool_id, VERSION_CHECK_TOOL_ID)
            self.assertEqual(
                manifest.entrypoint_relative_path,
                "bin/modelrig-version-check.exe",
            )
            self.assertEqual(manifest.working_directory, ".")
            self.assertEqual(len(manifest.files), 1)
            self.assertEqual(
                manifest.files[0].sha256,
                hashlib.sha256(executable.read_bytes()).hexdigest(),
            )

            signed = HmacRuntimeClosureSigner(KEY_ID, SECRET).sign(manifest)
            verifier = RuntimeClosureVerifier({KEY_ID: SECRET})
            root, verified = verifier.verify(
                signed,
                registry,
                task,
                VERSION_CHECK_COMMAND_ID,
                trusted_runtime_root=trusted,
            )
            self.assertEqual(root, trusted)
            self.assertEqual(tuple(path for _, path in verified), (executable,))

            stager = TrustedRuntimeClosureStager(trusted, workspace)
            receipt = stager.stage(
                signed, verifier, registry, task, VERSION_CHECK_COMMAND_ID
            )
            repeated = stager.stage(
                signed, verifier, registry, task, VERSION_CHECK_COMMAND_ID
            )
            self.assertEqual(repeated, receipt)
            rebound = stager.bind_for_launch(
                receipt,
                signed,
                verifier,
                registry,
                task,
                VERSION_CHECK_COMMAND_ID,
            )
            staged = Path(rebound.resolve(task, VERSION_CHECK_COMMAND_ID).argv[0])
            self.assertNotEqual(staged, executable)
            self.assertEqual(staged.read_bytes(), executable.read_bytes())

    def test_rejects_every_other_command(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _ = make_authority(
                Path(directory)
            )
            builder = ModelRigVersionCheckClosureBuilder(trusted, workspace)
            with self.assertRaisesRegex(RuntimeClosureError, "every other command"):
                builder.build(registry, task, "modelrig.devcontrol.tests")

    def test_rejects_extra_runtime_file_or_directory(self):
        for extra_name, is_directory in (("extra.dll", False), ("plugins", True)):
            with self.subTest(extra_name=extra_name):
                with tempfile.TemporaryDirectory() as directory:
                    task, registry, trusted, workspace, _ = make_authority(
                        Path(directory)
                    )
                    extra = trusted / extra_name
                    if is_directory:
                        extra.mkdir()
                    else:
                        extra.write_bytes(b"unexpected")
                    builder = ModelRigVersionCheckClosureBuilder(
                        trusted, workspace
                    )
                    with self.assertRaisesRegex(RuntimeClosureError, "exactly"):
                        builder.build(registry, task)

    def test_rejects_legacy_python_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                CatalogError, "self-contained runtime attestation"
            ):
                make_authority(Path(directory), legacy_profile=True)

    def test_rejects_workspace_not_named_by_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task, registry, trusted, _, _ = make_authority(root)
            other_workspace = root / "other-workspace"
            other_workspace.mkdir()
            builder = ModelRigVersionCheckClosureBuilder(
                trusted, other_workspace
            )
            with self.assertRaisesRegex(RuntimeClosureError, "execution lease"):
                builder.build(registry, task)


if __name__ == "__main__":
    unittest.main()
