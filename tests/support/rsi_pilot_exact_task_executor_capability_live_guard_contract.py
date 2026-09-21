"""Adversarial freshness contract for ADR-DC-036 live executor capability."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path, PurePosixPath
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
from rsi_pilot_exact_task_execution_plan_requirements_contract import _live_receipt  # noqa: E402
from rsi_pilot_exact_task_executor_capability_contract import (  # noqa: E402
    _authority_fixture,
    _registry,
    _task,
)


def run_contract() -> None:
    if os.name == "nt":
        # The support fixture uses a synthetic POSIX Git runtime. Existing Windows
        # jobs cover the native host substrate; this contract covers live freshness.
        return

    source_temp, ledger_temp, receipt = _live_receipt()
    capability_temp = tempfile.TemporaryDirectory(prefix="rsi-executor-live-guard-")
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
                "ADR-DC-036 live freshness must not start a Git process"
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
            assert proof.materialization_authenticated is True

        # The guard remains valid after the deterministic signed-path shim is gone:
        # freshness is anchored to the canonical workspace authority established at
        # materialization, while the upstream path digest remains immutable evidence.
        assert proof.materialization_authenticated is True
        assert capability._get_live_capability_inputs(proof) is not None

        # Mutating the signed runtime entrypoint after materialization immediately
        # destroys live authority. Durable evidence still parses, but no later
        # executor boundary can recover the process-local inputs from this object.
        relative = PurePosixPath(
            fixture["signed_closure"].manifest.entrypoint_relative_path
        )
        entrypoint = fixture["trusted"].joinpath(*relative.parts)
        entrypoint.write_bytes(b"tampered after materialization\n")
        assert proof.materialization_authenticated is False
        assert capability._get_live_capability_inputs(proof) is None

        replayed = capability.PilotExactTaskExecutorCapability.from_mapping(
            proof.to_dict()
        )
        assert replayed.sha256 == proof.sha256
        assert replayed.materialization_authenticated is False
    finally:
        capability_temp.cleanup()
        ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
