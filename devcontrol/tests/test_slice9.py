from __future__ import annotations

import hashlib
import importlib
import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import kaliv_dev_control.tier_a_authority as tier_a_module
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
from kaliv_dev_control.tier_a_authority import (
    LeasedCatalogMaterializer,
    TIER_A_APPLICATION_ENVIRONMENT,
    TierAExecutionError,
    TierALaunchPlan,
    _TIER_A_BUNDLE_FILES,
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
BUNDLE_FILES = _TIER_A_BUNDLE_FILES


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
        candidate_version="dc-l06-test",
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
    def _plan(self, root: Path):
        values = issue(root)
        (
            development_task,
            catalog,
            toolchain,
            attestation,
            verifier,
            workspace,
            control,
        ) = values
        registry = LeasedCatalogMaterializer(catalog, verifier).materialize(
            development_task, toolchain, attestation
        )
        plan = build_tier_a_launch_plan(
            registry,
            development_task,
            "modelrig.tier-a.probe",
            workspace_root=workspace.resolve(),
            control_plane_root=control.resolve(),
        )
        return values, registry, plan

    def test_signed_report_becomes_immutable_launch_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            values, _, plan = self._plan(Path(directory))
            development_task, _, _, attestation, _, _, _ = values
            self.assertEqual(plan.task_sha256, attestation.task_sha256)
            self.assertEqual(
                plan.signed_report_sha256, attestation.evidence_sha256[0]
            )
            self.assertEqual(dict(plan.env), dict(TIER_A_APPLICATION_ENVIRONMENT))
            self.assertEqual(
                TierALaunchPlan.from_mapping(plan.to_dict()).canonical_json(),
                plan.canonical_json(),
            )
            self.assertEqual(plan.task_id, development_task.task_id)

    def test_dc_l06_exposes_no_supported_process_launch_entrypoint(self) -> None:
        core = importlib.import_module("kaliv_dev_control._tier_a_execution_core")
        self.assertIsNone(importlib.util.find_spec("kaliv_dev_control.tier_a_execution"))
        for surface in (tier_a_module, core):
            self.assertFalse(hasattr(surface, "_run_tier_a_launch_plan"))
            self.assertFalse(hasattr(surface, "run_verified_tier_a_command"))

    def test_stage_local_bundle_projections_are_identical(self) -> None:
        toolhost = importlib.import_module("kaliv_dev_control._tier_a_legacy_toolhost")
        self.assertEqual(tier_a_module._TIER_A_BUNDLE_FILES, toolhost._TIER_A_BUNDLE_FILES)
        forbidden = (
            "runtime_staging",
            "runtime_closure",
            "tier_a_execution.py",
            "tier_a_execution_v3.py",
            "tier_a_result.py",
            "trusted_git",
            "semantic_review",
            "publisher",
        )
        for path in tier_a_module._TIER_A_BUNDLE_FILES:
            self.assertFalse(any(fragment in path for fragment in forbidden), path)

    def test_registry_cannot_be_rebound_to_another_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            values = issue(Path(directory))
            development_task, catalog, toolchain, attestation, verifier, _, _ = values
            registry = LeasedCatalogMaterializer(catalog, verifier).materialize(
                development_task, toolchain, attestation
            )
            other = DevelopmentTask.from_mapping(
                {**development_task.to_dict(), "task_id": "OTHER_A9"}
            )
            with self.assertRaisesRegex(TierAExecutionError, "another task"):
                registry.resolve(other, "modelrig.tier-a.probe")

    def test_any_authority_source_change_after_report_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            values, registry, _ = self._plan(Path(directory))
            development_task, _, _, _, _, workspace, control = values
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

    def test_missing_stage_local_authority_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory) / "control"
            control.mkdir()
            create_control_plane(control)
            (
                control
                / "devcontrol/src/kaliv_dev_control/_tier_a_environment.py"
            ).unlink()
            with self.assertRaisesRegex(TierAExecutionError, "missing or unsafe"):
                tier_a_toolhost_sha256(control)

    def test_executable_change_after_materialization_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            values, registry, _ = self._plan(Path(directory))
            development_task, _, _, _, _, workspace, control = values
            (workspace / "probe.exe").write_bytes(b"tampered")
            with self.assertRaisesRegex(TierAExecutionError, "changed after"):
                build_tier_a_launch_plan(
                    registry,
                    development_task,
                    "modelrig.tier-a.probe",
                    workspace_root=workspace.resolve(),
                    control_plane_root=control.resolve(),
                )

    def test_unreviewed_application_environment_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            CatalogError, "outside the reviewed isolation positive list"
        ):
            make_catalog(env={"API_TOKEN": "secret"})

    def test_failed_physical_probe_cannot_issue_a_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            values = issue(Path(directory), failed_probe=True)
            development_task, catalog, toolchain, attestation, verifier, _, _ = values
            with self.assertRaisesRegex(CatalogError, "failed probes"):
                LeasedCatalogMaterializer(catalog, verifier).materialize(
                    development_task, toolchain, attestation
                )

    def test_plan_reload_rejects_extra_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, plan = self._plan(Path(directory))
            with self.assertRaises(TierAExecutionError):
                TierALaunchPlan.from_mapping({**plan.to_dict(), "extra": True})


if __name__ == "__main__":
    unittest.main()
