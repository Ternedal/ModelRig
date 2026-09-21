"""Adversarial contract for ADR-DC-036 non-executing executor capability."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))
DEVCONTROL_TESTS = ROOT / "devcontrol" / "tests"
if str(DEVCONTROL_TESTS) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_TESTS))

import kaliv_dev_control.improvement_pilot_exact_task_development_task_binding as binding  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_plan_requirements as plan_req  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_executor_capability as capability  # noqa: E402
from kaliv_dev_control._tier_a_materialization import LeasedCatalogMaterializer  # noqa: E402
from kaliv_dev_control.catalog import (  # noqa: E402
    IsolationAttestation,
    IsolationBoundary,
    ModelRigCommandCatalog,
    NetworkMode,
    ProjectCommandSpec,
    ToolBinding,
    Toolchain,
)
from kaliv_dev_control.contract import DevelopmentTask  # noqa: E402
from kaliv_dev_control.physical_isolation import WindowsPhysicalIsolationVerifier  # noqa: E402
from kaliv_dev_control.runtime_closure import (  # noqa: E402
    HmacRuntimeClosureSigner,
    RuntimeClosureVerifier,
)
from kaliv_dev_control.runtime_closure_builder import (  # noqa: E402
    ModelRigVersionCheckClosureBuilder,
    VERSION_CHECK_COMMAND_ID,
    VERSION_CHECK_TOOL_ID,
    modelrig_version_check_closure_catalog,
)
from kaliv_dev_control.tier_a_authority import (  # noqa: E402
    tier_a_toolhost_sha256,
    workspace_root_authority_sha256,
)
from rsi_pilot_exact_task_execution_plan_requirements_contract import _live_receipt  # noqa: E402
from test_slice6_hardening import NOW, fixture_key, signed_report  # noqa: E402
from test_slice9 import create_control_plane  # noqa: E402
from test_trusted_git_runtime import stage as stage_trusted_git  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-executor-capability-v1.schema.json"
)
RUNTIME_KEY_ID = "rsi-executor-capability-runtime"
RUNTIME_SECRET = hashlib.sha256(b"rsi-executor-capability-runtime-secret").digest()


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-036 unexpectedly accepted invalid input")


def _task(requirements) -> DevelopmentTask:
    return DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "DC_L16_VERSION_CHECK",
            "repository": requirements.repository,
            "base_sha": requirements.base_sha,
            "goal": "Run the exact read-only ModelRig version check.",
            "acceptance_criteria": [
                "The reviewed standalone version check exits successfully."
            ],
            "risk": "low",
            "allowed_paths": ["VERSION"],
            "protected_paths": ["devcontrol/**"],
            "allowed_command_ids": [VERSION_CHECK_COMMAND_ID],
            "required_tests": [VERSION_CHECK_COMMAND_ID],
            "budget": {
                "max_changed_files": 1,
                "max_added_lines": 1,
                "max_deleted_lines": 0,
                "max_attempts": 1,
                "max_runtime_seconds": 120,
                "max_output_bytes": 65536,
            },
            "merge_authority": "human",
        }
    )


def _task_sha256(task: DevelopmentTask) -> str:
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def _registry(requirements, task: DevelopmentTask) -> bytes:
    return json.dumps(
        {
            "schema": binding.PILOT_EXACT_TASK_DEVELOPMENT_TASK_REGISTRY_SCHEMA,
            "entries": [
                {
                    "selected_pilot_task_id": requirements.selected_pilot_task_id,
                    "development_task": task.to_dict(),
                    "development_task_sha256": _task_sha256(task),
                }
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _authority_fixture(root: Path, task: DevelopmentTask):
    trusted = (root / "trusted-runtime").resolve()
    workspace = (root / "workspace").resolve()
    control = (root / "control-plane").resolve()
    evidence = (root / "physical-evidence").resolve()
    git_root = (root / "trusted-git-fixture").resolve()
    (trusted / "bin").mkdir(parents=True)
    workspace.mkdir()
    control.mkdir()
    evidence.mkdir()
    git_root.mkdir()
    create_control_plane(control)

    executable = trusted / "bin" / "modelrig-version-check.exe"
    executable.write_bytes(b"standalone ModelRig version check fixture\n")
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()

    catalog = modelrig_version_check_closure_catalog()
    toolchain = Toolchain(
        (
            ToolBinding(
                VERSION_CHECK_TOOL_ID,
                str(executable),
                executable_sha256,
            ),
        )
    )
    toolhost_sha = tier_a_toolhost_sha256(control)
    workspace_authority = workspace_root_authority_sha256(workspace)
    physical = signed_report(
        source_task=task,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        toolhost_sha256=toolhost_sha,
        workspace_root_sha256=workspace_authority,
    )
    (evidence / "physical-report.json").write_text(
        physical.canonical_json(),
        encoding="utf-8",
    )
    attestation = IsolationAttestation(
        task_id=task.task_id,
        task_sha256=_task_sha256(task),
        repository=task.repository,
        base_sha=task.base_sha,
        catalog_sha256=catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        evidence_sha256=(physical.sha256,),
    )
    physical_verifier = WindowsPhysicalIsolationVerifier(
        evidence,
        {"operator-key-2026": fixture_key()},
        now=lambda: NOW,
    )
    leased = LeasedCatalogMaterializer(
        catalog,
        physical_verifier,
    ).materialize(task, toolchain, attestation)
    manifest = ModelRigVersionCheckClosureBuilder(trusted, workspace).build(
        leased,
        task,
    )
    signed_closure = HmacRuntimeClosureSigner(
        RUNTIME_KEY_ID,
        RUNTIME_SECRET,
    ).sign(manifest)
    runtime_verifier = RuntimeClosureVerifier(
        {RUNTIME_KEY_ID: RUNTIME_SECRET}
    )
    _, _, _, _, git_runner = stage_trusted_git(git_root)
    return {
        "trusted": trusted,
        "workspace": workspace,
        "control": control,
        "catalog": catalog,
        "toolchain": toolchain,
        "attestation": attestation,
        "physical_verifier": physical_verifier,
        "signed_closure": signed_closure,
        "runtime_verifier": runtime_verifier,
        "git_runner": git_runner,
        "toolhost_sha": toolhost_sha,
        "workspace_authority": workspace_authority,
    }


def run_contract() -> None:
    if os.name == "nt":
        # The staged Git fixture is a synthetic POSIX executable.  Real Windows
        # isolation/tool-host coverage remains in the existing Windows CI jobs.
        return

    source_temp, ledger_temp, receipt = _live_receipt()
    capability_temp = tempfile.TemporaryDirectory(prefix="rsi-executor-capability-")
    try:
        requirements = plan_req.build_pilot_exact_task_execution_plan_requirements(
            receipt
        )
        task = _task(requirements)
        task_binding = binding._bind_verified_development_task(
            plan_requirements=requirements,
            admission_receipt=receipt,
            registry_payload=_registry(requirements, task),
        )
        fixture = _authority_fixture(Path(capability_temp.name).resolve(), task)
        impl = capability._implementation
        original_path_sha = impl._path_sha256

        def scoped_path_sha(path: Path) -> str:
            candidate = Path(path)
            if candidate == fixture["workspace"]:
                # The upstream human scope contains only a digest, not the clear
                # path.  This deterministic contract substitutes that one digest
                # while leaving every other path hash on the production helper.
                return task_binding.workspace_root_path_sha256
            return original_path_sha(candidate)

        def forbidden_git_run(*_args, **_kwargs):
            raise AssertionError(
                "ADR-DC-036 materialization must not start a Git process"
            )

        with patch.object(impl, "_path_sha256", side_effect=scoped_path_sha), patch.object(
            fixture["git_runner"], "run", side_effect=forbidden_git_run
        ):
            proof = capability._materialize_verified_executor_capability(
                task_binding=task_binding,
                admission_receipt=receipt,
                catalog=fixture["catalog"],
                toolchain=fixture["toolchain"],
                isolation_attestation=fixture["attestation"],
                physical_verifier=fixture["physical_verifier"],
                signed_runtime_closure=fixture["signed_closure"],
                runtime_closure_verifier=fixture["runtime_verifier"],
                trusted_runtime_root=fixture["trusted"],
                git_runner=fixture["git_runner"],
                workspace_root=fixture["workspace"],
                control_plane_root=fixture["control"],
            )

        assert proof.schema == capability.PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_SCHEMA
        assert proof.authority == capability.PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY
        assert proof.task_binding is task_binding
        assert proof.task_binding_sha256 == task_binding.sha256
        assert proof.admission_receipt_sha256 == receipt.sha256
        assert proof.execution_nonce_sha256 == receipt.execution_nonce_sha256
        assert proof.development_task_id == task.task_id
        assert proof.development_task_sha256 == _task_sha256(task)
        assert proof.fixed_command_id == VERSION_CHECK_COMMAND_ID
        assert proof.catalog_sha256 == fixture["catalog"].sha256
        assert proof.toolchain_sha256 == fixture["toolchain"].sha256
        assert proof.signed_runtime_closure_sha256 == fixture["signed_closure"].sha256
        assert proof.runtime_closure_manifest_sha256 == fixture["signed_closure"].manifest.sha256
        assert proof.workspace_root_authority_sha256 == fixture["workspace_authority"]
        assert proof.toolhost_sha256 == fixture["toolhost_sha"]
        assert proof.source_environment_sha256 == capability._source_environment_sha256()
        assert proof.process_memory_bytes == 512 * 1024 * 1024
        assert proof.active_process_limit == 8
        assert proof.executor_capability_materialized is True
        assert proof.physical_isolation_verified is True
        assert proof.runtime_closure_verified is True
        assert proof.trusted_git_runtime_verified is True
        assert proof.workspace_identity_verified is True
        assert proof.control_plane_toolhost_verified is True
        assert proof.execution_plan_materialized is True
        assert proof.execution_consumed is False
        assert proof.task_execution_started is False
        assert proof.task_execution_completed is False
        assert proof.integration_ready is False
        assert proof.product_pilot_started is False
        assert proof.local_commit_authorized is False
        assert proof.remote_write_authorized is False
        assert proof.push_authorized is False
        assert proof.pr_mutation_authorized is False
        assert proof.merge_authorized is False
        assert proof.release_authorized is False
        assert proof.deploy_authorized is False
        assert proof.production_activation_authorized is False
        assert proof.materialization_authenticated is True

        live_inputs = capability._get_live_capability_inputs(proof)
        assert live_inputs is not None
        assert live_inputs["admission_receipt"] is receipt
        assert live_inputs["git_runner"] is fixture["git_runner"]
        assert live_inputs["source_env"] == {
            "CI": "1",
            "MODELRIG_DEVCONTROL": "1",
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "LC_CTYPE": "C",
            "TZ": "UTC",
        }

        # Durable evidence survives round-trip, live capability authority does not.
        reloaded = capability.PilotExactTaskExecutorCapability.from_mapping(
            proof.to_dict()
        )
        assert reloaded == proof
        assert reloaded.sha256 == proof.sha256
        assert reloaded.materialization_authenticated is False
        assert capability._get_live_capability_inputs(reloaded) is None

        # Production remains deliberately fail-closed until host-pinned resolvers
        # for every ADR-DC-034 trust root are installed.
        _reject(lambda: capability.materialize_pilot_exact_task_executor_capability())

        # A caller-selected second command is never a valid executor capability.
        extra = ProjectCommandSpec(
            "modelrig.extra.check",
            VERSION_CHECK_TOOL_ID,
            (),
            ".",
            120,
            {"CI": "1", "MODELRIG_DEVCONTROL": "1"},
        )
        expanded_catalog = ModelRigCommandCatalog(
            (
                fixture["catalog"].resolve(VERSION_CHECK_COMMAND_ID),
                extra,
            )
        )
        with patch.object(impl, "_path_sha256", side_effect=scoped_path_sha):
            _reject(
                lambda: capability._materialize_verified_executor_capability(
                    task_binding=task_binding,
                    admission_receipt=receipt,
                    catalog=expanded_catalog,
                    toolchain=fixture["toolchain"],
                    isolation_attestation=fixture["attestation"],
                    physical_verifier=fixture["physical_verifier"],
                    signed_runtime_closure=fixture["signed_closure"],
                    runtime_closure_verifier=fixture["runtime_verifier"],
                    trusted_runtime_root=fixture["trusted"],
                    git_runner=fixture["git_runner"],
                    workspace_root=fixture["workspace"],
                    control_plane_root=fixture["control"],
                )
            )

        # Without the exact signed workspace path digest, materialization fails.
        _reject(
            lambda: capability._materialize_verified_executor_capability(
                task_binding=task_binding,
                admission_receipt=receipt,
                catalog=fixture["catalog"],
                toolchain=fixture["toolchain"],
                isolation_attestation=fixture["attestation"],
                physical_verifier=fixture["physical_verifier"],
                signed_runtime_closure=fixture["signed_closure"],
                runtime_closure_verifier=fixture["runtime_verifier"],
                trusted_runtime_root=fixture["trusted"],
                git_runner=fixture["git_runner"],
                workspace_root=fixture["workspace"],
                control_plane_root=fixture["control"],
            )
        )

        # Every durable authority escalation is rejected.
        for field in (
            "execution_consumed",
            "task_execution_started",
            "task_execution_completed",
            "integration_ready",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            _reject(
                lambda field=field: capability.PilotExactTaskExecutorCapability.from_mapping(
                    {**proof.to_dict(), field: True}
                )
            )
        for field in (
            "executor_capability_materialized",
            "physical_isolation_verified",
            "runtime_closure_verified",
            "trusted_git_runtime_verified",
            "workspace_identity_verified",
            "control_plane_toolhost_verified",
            "execution_plan_materialized",
        ):
            _reject(
                lambda field=field: capability.PilotExactTaskExecutorCapability.from_mapping(
                    {**proof.to_dict(), field: False}
                )
            )
        _reject(
            lambda: capability.PilotExactTaskExecutorCapability.from_mapping(
                {**proof.to_dict(), "process_memory_bytes": 1}
            )
        )
        _reject(
            lambda: capability.PilotExactTaskExecutorCapability.from_mapping(
                {**proof.to_dict(), "active_process_limit": 9}
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(proof.to_dict())
        assert set(schema["required"]) == set(proof.to_dict())
        assert schema["additionalProperties"] is False
        assert props["schema"]["const"] == capability.PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_SCHEMA
        assert props["authority"]["const"] == capability.PILOT_EXACT_TASK_EXECUTOR_CAPABILITY_AUTHORITY
        assert props["process_memory_bytes"]["const"] == 512 * 1024 * 1024
        assert props["active_process_limit"]["const"] == 8

        impl_source = inspect.getsource(capability._implementation)
        assert "git_runner.run(" not in impl_source
        assert "git_runner.evidence(" not in impl_source
        assert "run_verified_tier_a_command(" not in impl_source
        assert "run_single_verified_tier_a_command_with_receipt(" not in impl_source
        for forbidden in (
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
            "create_pull_request",
        ):
            assert forbidden not in impl_source.lower(), forbidden
    finally:
        capability_temp.cleanup()
        ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
