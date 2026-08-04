from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import kaliv_dev_control.tier_a_execution as tier_a_module
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
from kaliv_dev_control.contract import DevelopmentTask
from kaliv_dev_control.physical_isolation import (
    HmacIsolationReportSigner,
    PhysicalProbeResult,
    ProbeName,
    WindowsIsolationPhysicalReport,
    WindowsPhysicalIsolationVerifier,
    write_signed_report,
)
from kaliv_dev_control.tier_a_execution import (
    LeasedCatalogMaterializer,
    TIER_A_APPLICATION_ENVIRONMENT,
    TierAExecutionError,
    TierALaunchPlan,
    build_tier_a_launch_plan,
    tier_a_toolhost_sha256,
    workspace_root_authority_sha256,
)

BASE_SHA = "a" * 40
STARTED = "2026-08-03T12:00:00Z"
COMPLETED = "2026-08-03T12:10:00Z"
NOW = datetime(2026, 8, 3, 12, 15, tzinfo=timezone.utc)
SECRET = b"x" * 32
KEY_ID = "operator-key-test"

# This fixture deliberately mirrors the complete signed v6 authority bundle.
# A missing entry must make the test authority root fail closed just like a real
# operator root, rather than silently weakening physical-evidence identity.
BUNDLE_FILES = (
    "worker/app/__init__.py",
    "worker/app/windows_job.py",
    "worker/app/windows_restricted.py",
    "worker/app/windows_capture.py",
    "worker/app/windows_runtime_guard.py",
    "worker/app/windows_tier_a.py",
    "devcontrol/src/kaliv_dev_control/__init__.py",
    "devcontrol/src/kaliv_dev_control/catalog.py",
    "devcontrol/src/kaliv_dev_control/commands.py",
    "devcontrol/src/kaliv_dev_control/contract.py",
    "devcontrol/src/kaliv_dev_control/physical_isolation.py",
    "devcontrol/src/kaliv_dev_control/runtime_staging.py",
    "devcontrol/src/kaliv_dev_control/_runtime_closure_common.py",
    "devcontrol/src/kaliv_dev_control/runtime_closure_model.py",
    "devcontrol/src/kaliv_dev_control/runtime_closure_verify.py",
    "devcontrol/src/kaliv_dev_control/runtime_closure_staging.py",
    "devcontrol/src/kaliv_dev_control/runtime_closure.py",
    "devcontrol/src/kaliv_dev_control/tier_a_authority.py",
    "devcontrol/src/kaliv_dev_control/tier_a_plan.py",
    "devcontrol/src/kaliv_dev_control/tier_a_execution_v3.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py",
    "devcontrol/src/kaliv_dev_control/tier_a_result.py",
    "devcontrol/src/kaliv_dev_control/tier_a_command_receipt.py",
    "devcontrol/src/kaliv_dev_control/tier_a_execution.py",
    "devcontrol/src/kaliv_dev_control/workspace.py",
)


def task(command_id: str = "modelrig.tier-a.probe") -> DevelopmentTask:
    return DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "A9_LEASE",
            "repository": "Ternedal/ModelRig",
            "base_sha": BASE_SHA,
            "goal": "Bind a fixed command to signed Tier-A authority.",
            "acceptance_criteria": ["The launch plan is exact and fail closed."],
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


def make_catalog(*, env=None) -> ModelRigCommandCatalog:
    return ModelRigCommandCatalog(
        (
            ProjectCommandSpec(
                "modelrig.tier-a.probe",
                "probe",
                ("--version",),
                ".",
                30,
                TIER_A_APPLICATION_ENVIRONMENT if env is None else env,
            ),
        )
    )


def create_control_plane(root: Path) -> None:
    for relative in BUNDLE_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {relative}\n", encoding="utf-8")


def make_probes(*, passed: bool = True) -> tuple[PhysicalProbeResult, ...]:
    return tuple(
        PhysicalProbeResult(
            name=name,
            passed=passed,
            receipt_sha256=hashlib.sha256(name.value.encode()).hexdigest(),
            detail=f"{name.value} observed",
            observed_at=COMPLETED,
        )
        for name in ProbeName
    )


def issue(root: Path, *, failed_probe: bool = False, env=None):
    workspace = root / "workspace"
    evidence = root / "evidence"
    control = root / "control"
    workspace.mkdir()
    evidence.mkdir()
    control.mkdir()
    create_control_plane(control)

    executable = workspace / "probe.exe"
    executable.write_bytes(b"portable staged executable")
    executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()

    catalog = make_catalog(env=env)
    toolchain = Toolchain(
        (ToolBinding("probe", str(executable.resolve()), executable_hash),)
    )
    development_task = task()

    probes = list(make_probes())
    if failed_probe:
        original = probes[0]
        probes[0] = PhysicalProbeResult(
            name=original.name,
            passed=False,
            receipt_sha256=original.receipt_sha256,
            detail=original.detail,
            observed_at=original.observed_at,
        )
    report = WindowsIsolationPhysicalReport(
        report_id="report-a9-lease",
        task_id=development_task.task_id,
        task_sha256=hashlib.sha256(
            development_task.canonical_json().encode()
        ).hexdigest(),
        repository=development_task.repository,
        base_sha=development_task.base_sha,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        rig_id="modelrig-test-rig",
        rig_fingerprint_sha256="1" * 64,
        candidate_version="slice-9-test",
        windows_build="Windows test contract",
        toolhost_sha256=tier_a_toolhost_sha256(control),
        workspace_root_sha256=workspace_root_authority_sha256(workspace),
        collected_by="collector-test",
        approved_by="approver-test",
        started_at=STARTED,
        completed_at=COMPLETED,
        boot_marker_before_sha256="2" * 64,
        boot_marker_after_sha256="3" * 64,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        probes=tuple(probes),
    )
    signed = HmacIsolationReportSigner(KEY_ID, SECRET).sign(report)
    signed_hash = write_signed_report(
        (evidence / "report.json").resolve(), signed
    )
    attestation = IsolationAttestation(
        task_id=development_task.task_id,
        task_sha256=report.task_sha256,
        repository=development_task.repository,
        base_sha=development_task.base_sha,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        evidence_sha256=(signed_hash,),
    )
    verifier = WindowsPhysicalIsolationVerifier(
        evidence.resolve(),
        {KEY_ID: SECRET},
        now=lambda: NOW,
        max_age=timedelta(days=30),
    )
    return (
        development_task,
        catalog,
        toolchain,
        attestation,
        verifier,
        workspace,
        control,
    )


class TierAExecutionLeaseTests(unittest.TestCase):
    def test_signed_report_becomes_immutable_launch_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            values = issue(Path(directory))
            (
                development_task,
                catalog,
                toolchain,
                attestation,
                verifier,
                workspace,
                control,
            ) = values
            registry = LeasedCatalogMaterializer(
                catalog, verifier
            ).materialize(development_task, toolchain, attestation)
            plan = build_tier_a_launch_plan(
                registry,
                development_task,
                "modelrig.tier-a.probe",
                workspace_root=workspace.resolve(),
                control_plane_root=control.resolve(),
            )
            self.assertEqual(plan.task_sha256, attestation.task_sha256)
            self.assertEqual(
                plan.signed_report_sha256, attestation.evidence_sha256[0]
            )
            self.assertEqual(
                plan.workspace_root_sha256,
                workspace_root_authority_sha256(workspace),
            )
            self.assertEqual(
                plan.max_output_bytes,
                development_task.budget.max_output_bytes,
            )
            self.assertEqual(dict(plan.env), dict(TIER_A_APPLICATION_ENVIRONMENT))
            self.assertEqual(
                TierALaunchPlan.from_mapping(plan.to_dict()).canonical_json(),
                plan.canonical_json(),
            )

    def test_public_runtime_requires_fresh_verification_not_a_plan(self):
        self.assertFalse(hasattr(tier_a_module, "run_tier_a_launch_plan"))
        self.assertTrue(hasattr(tier_a_module, "run_verified_tier_a_command"))

    def test_registry_cannot_be_rebound_to_another_task(self):
        with tempfile.TemporaryDirectory() as directory:
            development_task, catalog, toolchain, attestation, verifier, _, _ = issue(
                Path(directory)
            )
            registry = LeasedCatalogMaterializer(
                catalog, verifier
            ).materialize(development_task, toolchain, attestation)
            other = DevelopmentTask.from_mapping(
                {**development_task.to_dict(), "task_id": "OTHER_A9"}
            )
            with self.assertRaisesRegex(TierAExecutionError, "another task"):
                registry.resolve(other, "modelrig.tier-a.probe")

    def test_any_authority_source_change_after_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                development_task,
                catalog,
                toolchain,
                attestation,
                verifier,
                workspace,
                control,
            ) = issue(Path(directory))
            registry = LeasedCatalogMaterializer(
                catalog, verifier
            ).materialize(development_task, toolchain, attestation)
            (control / "worker/app/windows_capture.py").write_text(
                "# changed after evidence\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(TierAExecutionError, "authority code"):
                build_tier_a_launch_plan(
                    registry,
                    development_task,
                    "modelrig.tier-a.probe",
                    workspace_root=workspace.resolve(),
                    control_plane_root=control.resolve(),
                )

    def test_missing_capture_authority_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory) / "control"
            control.mkdir()
            create_control_plane(control)
            (control / "devcontrol/src/kaliv_dev_control/tier_a_result.py").unlink()

            with self.assertRaisesRegex(TierAExecutionError, "missing or unsafe"):
                tier_a_toolhost_sha256(control)

    def test_executable_change_after_materialization_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                development_task,
                catalog,
                toolchain,
                attestation,
                verifier,
                workspace,
                control,
            ) = issue(Path(directory))
            registry = LeasedCatalogMaterializer(
                catalog, verifier
            ).materialize(development_task, toolchain, attestation)
            (workspace / "probe.exe").write_bytes(b"tampered")
            with self.assertRaisesRegex(TierAExecutionError, "changed after"):
                build_tier_a_launch_plan(
                    registry,
                    development_task,
                    "modelrig.tier-a.probe",
                    workspace_root=workspace.resolve(),
                    control_plane_root=control.resolve(),
                )

    def test_unreviewed_application_environment_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            values = issue(Path(directory), env={"API_TOKEN": "secret"})
            (
                development_task,
                catalog,
                toolchain,
                attestation,
                verifier,
                workspace,
                control,
            ) = values
            registry = LeasedCatalogMaterializer(
                catalog, verifier
            ).materialize(development_task, toolchain, attestation)
            with self.assertRaisesRegex(TierAExecutionError, "not reviewed"):
                build_tier_a_launch_plan(
                    registry,
                    development_task,
                    "modelrig.tier-a.probe",
                    workspace_root=workspace.resolve(),
                    control_plane_root=control.resolve(),
                )

    def test_failed_physical_probe_cannot_issue_a_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            development_task, catalog, toolchain, attestation, verifier, _, _ = issue(
                Path(directory), failed_probe=True
            )
            with self.assertRaisesRegex(CatalogError, "failed probes"):
                LeasedCatalogMaterializer(catalog, verifier).materialize(
                    development_task, toolchain, attestation
                )

    def test_plan_reload_rejects_extra_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                development_task,
                catalog,
                toolchain,
                attestation,
                verifier,
                workspace,
                control,
            ) = issue(Path(directory))
            registry = LeasedCatalogMaterializer(
                catalog, verifier
            ).materialize(development_task, toolchain, attestation)
            plan = build_tier_a_launch_plan(
                registry,
                development_task,
                "modelrig.tier-a.probe",
                workspace_root=workspace.resolve(),
                control_plane_root=control.resolve(),
            )
            with self.assertRaises(TierAExecutionError):
                TierALaunchPlan.from_mapping({**plan.to_dict(), "extra": True})


if __name__ == "__main__":
    unittest.main()
