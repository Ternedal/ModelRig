"""Adversarial contract for ADR-DC-105 product-pilot executor capability."""
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

from source_code import code_of  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_tier_a_substrate as substrate  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_admission as admission  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_executor_capability as capability  # noqa: E402
from kaliv_dev_control.runtime_closure_builder import VERSION_CHECK_COMMAND_ID  # noqa: E402
import rsi_pilot_exact_task_product_pilot_execution_admission_contract as admission_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402
from rsi_pilot_exact_task_executor_capability_contract import _authority_fixture  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-product-pilot-executor-capability-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_executor_capability.py"
)
LEGACY_SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "_improvement_pilot_exact_task_executor_capability_impl.py"
)
SUBSTRATE_SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "_improvement_pilot_exact_task_tier_a_substrate.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-105 unexpectedly accepted unsafe executor capability")


def _admission(fixture):
    (
        auth_temp,
        tx_temp,
        _tx_ledger,
        start,
        _authorization,
        ready,
        registry_payload,
        task,
        _task_registry,
    ) = admission_contract._start(fixture)
    admitted = admission._build_verified_product_pilot_execution_admission(
        start_state=start,
        registry_payload=registry_payload,
        now_provider=lambda: "2026-09-15T09:55:00Z",
    )
    assert admitted.admission_authenticated is True
    return auth_temp, tx_temp, admitted, task


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    auth_temp = None
    tx_temp = None
    capability_temp = None
    try:
        auth_temp, tx_temp, admitted, task = _admission(fixture)
        assert admitted.fixed_command_id == VERSION_CHECK_COMMAND_ID
        capability_temp = tempfile.TemporaryDirectory(
            prefix="rsi-product-pilot-executor-capability-"
        )
        authority = _authority_fixture(Path(capability_temp.name).resolve(), task)
        original_path_sha = capability._path_sha256

        def scoped_path_sha(path: Path) -> str:
            candidate = Path(path)
            if candidate == authority["workspace"]:
                return admitted.workspace_root_path_sha256
            return original_path_sha(candidate)

        def forbidden_git_run(*_args, **_kwargs):
            raise AssertionError(
                "ADR-DC-105 capability materialization must not start Git"
            )

        with patch.object(
            authority["git_runner"], "run", side_effect=forbidden_git_run
        ):
            receipt = capability._materialize_verified_product_pilot_executor_capability(
                execution_admission=admitted,
                catalog=authority["catalog"],
                toolchain=authority["toolchain"],
                isolation_attestation=authority["attestation"],
                physical_verifier=authority["physical_verifier"],
                signed_runtime_closure=authority["signed_closure"],
                runtime_closure_verifier=authority["runtime_verifier"],
                trusted_runtime_root=authority["trusted"],
                git_runner=authority["git_runner"],
                workspace_root=authority["workspace"],
                control_plane_root=authority["control"],
                path_sha256=scoped_path_sha,
            )

        assert receipt.capability_authenticated is True
        assert receipt.execution_admission_sha256 == admitted.sha256
        assert receipt.development_task_id == task.task_id
        assert receipt.development_task_sha256 == admitted.development_task_sha256
        assert receipt.development_task_base_sha == task.base_sha
        assert receipt.fixed_command_id == VERSION_CHECK_COMMAND_ID
        assert receipt.catalog_sha256 == authority["catalog"].sha256
        assert receipt.toolchain_sha256 == authority["toolchain"].sha256
        assert receipt.signed_runtime_closure_sha256 == authority["signed_closure"].sha256
        assert receipt.workspace_root_authority_sha256 == authority["workspace_authority"]
        assert receipt.toolhost_sha256 == authority["toolhost_sha"]
        assert receipt.product_pilot_started is True
        assert receipt.execution_admission_authenticated is True
        assert receipt.executor_capability_materialized is True
        assert receipt.physical_isolation_verified is True
        assert receipt.runtime_closure_verified is True
        assert receipt.trusted_git_runtime_verified is True
        assert receipt.execution_plan_materialization_authorized is True
        assert receipt.execution_plan_materialized is False
        assert receipt.task_execution_authorized is False
        assert receipt.task_execution_started is False
        assert receipt.task_execution_completed is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.next_boundary_execution_plan_required is True

        live = capability._get_live_product_pilot_executor_capability_inputs(receipt)
        assert live is not None
        assert live["execution_admission"] is admitted
        assert live["git_runner"] is authority["git_runner"]
        assert live["task"] == task

        serialized = capability.PilotExactTaskProductPilotExecutorCapabilityReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.capability_authenticated is False

        replayed_admission = admission.PilotExactTaskProductPilotExecutionAdmissionReceipt.from_mapping(
            admitted.to_dict()
        )
        assert replayed_admission.admission_authenticated is False
        _reject(
            lambda: capability._materialize_verified_product_pilot_executor_capability(
                execution_admission=replayed_admission,
                catalog=authority["catalog"],
                toolchain=authority["toolchain"],
                isolation_attestation=authority["attestation"],
                physical_verifier=authority["physical_verifier"],
                signed_runtime_closure=authority["signed_closure"],
                runtime_closure_verifier=authority["runtime_verifier"],
                trusted_runtime_root=authority["trusted"],
                git_runner=authority["git_runner"],
                workspace_root=authority["workspace"],
                control_plane_root=authority["control"],
                path_sha256=scoped_path_sha,
            )
        )

        wrong_path = lambda _path: "f" * 64
        _reject(
            lambda: capability._materialize_verified_product_pilot_executor_capability(
                execution_admission=admitted,
                catalog=authority["catalog"],
                toolchain=authority["toolchain"],
                isolation_attestation=authority["attestation"],
                physical_verifier=authority["physical_verifier"],
                signed_runtime_closure=authority["signed_closure"],
                runtime_closure_verifier=authority["runtime_verifier"],
                trusted_runtime_root=authority["trusted"],
                git_runner=authority["git_runner"],
                workspace_root=authority["workspace"],
                control_plane_root=authority["control"],
                path_sha256=wrong_path,
            )
        )

        for field, value in (
            ("execution_plan_materialization_authorized", False),
            ("execution_plan_materialized", True),
            ("task_execution_authorized", True),
            ("task_execution_started", True),
            ("task_execution_completed", True),
            ("local_commit_authorized", True),
            ("remote_write_authorized", True),
            ("production_activation_authorized", True),
            ("next_boundary_execution_plan_required", False),
            ("nonce_reusable", True),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: capability.PilotExactTaskProductPilotExecutorCapabilityReceipt.from_mapping(
                    raw
                )
            )
    finally:
        if capability_temp is not None:
            capability_temp.cleanup()
        if tx_temp is not None:
            tx_temp.cleanup()
        if auth_temp is not None:
            auth_temp.cleanup()
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        capability.PilotExactTaskProductPilotExecutorCapabilityReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False

    public = inspect.signature(
        capability.materialize_pilot_exact_task_product_pilot_executor_capability
    )
    assert tuple(public.parameters) == ("execution_admission",)

    legacy_source = code_of(LEGACY_SOURCE)
    product_source = code_of(SOURCE)
    shared_source = code_of(SUBSTRATE_SOURCE).lower()
    assert "tier_a_substrate.materialize_verified_tier_a_substrate(" in legacy_source
    assert "tier_a_substrate.materialize_verified_tier_a_substrate(" in product_source
    for forbidden in (
        "subprocess.",
        "run_verified_tier_a_command",
        "run_single_verified_tier_a_command_with_receipt",
        ".run(",
        ".evidence(",
        "requests.",
        "urllib.",
        "socket.",
        "create_once_file",
    ):
        assert forbidden not in shared_source


if __name__ == "__main__":
    run_contract()
