"""Adversarial contract for ADR-DC-035 host-pinned DevelopmentTask binding."""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control  # noqa: E402
from kaliv_dev_control.contract import DevelopmentTask  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_admission as admission  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_plan_requirements as plan_req  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_development_task_binding as binding  # noqa: E402
import kaliv_dev_control._improvement_pilot_exact_task_development_task_binding_production_boundary as production  # noqa: E402
from rsi_pilot_exact_task_execution_plan_requirements_contract import _live_receipt  # noqa: E402

REGISTRY_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-development-task-registry-v1.schema.json"
)
BINDING_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-development-task-binding-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-035 unexpectedly accepted invalid input")


def _task(requirements, *, task_id: str = "DC_L16_VERSION_CHECK", command_ids=None) -> DevelopmentTask:
    commands = ["modelrig.version.check"] if command_ids is None else list(command_ids)
    return DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": task_id,
            "repository": requirements.repository,
            "base_sha": requirements.base_sha,
            "goal": "Run the exact read-only ModelRig version check.",
            "acceptance_criteria": ["The reviewed version check exits successfully."],
            "risk": "low",
            "allowed_paths": ["VERSION"],
            "protected_paths": ["devcontrol/**"],
            "allowed_command_ids": commands,
            "required_tests": commands,
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


def _task_sha(task: DevelopmentTask) -> str:
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def _registry(requirements, task: DevelopmentTask, *, pilot_id: str | None = None) -> bytes:
    selected = requirements.selected_pilot_task_id if pilot_id is None else pilot_id
    value = {
        "schema": binding.PILOT_EXACT_TASK_DEVELOPMENT_TASK_REGISTRY_SCHEMA,
        "entries": [
            {
                "selected_pilot_task_id": selected,
                "development_task": task.to_dict(),
                "development_task_sha256": _task_sha(task),
            }
        ],
    }
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def run_contract() -> None:
    source_temp, ledger_temp, receipt = _live_receipt()
    try:
        requirements = plan_req.build_pilot_exact_task_execution_plan_requirements(receipt)
        task = _task(requirements)
        payload = _registry(requirements, task)
        proof = binding._bind_verified_development_task(
            plan_requirements=requirements,
            admission_receipt=receipt,
            registry_payload=payload,
        )
        assert proof.schema == binding.PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_SCHEMA
        assert proof.authority == binding.PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY
        assert proof.plan_requirements is requirements
        assert proof.plan_requirements_sha256 == requirements.sha256
        assert proof.admission_receipt_sha256 == receipt.sha256
        assert proof.execution_nonce_sha256 == receipt.execution_nonce_sha256
        assert proof.registry_sha256 == hashlib.sha256(payload).hexdigest()
        assert proof.selected_pilot_task_id == requirements.selected_pilot_task_id
        assert proof.development_task == task
        assert proof.development_task_id == "DC_L16_VERSION_CHECK"
        assert proof.development_task_id != proof.selected_pilot_task_id
        assert proof.development_task_sha256 == _task_sha(task)
        assert proof.fixed_command_id == "modelrig.version.check"
        assert proof.host_registry_verified is True
        assert proof.pilot_task_mapping_verified is True
        assert proof.development_task_materialized is True
        assert proof.single_fixed_command_verified is True
        assert proof.execution_plan_materialized is False
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

        # Durable binding evidence round-trips, but nested receipts remain inert.
        replayed = binding.PilotExactTaskDevelopmentTaskBinding.from_mapping(
            proof.to_dict()
        )
        assert replayed == proof
        assert replayed.sha256 == proof.sha256
        assert replayed.plan_requirements.admission_receipt.transaction_authenticated is False

        # The same requirements cannot cross ADR-DC-035 with a reloaded receipt.
        reloaded_receipt = admission.PilotExactTaskExecutionAdmissionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded_receipt.transaction_authenticated is False
        _reject(
            lambda: binding._bind_verified_development_task(
                plan_requirements=requirements,
                admission_receipt=reloaded_receipt,
                registry_payload=payload,
            )
        )

        # Caller/model cannot substitute another pilot mapping.
        _reject(
            lambda: binding._bind_verified_development_task(
                plan_requirements=requirements,
                admission_receipt=receipt,
                registry_payload=_registry(requirements, task, pilot_id="different-task"),
            )
        )

        # Registry task must be exact repository/base and one fixed command.
        wrong_base = DevelopmentTask.from_mapping(
            {**task.to_dict(), "base_sha": "f" * 40}
        )
        _reject(
            lambda: binding._bind_verified_development_task(
                plan_requirements=requirements,
                admission_receipt=receipt,
                registry_payload=_registry(requirements, wrong_base),
            )
        )
        multi = _task(
            requirements,
            task_id="DC_L16_MULTI",
            command_ids=["modelrig.version.check", "modelrig.test.second"],
        )
        _reject(lambda: binding._parse_registry_payload(_registry(requirements, multi)))

        # Task hash and canonical JSON are part of host registry authority.
        registry_value = json.loads(payload.decode("utf-8"))
        registry_value["entries"][0]["development_task_sha256"] = "f" * 64
        bad_hash = json.dumps(
            registry_value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        _reject(lambda: binding._parse_registry_payload(bad_hash))
        _reject(lambda: binding._parse_registry_payload(payload + b"\n"))

        # Authority flags cannot be escalated in serialized evidence.
        for field in (
            "execution_plan_materialized",
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
                lambda field=field: binding.PilotExactTaskDevelopmentTaskBinding.from_mapping(
                    {**proof.to_dict(), field: True}
                )
            )
        for field in (
            "host_registry_verified",
            "pilot_task_mapping_verified",
            "development_task_materialized",
            "single_fixed_command_verified",
        ):
            _reject(
                lambda field=field: binding.PilotExactTaskDevelopmentTaskBinding.from_mapping(
                    {**proof.to_dict(), field: False}
                )
            )

        # Production reads only the fixed host-controlled registry and exposes no
        # caller-selected registry/path parameter.
        original_elevated = production._require_elevated_operator
        original_read = production._read_keyring_bytes
        original_path = production._canonical_registry_path
        calls = []
        try:
            production._require_elevated_operator = lambda: None
            production._canonical_registry_path = lambda: Path("/fixed/host/registry.json")

            def fake_read(path, *, require_host_control):
                calls.append((path, require_host_control))
                return payload

            production._read_keyring_bytes = fake_read
            production_proof = binding.bind_pilot_exact_task_development_task(
                plan_requirements=requirements,
                admission_receipt=receipt,
            )
            assert production_proof == proof
            assert calls == [(Path("/fixed/host/registry.json"), True)]
            _reject(
                lambda: binding.bind_pilot_exact_task_development_task(
                    plan_requirements=requirements,
                    admission_receipt=receipt,
                    registry_payload=payload,
                )
            )
        finally:
            production._require_elevated_operator = original_elevated
            production._read_keyring_bytes = original_read
            production._canonical_registry_path = original_path

        registry_schema = json.loads(REGISTRY_SCHEMA.read_text(encoding="utf-8"))
        assert registry_schema["additionalProperties"] is False
        assert registry_schema["properties"]["schema"]["const"] == (
            binding.PILOT_EXACT_TASK_DEVELOPMENT_TASK_REGISTRY_SCHEMA
        )
        task_schema = registry_schema["$defs"]["developmentTask"]
        assert task_schema["properties"]["task_id"]["pattern"] == "^[A-Z][A-Z0-9_-]{2,63}$"
        assert task_schema["properties"]["allowed_command_ids"]["maxItems"] == 1
        assert task_schema["properties"]["merge_authority"]["const"] == "human"

        binding_schema = json.loads(BINDING_SCHEMA.read_text(encoding="utf-8"))
        props = binding_schema["properties"]
        assert set(props) == set(proof.to_dict())
        assert binding_schema["additionalProperties"] is False
        assert props["schema"]["const"] == binding.PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_SCHEMA
        assert props["authority"]["const"] == binding.PILOT_EXACT_TASK_DEVELOPMENT_TASK_BINDING_AUTHORITY
        assert props["development_task"]["$ref"].endswith("#/$defs/developmentTask")
        for field in (
            "host_registry_verified",
            "pilot_task_mapping_verified",
            "development_task_materialized",
            "single_fixed_command_verified",
        ):
            assert props[field]["const"] is True
        for field in (
            "execution_plan_materialized",
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
            assert props[field]["const"] is False

        root_source = inspect.getsource(kaliv_dev_control)
        assert "improvement_pilot_exact_task_development_task_binding" not in root_source
        impl_source = inspect.getsource(binding._implementation).lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
            "create_pull_request",
            "run_verified_tier_a_command",
            "run_single_verified_tier_a_command_with_receipt",
        ):
            assert forbidden not in impl_source, forbidden
    finally:
        ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
