"""Adversarial contract for ADR-DC-033 one-shot exact-task execution admission."""
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
import kaliv_dev_control._improvement_pilot_exact_task_execution_admission_impl as admission_impl  # noqa: E402
import kaliv_dev_control._improvement_pilot_exact_task_execution_admission_production_boundary as admission_boundary  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_admission as admission  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_revalidation_attestation as verify  # noqa: E402
from rsi_pilot_exact_task_execution_revalidation_attestation_contract import (  # noqa: E402
    _claim,
    _host_authority,
    _material,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-execution-admission-receipt-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-033 unexpectedly accepted invalid input")


class _ClockHarness:
    PilotExactTaskExecutionAdmissionError = admission.PilotExactTaskExecutionAdmissionError
    _utc = staticmethod(admission_impl._utc)

    def __init__(self, values: tuple[str, ...]) -> None:
        self._values = iter(values)

    def _now_utc_seconds(self) -> str:
        return next(self._values)


def _proof(*, all_green: bool = True):
    (
        temp,
        _admission_verifier,
        admission_signature,
        _human_verifier,
        human_signature,
        _authorization_proof,
        packet,
    ) = _material()
    claim = _claim(packet, all_green=all_green)
    verifier, signature = _host_authority(claim)
    proof = verify._verify_pilot_exact_task_execution_revalidation_attestation(
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:36:00Z",
    )
    fresh = verify._verify_pilot_exact_task_execution_revalidation_attestation(
        attestation=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:36:15Z",
    )
    return temp, proof, fresh, signature, human_signature, admission_signature


def _ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name).resolve()
    return temp, admission._PilotExactTaskExecutionAdmissionLedger(root)


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()

    source_temp, proof, fresh, _signature, _human_signature, _admission_signature = _proof()
    ledger_temp, ledger = _ledger("rsi-exact-task-admission-")
    try:
        packet = proof.attestation.packet
        assert proof.execution_revalidation_satisfied is True
        assert proof.task_execution_authorized is False
        assert proof.task_execution_started is False
        assert admission._admission_key(proof) == admission._admission_key(fresh)

        times = iter(("2026-09-14T08:36:20Z", "2026-09-14T08:36:21Z"))
        receipt = admission._admit_verified_exact_task_execution(
            supplied_proof=proof,
            fresh_proof=fresh,
            ledger=ledger,
            now_provider=lambda: next(times),
        )

        assert receipt.schema == admission.PILOT_EXACT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA
        assert receipt.authority == admission.PILOT_EXACT_TASK_EXECUTION_ADMISSION_AUTHORITY
        assert receipt.ledger_scope == admission.PILOT_EXACT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE
        assert receipt.revalidation_attestation_proof == proof
        assert receipt.revalidation_attestation_proof_sha256 == proof.sha256
        assert receipt.revalidation_attestation_sha256 == proof.attestation_sha256
        assert receipt.revalidation_attestation_signature_sha256 == proof.signature_sha256
        assert receipt.packet_sha256 == proof.packet_sha256
        assert (
            receipt.execution_authorization_proof_sha256
            == proof.execution_authorization_proof_sha256
        )
        assert (
            receipt.execution_authorization_signature_sha256
            == proof.execution_authorization_signature_sha256
        )
        assert receipt.admission_attestation_proof_sha256 == proof.admission_attestation_proof_sha256
        assert (
            receipt.admission_attestation_signature_sha256
            == proof.admission_attestation_signature_sha256
        )
        assert receipt.start_receipt_sha256 == packet.start_receipt_sha256
        assert receipt.execution_nonce_sha256 == proof.execution_nonce_sha256
        assert receipt.selected_pilot_task_id == packet.selected_pilot_task_id
        assert receipt.workspace_root_path_sha256 == packet.workspace_root_path_sha256
        assert (
            receipt.local_commits_allowed_by_human_scope
            is packet.local_commits_allowed_by_human_scope
        )
        assert receipt.host_replay_guard_committed is True
        assert receipt.execution_authorization_consumed is True
        assert receipt.one_shot_execution_required is True
        assert receipt.task_execution_admission_observed is True
        assert receipt.task_execution_authorized is True
        assert receipt.task_execution_started is False
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

        # Durable receipt bytes are historical evidence only. A reload cannot
        # recover the process-local transaction authority required by a later executor.
        reloaded = admission.PilotExactTaskExecutionAdmissionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.transaction_authenticated is False

        # Exact replay in the same ledger is rejected.
        replay_times = iter(("2026-09-14T08:36:22Z", "2026-09-14T08:36:23Z"))
        _reject(
            lambda: admission._admit_verified_exact_task_execution(
                supplied_proof=proof,
                fresh_proof=fresh,
                ledger=ledger,
                now_provider=lambda: next(replay_times),
            )
        )

        # Re-attesting the same human execution authorization/nonce cannot create
        # another replay slot: the ledger key is anchored below ADR-032 attestation identity.
        alternate_claim = verify.build_pilot_exact_task_execution_revalidation_attestation(
            packet=packet,
            attestation_id="exact-task-revalidation-attestation-033-retry",
            observer_host_id="modelrig-authority-host-033-retry",
            attested_at_utc="2026-09-14T08:35:30Z",
            results={name: True for name in verify.RESULT_FIELDS},
        )
        alternate_verifier, alternate_signature = _host_authority(alternate_claim)
        alternate_proof = verify._verify_pilot_exact_task_execution_revalidation_attestation(
            attestation=alternate_claim,
            signature=alternate_signature,
            verifier=alternate_verifier,
            now_provider=lambda: "2026-09-14T08:36:05Z",
        )
        alternate_fresh = verify._verify_pilot_exact_task_execution_revalidation_attestation(
            attestation=alternate_claim,
            signature=alternate_signature,
            verifier=alternate_verifier,
            now_provider=lambda: "2026-09-14T08:36:10Z",
        )
        assert alternate_proof.attestation_sha256 != proof.attestation_sha256
        assert alternate_proof.execution_nonce_sha256 == proof.execution_nonce_sha256
        assert admission._admission_key(alternate_proof) == receipt.admission_key_sha256
        reattest_times = iter(("2026-09-14T08:36:24Z", "2026-09-14T08:36:25Z"))
        _reject(
            lambda: admission._admit_verified_exact_task_execution(
                supplied_proof=alternate_proof,
                fresh_proof=alternate_fresh,
                ledger=ledger,
                now_provider=lambda: next(reattest_times),
            )
        )

        # A fresh proof must correspond to the exact supplied ADR-032 semantics.
        mismatch_temp, mismatch_ledger = _ledger("rsi-exact-task-admission-mismatch-")
        try:
            _reject(
                lambda: admission._admit_verified_exact_task_execution(
                    supplied_proof=proof,
                    fresh_proof=alternate_fresh,
                    ledger=mismatch_ledger,
                    now_provider=lambda: "2026-09-14T08:36:30Z",
                )
            )
        finally:
            mismatch_temp.cleanup()

        # Admission is bounded both by the human authorization expiry and a 300s
        # maximum age from the host revalidation attestation.
        stale_temp, stale_ledger = _ledger("rsi-exact-task-admission-stale-")
        try:
            _reject(
                lambda: admission._admit_verified_exact_task_execution(
                    supplied_proof=proof,
                    fresh_proof=fresh,
                    ledger=stale_ledger,
                    now_provider=lambda: "2026-09-14T08:40:01Z",
                )
            )
        finally:
            stale_temp.cleanup()

        # Production samples wall time both before and after the durable nonce
        # reservation. A backwards jump must fail closed even when both samples
        # would independently remain inside the signed freshness window. The
        # create-once lock must remain, so rollback cannot reopen the nonce.
        rollback_temp, rollback_ledger = _ledger("rsi-exact-task-admission-clock-rollback-")
        try:
            rollback_clock = admission_boundary._nondecreasing_admission_clock(
                _ClockHarness(
                    (
                        "2026-09-14T08:36:20Z",
                        "2026-09-14T08:36:19Z",
                    )
                )
            )
            _reject(
                lambda: admission._admit_verified_exact_task_execution(
                    supplied_proof=proof,
                    fresh_proof=fresh,
                    ledger=rollback_ledger,
                    now_provider=rollback_clock,
                )
            )
            assert any(rollback_ledger.root.iterdir())
            retry_times = iter(("2026-09-14T08:36:21Z", "2026-09-14T08:36:22Z"))
            _reject(
                lambda: admission._admit_verified_exact_task_execution(
                    supplied_proof=proof,
                    fresh_proof=fresh,
                    ledger=rollback_ledger,
                    now_provider=lambda: next(retry_times),
                )
            )

            equal_clock = admission_boundary._nondecreasing_admission_clock(
                _ClockHarness(
                    (
                        "2026-09-14T08:36:20Z",
                        "2026-09-14T08:36:20Z",
                    )
                )
            )
            assert equal_clock() == "2026-09-14T08:36:20Z"
            assert equal_clock() == "2026-09-14T08:36:20Z"
            invalid_clock = admission_boundary._nondecreasing_admission_clock(
                _ClockHarness(("not-a-time",))
            )
            _reject(invalid_clock)
        finally:
            rollback_temp.cleanup()

        # A cryptographically valid signed failed ADR-032 revalidation is audit
        # evidence only and cannot be promoted into execution admission.
        failed_temp, failed_proof, failed_fresh, *_ = _proof(all_green=False)
        failed_ledger_temp, failed_ledger = _ledger("rsi-exact-task-admission-failed-")
        try:
            assert failed_proof.execution_revalidation_satisfied is False
            _reject(
                lambda: admission._admit_verified_exact_task_execution(
                    supplied_proof=failed_proof,
                    fresh_proof=failed_fresh,
                    ledger=failed_ledger,
                    now_provider=lambda: "2026-09-14T08:36:20Z",
                )
            )
        finally:
            failed_ledger_temp.cleanup()
            failed_temp.cleanup()

        # Rebinding or post-serialization authority escalation must fail closed.
        mutations = {
            "admission_key_sha256": "1" * 64,
            "revalidation_attestation_proof_sha256": "2" * 64,
            "revalidation_attestation_sha256": "3" * 64,
            "revalidation_attestation_signature_sha256": "4" * 64,
            "packet_sha256": "5" * 64,
            "execution_authorization_proof_sha256": "6" * 64,
            "execution_authorization_signature_sha256": "7" * 64,
            "admission_attestation_proof_sha256": "8" * 64,
            "admission_attestation_signature_sha256": "9" * 64,
            "start_receipt_sha256": "a" * 64,
            "execution_nonce_sha256": "b" * 64,
            "selected_pilot_task_id": "different.task",
            "workspace_root_path_sha256": "c" * 64,
            "host_replay_guard_committed": False,
            "execution_authorization_consumed": False,
            "one_shot_execution_required": False,
            "task_execution_admission_observed": False,
            "task_execution_authorized": False,
            "task_execution_started": True,
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
                lambda field=field, value=value: admission.PilotExactTaskExecutionAdmissionReceipt.from_mapping(
                    {**receipt.to_dict(), field: value}
                )
            )
        _reject(
            lambda: admission.PilotExactTaskExecutionAdmissionReceipt.from_mapping(
                {**receipt.to_dict(), "local_commits_allowed_by_human_scope": 1}
            )
        )
        _reject(
            lambda: admission.PilotExactTaskExecutionAdmissionReceipt.from_mapping(
                {**receipt.to_dict(), "unexpected": False}
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert schema["additionalProperties"] is False
        assert props["revalidation_attestation_proof"]["$ref"] == (
            "rsi-pilot-exact-task-execution-revalidation-attestation-proof-v1.schema.json"
        )
        assert props["schema"]["const"] == admission.PILOT_EXACT_TASK_EXECUTION_ADMISSION_RECEIPT_SCHEMA
        assert props["ledger_scope"]["const"] == admission.PILOT_EXACT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE
        for field in (
            "host_replay_guard_committed",
            "execution_authorization_consumed",
            "one_shot_execution_required",
            "task_execution_admission_observed",
            "task_execution_authorized",
        ):
            assert props[field]["const"] is True
        for field in (
            "task_execution_started",
            "execution_consumed",
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
        assert "improvement_pilot_exact_task_execution_admission" not in root_source
        public_source = inspect.getsource(admission).lower()
        impl_source = inspect.getsource(
            sys.modules[
                "kaliv_dev_control._improvement_pilot_exact_task_execution_admission_impl"
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
