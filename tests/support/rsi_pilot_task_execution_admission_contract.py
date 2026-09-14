"""Adversarial contract for ADR-DC-029 one-shot task execution admission."""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control  # noqa: E402
from kaliv_dev_control import catalog  # noqa: E402
import kaliv_dev_control.improvement_pilot_execution_admission_attestation as att  # noqa: E402
import kaliv_dev_control.improvement_pilot_task_execution_admission as admission  # noqa: E402
import kaliv_dev_control._improvement_pilot_task_execution_admission_production_boundary as production  # noqa: E402
from rsi_pilot_execution_admission_attestation_contract import (  # noqa: E402
    _authority,
    _claim,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-task-execution-admission-receipt-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-029 unexpectedly accepted invalid input")


def _proof(*, all_green: bool = True):
    temp, claim = _claim(all_green=all_green)
    verifier, signature = _authority(claim)
    proof = att._verify_pilot_execution_admission_attestation(
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:30:30Z",
    )
    fresh = att._verify_pilot_execution_admission_attestation(
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:30:45Z",
    )
    return temp, proof, fresh, signature


def _ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name).resolve()
    return temp, admission._PilotTaskExecutionAdmissionLedger(root)


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()

    source_temp, proof, fresh, signature = _proof()
    ledger_temp, ledger = _ledger("rsi-task-admission-")
    try:
        start_receipt = proof.attestation.packet.admission_requirements.start_receipt
        assert start_receipt.transaction_authenticated is True
        assert proof.execution_admission_satisfied is True
        assert proof.task_execution_authorized is False

        # Production liveness is deliberately checked on the exact caller object
        # before any serialization strips transaction provenance.
        production._require_live_start_receipt(proof)
        reloaded_proof = att.PilotExecutionAdmissionAttestationProof.from_mapping(
            proof.to_dict()
        )
        assert (
            reloaded_proof.attestation.packet.admission_requirements.start_receipt.transaction_authenticated
            is False
        )
        _reject(lambda: production._require_live_start_receipt(reloaded_proof))
        _reject(
            lambda: admission.admit_pilot_task_execution(
                attestation_proof=reloaded_proof,
                attestation_signature=signature,
            )
        )

        times = iter(("2026-09-14T08:31:00Z", "2026-09-14T08:31:01Z"))
        receipt = admission._admit_verified_pilot_task_execution(
            supplied_proof=proof,
            fresh_proof=fresh,
            ledger=ledger,
            now_provider=lambda: next(times),
        )

        requirements = proof.attestation.packet.admission_requirements
        assert receipt.schema == admission.PILOT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA
        assert receipt.authority == admission.PILOT_TASK_EXECUTION_ADMISSION_AUTHORITY
        assert receipt.ledger_scope == admission.PILOT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE
        assert receipt.attestation_proof == proof
        assert receipt.attestation_proof_sha256 == proof.sha256
        assert receipt.attestation_sha256 == proof.attestation_sha256
        assert receipt.attestation_signature_sha256 == proof.signature_sha256
        assert receipt.packet_sha256 == proof.packet_sha256
        assert receipt.start_receipt_sha256 == proof.start_receipt_sha256
        assert receipt.start_nonce_sha256 == requirements.start_receipt.start_nonce_sha256
        assert receipt.selected_pilot_task_id == requirements.selected_pilot_task_id
        assert receipt.workspace_root_path_sha256 == requirements.workspace_root_path_sha256
        assert (
            receipt.local_commits_allowed_by_human_scope
            is requirements.local_commits_allowed_by_human_scope
        )
        assert receipt.host_replay_guard_committed is True
        assert receipt.global_replay_safe is False
        assert receipt.one_shot_execution_required is True
        assert receipt.execution_admission_satisfied is True
        assert receipt.task_execution_authorized is True
        assert receipt.execution_consumed is False
        assert receipt.integration_ready is False
        assert receipt.product_pilot_started is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.transaction_authenticated is True

        # Durable receipt bytes remain historical evidence only. Reload cannot
        # recover the live one-shot authority provenance.
        reloaded = admission.PilotTaskExecutionAdmissionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.transaction_authenticated is False
        assert (
            reloaded.attestation_proof.attestation.packet.admission_requirements.start_receipt.transaction_authenticated
            is False
        )

        # The same exact proof cannot be admitted twice in one ledger.
        replay_times = iter(("2026-09-14T08:31:02Z", "2026-09-14T08:31:03Z"))
        _reject(
            lambda: admission._admit_verified_pilot_task_execution(
                supplied_proof=proof,
                fresh_proof=fresh,
                ledger=ledger,
                now_provider=lambda: next(replay_times),
            )
        )

        # Admission is tied to the short ADR-028 host-attestation freshness window.
        stale_temp, stale_ledger = _ledger("rsi-task-admission-stale-")
        try:
            _reject(
                lambda: admission._admit_verified_pilot_task_execution(
                    supplied_proof=proof,
                    fresh_proof=fresh,
                    ledger=stale_ledger,
                    now_provider=lambda: "2026-09-14T08:35:01Z",
                )
            )
        finally:
            stale_temp.cleanup()

        # A valid signed failed ADR-028 check is observed but cannot be admitted.
        failed_temp, failed_proof, failed_fresh, _failed_signature = _proof(
            all_green=False
        )
        failed_ledger_temp, failed_ledger = _ledger("rsi-task-admission-failed-")
        try:
            assert failed_proof.execution_admission_satisfied is False
            _reject(
                lambda: admission._admit_verified_pilot_task_execution(
                    supplied_proof=failed_proof,
                    fresh_proof=failed_fresh,
                    ledger=failed_ledger,
                    now_provider=lambda: "2026-09-14T08:31:00Z",
                )
            )
        finally:
            failed_ledger_temp.cleanup()
            failed_temp.cleanup()

        # Rebinding or authority escalation in serialized evidence must fail.
        mutations = {
            "admission_key_sha256": "0" * 64,
            "attestation_proof_sha256": "1" * 64,
            "start_receipt_sha256": "2" * 64,
            "start_nonce_sha256": "3" * 64,
            "selected_pilot_task_id": "different.task",
            "workspace_root_path_sha256": "4" * 64,
            "execution_admission_satisfied": False,
            "task_execution_authorized": False,
            "execution_consumed": True,
            "integration_ready": True,
            "product_pilot_started": True,
            "local_commit_authorized": True,
            "remote_write_authorized": True,
            "push_authorized": True,
            "pr_mutation_authorized": True,
            "merge_authorized": True,
            "release_authorized": True,
            "deploy_authorized": True,
            "production_activation_authorized": True,
        }
        for field, value in mutations.items():
            _reject(
                lambda field=field, value=value: admission.PilotTaskExecutionAdmissionReceipt.from_mapping(
                    {**receipt.to_dict(), field: value}
                )
            )
        _reject(
            lambda: admission.PilotTaskExecutionAdmissionReceipt.from_mapping(
                {**receipt.to_dict(), "local_commits_allowed_by_human_scope": 1}
            )
        )
        _reject(
            lambda: admission.PilotTaskExecutionAdmissionReceipt.from_mapping(
                {**receipt.to_dict(), "unexpected": False}
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert schema["additionalProperties"] is False
        assert (
            props["attestation_proof"]["$ref"]
            == "rsi-pilot-execution-admission-attestation-proof-v1.schema.json"
        )
        assert props["schema"]["const"] == admission.PILOT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA
        assert props["ledger_scope"]["const"] == admission.PILOT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE
        assert props["host_replay_guard_committed"]["const"] is True
        assert props["global_replay_safe"]["const"] is False
        assert props["one_shot_execution_required"]["const"] is True
        assert props["execution_admission_satisfied"]["const"] is True
        assert props["task_execution_authorized"]["const"] is True
        assert props["execution_consumed"]["const"] is False
        for field in (
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
        assert "improvement_pilot_task_execution_admission" not in root_source
        public_source = inspect.getsource(admission).lower()
        impl_source = inspect.getsource(
            sys.modules[
                "kaliv_dev_control._improvement_pilot_task_execution_admission_impl"
            ]
        ).lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
            "create_pull_request",
            "popen",
            "run_command",
        ):
            assert forbidden not in public_source, forbidden
            assert forbidden not in impl_source, forbidden
    finally:
        ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
