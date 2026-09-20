"""Focused replay contract: one ADR-DC-030 execution nonce gets one host slot."""
from __future__ import annotations

import json
import os
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

import kaliv_dev_control.improvement_pilot_exact_task_execution_admission as admission  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_authorization as auth  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_revalidation_attestation as verify  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_revalidation_observation as obs  # noqa: E402
from rsi_pilot_exact_task_execution_admission_contract import _ledger, _proof  # noqa: E402
from rsi_pilot_exact_task_execution_revalidation_attestation_contract import (  # noqa: E402
    _host_authority,
)
from rsi_pilot_exact_task_execution_revalidation_observation_contract import (  # noqa: E402
    _evidence,
    _human_authority,
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-033 reused execution nonce unexpectedly admitted twice")


def run_contract() -> None:
    source_temp, proof, fresh, *_ = _proof()
    proof_cache_temp = tempfile.TemporaryDirectory(
        prefix="rsi-exact-task-admission-proof-cache-"
    )
    proof_cache_path = Path(proof_cache_temp.name) / "proofs.json"
    proof_cache_path.write_text(
        json.dumps(
            {"proof": proof.to_dict(), "fresh": fresh.to_dict()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    previous_proof_cache = os.environ.get("MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE")
    os.environ["MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE"] = str(proof_cache_path)
    ledger_temp, ledger = _ledger("rsi-exact-task-admission-nonce-reuse-")
    try:
        source_authorization = (
            proof.attestation.packet.execution_authorization_proof.authorization
        )
        requirements = source_authorization.execution_requirements

        # Issue a distinct, correctly signed ADR-DC-030 authorization that
        # deliberately reuses the already signed one-shot execution nonce.
        # ADR-DC-030 validates structure/signature, while ADR-DC-033 owns the
        # host-local create-once replay guard for that nonce.
        second_authorization = auth.build_pilot_exact_task_execution_authorization(
            execution_requirements=requirements,
            authorization_id="exact-task-execution-authorization-033-reused-nonce",
            execution_authorizer_actor_id=(
                source_authorization.execution_authorizer_actor_id
            ),
            authorized_at_utc="2026-09-14T08:32:10Z",
            expires_at_utc="2026-09-14T08:42:00Z",
            execution_nonce_sha256=source_authorization.execution_nonce_sha256,
            notes=("deliberate nonce-reuse adversarial case",),
        )
        second_human_verifier, second_human_signature = _human_authority(
            second_authorization
        )
        second_authorization_proof = (
            auth._verify_pilot_exact_task_execution_authorization(
                execution_requirements=requirements,
                authorization=second_authorization,
                signature=second_human_signature,
                verifier=second_human_verifier,
                now_provider=lambda: "2026-09-14T08:33:10Z",
            )
        )
        assert (
            second_authorization_proof.sha256
            != proof.execution_authorization_proof_sha256
        )
        assert (
            second_authorization_proof.execution_nonce_sha256
            == proof.execution_nonce_sha256
        )

        second_packet = obs.build_pilot_exact_task_execution_revalidation_observation_packet(
            execution_authorization_proof=second_authorization_proof,
            observation_id="exact-task-revalidation-observation-033-reused-nonce",
            observer_actor_id=proof.attestation.packet.observer_actor_id,
            observed_at_utc="2026-09-14T08:34:10Z",
            evidence_sha256=_evidence(second_authorization_proof),
        )
        second_claim = verify.build_pilot_exact_task_execution_revalidation_attestation(
            packet=second_packet,
            attestation_id="exact-task-revalidation-attestation-033-reused-nonce",
            observer_host_id="modelrig-authority-host-033-reused-nonce",
            attested_at_utc="2026-09-14T08:35:10Z",
            results={name: True for name in verify.RESULT_FIELDS},
        )
        second_host_verifier, second_host_signature = _host_authority(second_claim)
        second_proof = verify._verify_pilot_exact_task_execution_revalidation_attestation(
            attestation=second_claim,
            signature=second_host_signature,
            verifier=second_host_verifier,
            now_provider=lambda: "2026-09-14T08:36:00Z",
        )
        second_fresh = verify._verify_pilot_exact_task_execution_revalidation_attestation(
            attestation=second_claim,
            signature=second_host_signature,
            verifier=second_host_verifier,
            now_provider=lambda: "2026-09-14T08:36:15Z",
        )

        assert second_proof.execution_authorization_proof_sha256 != (
            proof.execution_authorization_proof_sha256
        )
        assert second_proof.execution_nonce_sha256 == proof.execution_nonce_sha256
        assert admission._admission_key(proof) == proof.execution_nonce_sha256
        assert admission._admission_key(second_proof) == proof.execution_nonce_sha256

        first_times = iter(("2026-09-14T08:36:20Z", "2026-09-14T08:36:21Z"))
        first_receipt = admission._admit_verified_exact_task_execution(
            supplied_proof=proof,
            fresh_proof=fresh,
            ledger=ledger,
            now_provider=lambda: next(first_times),
        )
        assert first_receipt.admission_key_sha256 == proof.execution_nonce_sha256

        # The second authorization has a different proof identity, but because
        # it reuses the same signed nonce it must collide with the permanent
        # create-once marker and fail closed.
        second_times = iter(("2026-09-14T08:36:22Z", "2026-09-14T08:36:23Z"))
        _reject(
            lambda: admission._admit_verified_exact_task_execution(
                supplied_proof=second_proof,
                fresh_proof=second_fresh,
                ledger=ledger,
                now_provider=lambda: next(second_times),
            )
        )
    finally:
        ledger_temp.cleanup()
        source_temp.cleanup()

    # This focused contract owns only the ADR-DC-033 nonce-reuse boundary.
    # ADR-DC-034 onward are sibling Stage-B phases owned by the admission driver;
    # never recursively launch their internally parallel workers from this guard.
    try:
        pass
    finally:
        if previous_proof_cache is None:
            os.environ.pop("MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE", None)
        else:
            os.environ["MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE"] = previous_proof_cache
        proof_cache_temp.cleanup()


if __name__ == "__main__":
    run_contract()
