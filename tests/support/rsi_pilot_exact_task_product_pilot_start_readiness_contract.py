"""Adversarial contract for ADR-DC-096 product-pilot start readiness."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
from source_code import code_of  # noqa: E402
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_readiness as readiness  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_post_production_activation_attestation as attestation  # noqa: E402
import rsi_pilot_exact_task_post_production_activation_attestation_contract as attestation_contract  # noqa: E402
import rsi_pilot_exact_task_production_activation_transaction_contract as tx_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-start-readiness-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_start_readiness.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-096 unexpectedly accepted unsafe pilot readiness")


def _source():
    fixture = tx_contract._fixture()
    transaction = tx_contract._execute(fixture)
    tx_contract._assert_consumed(transaction)
    recovery_ledger = attestation_contract._empty_recovery_ledger(fixture)
    source = attestation_contract._attest(fixture, recovery_ledger)
    return fixture, source


def _evaluate(source, when: str):
    moments = iter((when,))
    return readiness._evaluate_verified_pilot_exact_task_product_pilot_start_readiness(
        source,
        now_provider=moments.__next__,
    )


def _assert_inert(receipt) -> None:
    assert receipt.production_activation is True
    assert receipt.production_activation_attested is True
    assert receipt.post_production_state_verified is True
    assert receipt.product_pilot_start_ready is True
    assert receipt.product_pilot_start_authorized is False
    assert receipt.product_pilot_started is False
    assert receipt.manual_intervention_required is False
    assert receipt.promotion_gate_execution_authorized is False
    assert receipt.production_env_mutation_authorized is False
    assert receipt.appliance_restart_authorized is False
    assert receipt.production_receipt_write_authorized is False
    assert receipt.production_activation_authorized is False
    assert receipt.success_deployment_status_authorized is False
    assert receipt.deployment_status_mutation_authorized is False
    assert receipt.deployment_mutation_authorized is False
    assert receipt.deploy_authorized is False
    assert receipt.remote_write_authorized is False
    assert receipt.release_authorized is False
    assert receipt.tag_write_authorized is False
    assert receipt.release_mutation_authorized is False
    assert receipt.merge_authorized is False
    assert receipt.push_authorized is False
    assert receipt.pr_mutation_authorized is False
    assert receipt.review_submission_authorized is False
    assert receipt.review_thread_mutation_authorized is False
    assert receipt.nonce_reusable is False
    assert receipt.next_boundary_authorization_required is True


def run_contract() -> None:
    if os.name == "nt":
        return

    fixture, source = _source()
    try:
        receipt = _evaluate(source, "2026-09-15T09:54:21Z")
        assert receipt.readiness_authenticated is True
        assert (
            receipt.post_production_activation_attestation_sha256
            == source.sha256
        )
        assert (
            receipt.production_activation_candidate_sha256
            == source.production_activation_candidate_sha256
        )
        assert (
            receipt.production_activation_completion_source
            == source.production_activation_completion_source
        )
        assert (
            receipt.production_activation_source_receipt_sha256
            == source.production_activation_source_receipt_sha256
        )
        assert (
            receipt.production_activation_transaction_lock_sha256
            == source.production_activation_transaction_lock_sha256
        )
        assert receipt.environment_after_sha256 == source.environment_after_sha256
        assert receipt.output_state_sha256 == source.output_state_sha256
        assert receipt.production_preflight_sha256 == source.production_preflight_sha256
        assert (
            receipt.machine_production_receipt_sha256
            == source.machine_production_receipt_sha256
        )
        assert receipt.repository == source.repository
        assert receipt.repository_id == source.repository_id
        assert receipt.merge_commit_sha == source.merge_commit_sha
        assert receipt.promotion_git_sha == source.promotion_git_sha
        assert (
            receipt.post_production_attested_at_utc
            == source.second_observed_at_utc
        )
        assert receipt.attestation_age_seconds == 20
        _assert_inert(receipt)

        serialized = readiness.PilotExactTaskProductPilotStartReadinessReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.readiness_authenticated is False

        for field, value in (
            ("production_activation", False),
            ("production_activation_attested", False),
            ("post_production_state_verified", False),
            ("product_pilot_start_ready", False),
            ("product_pilot_start_authorized", True),
            ("product_pilot_started", True),
            ("production_activation_authorized", True),
            ("remote_write_authorized", True),
            ("next_boundary_authorization_required", False),
            ("nonce_reusable", True),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: readiness.PilotExactTaskProductPilotStartReadinessReceipt.from_mapping(
                    raw
                )
            )

        exact_boundary = _evaluate(source, "2026-09-15T09:55:01Z")
        assert exact_boundary.attestation_age_seconds == 60
        assert exact_boundary.readiness_authenticated is True
        _reject(lambda: _evaluate(source, "2026-09-15T09:55:02Z"))
        _reject(lambda: _evaluate(source, "2026-09-15T09:54:00Z"))

        loose_source = (
            attestation.PilotExactTaskPostProductionActivationAttestationReceipt.from_mapping(
                source.to_dict()
            )
        )
        assert loose_source.attestation_authenticated is False
        _reject(lambda: _evaluate(loose_source, "2026-09-15T09:54:21Z"))

        raw = receipt.to_dict()
        raw["attestation_age_seconds"] = 19
        _reject(
            lambda: readiness.PilotExactTaskProductPilotStartReadinessReceipt.from_mapping(
                raw
            )
        )
    finally:
        tx_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        readiness.PilotExactTaskProductPilotStartReadinessReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields

    public_signature = inspect.signature(
        readiness.evaluate_pilot_exact_task_product_pilot_start_readiness
    )
    assert tuple(public_signature.parameters) == (
        "post_production_activation_attestation",
    )

    source_code = code_of(SOURCE)
    for forbidden in (
        "subprocess.",
        "create_once_file",
        "urllib",
        "requests.",
        "http.client",
        "\"POST\"",
        "\"PUT\"",
        "\"PATCH\"",
        "\"DELETE\"",
        ".write_text(",
        ".write_bytes(",
        ".unlink(",
        ".rename(",
    ):
        assert forbidden not in source_code
    assert "attest_pilot_exact_task_post_production_activation(" not in source_code
    assert "execute_pilot_exact_task_production_activation(" not in source_code
    assert "recover_pilot_exact_task_production_activation(" not in source_code


if __name__ == "__main__":
    run_contract()
