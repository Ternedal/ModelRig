"""Adversarial contract for ADR-DC-099 inert product-pilot task registry."""
from __future__ import annotations

from dataclasses import replace
import inspect
import json
import os
import sys
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from source_code import code_of  # noqa: E402
from kaliv_dev_control import improvement_human_pilot_decision as human  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_development_task_binding as task_binding  # noqa: E402
from kaliv_dev_control.contract import DevelopmentTask  # noqa: E402
from kaliv_dev_control.runtime_closure_builder import VERSION_CHECK_COMMAND_ID  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_lineage_attestation as lineage  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_task_registry as registry  # noqa: E402
import rsi_human_pilot_decision_production_boundary as human_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-product-pilot-task-registry-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_product_pilot_task_registry.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-099 unexpectedly accepted unsafe task-registry evidence")


def _fresh_go(fixture, lineage_receipt):
    live = lineage._get_live_product_pilot_lineage_inputs(lineage_receipt)
    assert live is not None
    requirements = live["preflight"].attestation.packet.preflight_requirements

    completion = human_contract.PhysicalCampaignIndependentHumanVerdictProof(
        verdict_sha256="1" * 64,
        signature_sha256="2" * 64,
        key_id="rsi-independent-verdict-test-key",
        issuer_actor_id="physical.reviewer",
        issuer_system_id=human_contract.INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID,
        main_freeze_proof_sha256="3" * 64,
        execution_proof_sha256="4" * 64,
        evidence_snapshot_sha256="5" * 64,
        admission_sha256="6" * 64,
        campaign_id=requirements.campaign_id,
        task_id=requirements.source_task_id,
        task_sha256=requirements.source_task_sha256,
        repository=requirements.repository,
        base_sha=requirements.base_sha,
        requested_main_sha=requirements.requested_main_sha,
        operator_actor_id="physical.operator",
        approver_actor_id="physical.approver",
        reviewer_actor_id="physical.reviewer",
        verdict_id="independent-verdict-registry",
        decision="approve",
        findings=(),
        reviewed_at_utc="2026-09-15T09:54:05Z",
        verified_at_utc="2026-09-15T09:54:06Z",
    )
    private_key, key = human_contract._trusted_key(actor="pilot.owner")
    decision = human.build_human_pilot_decision(
        completion_proof=completion,
        decision_id="pilot-registry-go-001",
        decision_maker_actor_id="pilot.owner",
        decision="go",
        operator_surface=lineage_receipt.operator_surface,
        allowed_task_ids=(lineage_receipt.selected_pilot_task_id,),
        workspace_root_path_sha256=lineage_receipt.workspace_root_path_sha256,
        local_commits_allowed=requirements.local_commits_allowed,
        notes=(),
        decided_at_utc="2026-09-15T09:54:10Z",
    )
    signature = human_contract._sign(decision, private_key, key)
    verifier = human_contract.Ed25519AuthorityVerifier(
        {key.key_id: key}, minimum_keyring_epoch=1
    )
    proof = human._verify_human_pilot_decision(
        completion_proof=completion,
        decision=decision,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T09:54:11Z",
    )
    return completion, decision, signature, proof


def _host_registry(lineage_receipt):
    live = lineage._get_live_product_pilot_lineage_inputs(lineage_receipt)
    assert live is not None
    requirements = live["preflight"].attestation.packet.preflight_requirements
    task = DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "PILOT_VERSION_CHECK_001",
            "repository": requirements.repository,
            "base_sha": requirements.base_sha,
            "goal": "Run the first exact local read-only ModelRig version-check pilot.",
            "acceptance_criteria": ["Produce the fixed version-check receipt without mutation."],
            "risk": "low",
            "allowed_paths": ["VERSION"],
            "protected_paths": [".github/workflows/**"],
            "allowed_command_ids": [VERSION_CHECK_COMMAND_ID],
            "required_tests": [VERSION_CHECK_COMMAND_ID],
            "budget": {
                "max_changed_files": 1,
                "max_added_lines": 1,
                "max_deleted_lines": 0,
                "max_attempts": 1,
                "max_runtime_seconds": 60,
                "max_output_bytes": 65536,
            },
            "merge_authority": "human",
        }
    )
    task_sha = hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()
    payload = {
        "schema": task_binding.PILOT_EXACT_TASK_DEVELOPMENT_TASK_REGISTRY_SCHEMA,
        "entries": [
            {
                "selected_pilot_task_id": lineage_receipt.selected_pilot_task_id,
                "development_task": task.to_dict(),
                "development_task_sha256": task_sha,
            }
        ],
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return raw, task, task_sha


def _build(lineage_receipt, proof, registry_payload, when="2026-09-15T09:54:20Z"):
    return registry._build_verified_product_pilot_task_registry(
        lineage_attestation=lineage_receipt,
        fresh_human_decision_proof=proof,
        registry_payload=registry_payload,
        now_provider=lambda: when,
    )


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = (
        lineage_contract._build_fixture()
        if owns_fixture
        else shared_fixture
    )
    try:
        lineage_receipt = lineage_contract._attest(fixture)
        assert lineage_receipt.attestation_authenticated is True
        _completion, _decision, _signature, proof = _fresh_go(fixture, lineage_receipt)
        registry_payload, development_task, development_task_sha = _host_registry(
            lineage_receipt
        )

        receipt = _build(lineage_receipt, proof, registry_payload)
        assert receipt.registry_authenticated is True
        assert receipt.lineage_attestation_sha256 == lineage_receipt.sha256
        assert receipt.fresh_human_decision_proof_sha256 == proof.sha256
        assert receipt.registered_task_ids == (lineage_receipt.selected_pilot_task_id,)
        assert receipt.host_development_task_registry_verified is True
        assert receipt.host_development_task_registry_sha256 == hashlib.sha256(registry_payload).hexdigest()
        assert receipt.development_task_id == development_task.task_id
        assert receipt.development_task_sha256 == development_task_sha
        assert receipt.fixed_command_id == VERSION_CHECK_COMMAND_ID
        assert receipt.task_registry_ready is True
        assert receipt.executor_wired is False
        assert receipt.runtime_preflight_satisfied is False
        assert receipt.product_pilot_start_ready is False
        assert receipt.product_pilot_start_authorized is False
        assert receipt.product_pilot_started is False
        assert receipt.task_execution_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.next_boundary_authorization_required is True
        assert receipt.human_go_age_seconds == 9

        serialized = registry.PilotExactTaskProductPilotTaskRegistryReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.sha256 == receipt.sha256
        assert serialized.registry_authenticated is False

        replayed_lineage = lineage.PilotExactTaskProductPilotLineageAttestationReceipt.from_mapping(
            lineage_receipt.to_dict()
        )
        assert replayed_lineage.attestation_authenticated is False
        _reject(lambda: registry._build_verified_product_pilot_task_registry(
            lineage_attestation=replayed_lineage,
            fresh_human_decision_proof=proof,
            registry_payload=registry_payload,
            now_provider=lambda: "2026-09-15T09:54:20Z",
        ))

        _reject(lambda: _build(lineage_receipt, proof, registry_payload, "2026-09-15T09:55:12Z"))

        wrong_workspace = replace(proof, workspace_root_path_sha256="f" * 64)
        _reject(lambda: _build(lineage_receipt, wrong_workspace, registry_payload))

        wrong_tasks = replace(proof, allowed_task_ids=("another-task",))
        _reject(lambda: _build(lineage_receipt, wrong_tasks, registry_payload))

        no_go = replace(proof, decision="no_go", pilot_go_authorized=False, notes=("stop",))
        _reject(lambda: _build(lineage_receipt, no_go, registry_payload))

        wrong_registry = json.loads(registry_payload.decode("utf-8"))
        wrong_registry["entries"][0]["selected_pilot_task_id"] = "different-task"
        wrong_registry_payload = json.dumps(
            wrong_registry,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        _reject(lambda: _build(lineage_receipt, proof, wrong_registry_payload))

        for field in (
            "executor_wired",
            "runtime_preflight_satisfied",
            "product_pilot_start_ready",
            "product_pilot_start_authorized",
            "product_pilot_started",
            "task_execution_authorized",
            "remote_write_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        ):
            raw = receipt.to_dict()
            raw[field] = True
            _reject(lambda raw=raw: registry.PilotExactTaskProductPilotTaskRegistryReceipt.from_mapping(raw))
    finally:
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(registry.PilotExactTaskProductPilotTaskRegistryReceipt.__dataclass_fields__)
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False

    public = inspect.signature(registry.build_pilot_exact_task_product_pilot_task_registry)
    assert tuple(public.parameters) == (
        "lineage_attestation",
        "completion_proof",
        "human_pilot_decision",
        "human_pilot_decision_signature",
    )

    source = code_of(SOURCE)
    assert "verify_human_pilot_decision(" in source
    assert "_read_host_controlled_registry()" in source
    assert "_parse_registry_payload(" in source
    for forbidden in (
        "subprocess.",
        "urllib.",
        "requests.",
        "http.client",
        ".write_text(",
        ".write_bytes(",
        ".unlink(",
        ".rename(",
    ):
        assert forbidden not in source


if __name__ == "__main__":
    run_contract()
