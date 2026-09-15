"""ADR-DC-036 capability-only contract after workspace-snapshot hardening."""
from __future__ import annotations

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

import kaliv_dev_control.improvement_pilot_exact_task_development_task_binding as binding  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_plan_requirements as plan_req  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_executor_capability as capability  # noqa: E402
from kaliv_dev_control.catalog import ModelRigCommandCatalog, ProjectCommandSpec  # noqa: E402
from kaliv_dev_control.runtime_closure_builder import (  # noqa: E402
    VERSION_CHECK_COMMAND_ID,
    VERSION_CHECK_TOOL_ID,
)
from rsi_pilot_exact_task_execution_plan_requirements_contract import _live_receipt  # noqa: E402
from rsi_pilot_exact_task_executor_capability_contract import (  # noqa: E402
    _authority_fixture,
    _registry,
    _task,
    _task_sha256,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-executor-capability-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-036 unexpectedly accepted authority escalation")


def run_contract() -> None:
    if os.name == "nt":
        # The synthetic trusted-Git helper fixture is POSIX-only. Native Windows
        # isolation remains covered by the existing Windows DevControl jobs.
        return

    source_temp, ledger_temp, receipt = _live_receipt()
    capability_temp = tempfile.TemporaryDirectory(prefix="rsi-capability-only-")
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
                return task_binding.workspace_root_path_sha256
            return original_path_sha(candidate)

        def forbidden_git_run(*_args, **_kwargs):
            raise AssertionError(
                "ADR-DC-036 capability materialization must not start Git"
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

        assert proof.executor_capability_materialized is True
        assert proof.execution_plan_materialized is False
        assert proof.execution_consumed is False
        assert proof.task_execution_started is False
        assert proof.task_execution_completed is False
        assert proof.development_task_sha256 == _task_sha256(task)
        assert proof.fixed_command_id == VERSION_CHECK_COMMAND_ID
        assert proof.catalog_sha256 == fixture["catalog"].sha256
        assert proof.toolchain_sha256 == fixture["toolchain"].sha256
        assert proof.materialization_authenticated is True

        # Durable evidence never upgrades to launch-plan authority on reload.
        reloaded = capability.PilotExactTaskExecutorCapability.from_mapping(
            proof.to_dict()
        )
        assert reloaded == proof
        assert reloaded.execution_plan_materialized is False
        assert reloaded.materialization_authenticated is False

        # Explicit launch-plan escalation is rejected until the later boundary
        # freezes an exact GitWorkspaceSnapshot and can own that authority.
        _reject(
            lambda: capability.PilotExactTaskExecutorCapability.from_mapping(
                {**proof.to_dict(), "execution_plan_materialized": True}
            )
        )

        # Capability materialization remains exactly one reviewed command. A
        # second catalog command cannot smuggle latent future execution authority.
        expanded_catalog = ModelRigCommandCatalog(
            (
                fixture["catalog"].resolve(VERSION_CHECK_COMMAND_ID),
                ProjectCommandSpec(
                    "modelrig.extra.check",
                    VERSION_CHECK_TOOL_ID,
                    (),
                    ".",
                    120,
                    {"CI": "1", "MODELRIG_DEVCONTROL": "1"},
                ),
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

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(proof.to_dict())
        assert set(schema["required"]) == set(proof.to_dict())
        assert props["executor_capability_materialized"]["const"] is True
        assert props["execution_plan_materialized"]["const"] is False
        assert props["execution_consumed"]["const"] is False
        assert capability.PilotExactTaskExecutorCapability.__dataclass_fields__[
            "execution_plan_materialized"
        ].default is False

        facade_source = inspect.getsource(capability)
        assert "install_pilot_exact_task_executor_capability_only_semantics" in facade_source
        semantics_source = inspect.getsource(
            __import__(
                "kaliv_dev_control._improvement_pilot_exact_task_executor_capability_semantics",
                fromlist=["x"],
            )
        )
        assert "GitWorkspaceSnapshot" in semantics_source
        assert "execution_plan_materialized" in semantics_source
    finally:
        capability_temp.cleanup()
        ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
