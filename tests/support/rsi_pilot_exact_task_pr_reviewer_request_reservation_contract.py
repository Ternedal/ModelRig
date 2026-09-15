"""Adversarial contract for ADR-DC-069 durable reviewer-request reservation."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_authorization as reviewer_auth  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_reservation as reservation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_target_attestation as target  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_request_authorization_contract import _human_authority  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_target_attestation_contract import _live_handoff  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-request-reservation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        reservation.PilotExactTaskPrReviewerRequestReservationError,
        reviewer_auth.PilotExactTaskPrReviewerRequestAuthorizationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-069 unexpectedly accepted unsafe reviewer reservation")


def _material():
    reviewer_requirements, cleanup = _live_handoff()
    policy = target.PilotExactTaskPrReviewerTargetPolicy(
        policy_epoch=1,
        reviewer_login="modelrig-reviewer",
        reviewer_user_id=246813579,
    )
    target_attestation = target._attest_verified_pilot_exact_task_pr_reviewer_target(
        reviewer_handoff_requirements=reviewer_requirements,
        reviewer_target_policy=policy,
        now_provider=lambda: "2026-09-15T06:25:11Z",
    )
    reviewer_nonce = hashlib.sha256(b"reviewer-request-nonce-069").hexdigest()
    claim = reviewer_auth.build_pilot_exact_task_pr_reviewer_request_authorization(
        reviewer_target_attestation=target_attestation,
        authorization_id="exact-pr-reviewer-request-reservation-069",
        reviewer_request_authorizer_actor_id=(
            target_attestation.required_reviewer_authorizer_actor_id
        ),
        authorized_at_utc="2026-09-15T06:25:20Z",
        expires_at_utc="2026-09-15T06:35:00Z",
        reviewer_request_nonce_sha256=reviewer_nonce,
        notes=("reserve exact reviewer request once",),
    )
    verifier, signature = _human_authority(claim)
    supplied = reviewer_auth._verify_pilot_exact_task_pr_reviewer_request_authorization(
        reviewer_target_attestation=target_attestation,
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T06:25:30Z",
    )
    fresh = reviewer_auth._verify_pilot_exact_task_pr_reviewer_request_authorization(
        reviewer_target_attestation=target_attestation,
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T06:25:31Z",
    )
    return target_attestation, claim, signature, supplied, fresh, cleanup


def run_contract() -> None:
    if os.name == "nt":
        return

    target_attestation, claim, signature, supplied, fresh, cleanup = _material()
    ledger_temp = TemporaryDirectory(prefix="rsi-reviewer-request-reservation-069-")
    try:
        ledger = reservation._PilotExactTaskPrReviewerRequestReservationLedger(
            Path(ledger_temp.name)
        )
        result = reservation._reserve_verified_pilot_exact_task_pr_reviewer_request(
            supplied_authorization_proof=supplied,
            fresh_authorization_proof=fresh,
            ledger=ledger,
            now_provider=lambda: "2026-09-15T06:25:32Z",
        )
        assert result.reservation_authenticated is True
        assert result.reservation_key_sha256 == claim.reviewer_request_nonce_sha256
        assert result.reviewer_request_nonce_sha256 == claim.reviewer_request_nonce_sha256
        assert result.ready_for_review_nonce_sha256 == claim.ready_for_review_nonce_sha256
        assert result.reviewer_target_attestation_sha256 == target_attestation.sha256
        assert result.reviewer_handoff_requirements_sha256 == (
            target_attestation.reviewer_handoff_requirements_sha256
        )
        assert result.ready_transaction_sha256 == target_attestation.ready_transaction_sha256
        assert result.predicted_commit_sha == target_attestation.predicted_commit_sha
        assert result.reviewer_handoff_plan_sha256 == target_attestation.reviewer_handoff_plan_sha256
        assert result.reviewer_target_policy_sha256 == target_attestation.reviewer_target_policy_sha256
        assert result.reviewer_target_policy_epoch == 1
        assert result.reviewer_login == "modelrig-reviewer"
        assert result.reviewer_user_id == 246813579
        assert result.fresh_verified_at_utc == "2026-09-15T06:25:31Z"
        assert result.reserved_at_utc == "2026-09-15T06:25:32Z"
        assert ledger._path(claim.reviewer_request_nonce_sha256).is_file()

        for field in (
            "host_replay_guard_committed",
            "human_reviewer_request_authorization_freshly_verified",
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_observation_required",
            "reviewer_requestability_observation_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
            "self_review_forbidden",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        # Same signed nonce is permanently spent after the first create-once write.
        _reject(lambda: reservation._reserve_verified_pilot_exact_task_pr_reviewer_request(
            supplied_authorization_proof=supplied,
            fresh_authorization_proof=fresh,
            ledger=ledger,
            now_provider=lambda: "2026-09-15T06:25:33Z",
        ))

        reloaded = reservation.PilotExactTaskPrReviewerRequestReservationReceipt.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.reservation_authenticated is False

        # Structural/reloaded proof cannot restore live reviewer target authority.
        reloaded_proof = reviewer_auth.PilotExactTaskPrReviewerRequestAuthorizationProof.from_mapping(
            supplied.to_dict()
        )
        assert reloaded_proof == supplied
        _reject(lambda: reservation._require_live_proof(reloaded_proof))

        # Fresh proof may differ only in verification timestamp.
        changed_claim = reviewer_auth.build_pilot_exact_task_pr_reviewer_request_authorization(
            reviewer_target_attestation=target_attestation,
            authorization_id="changed-reviewer-request-reservation-069",
            reviewer_request_authorizer_actor_id=(
                target_attestation.required_reviewer_authorizer_actor_id
            ),
            authorized_at_utc="2026-09-15T06:25:20Z",
            expires_at_utc="2026-09-15T06:35:00Z",
            reviewer_request_nonce_sha256=claim.reviewer_request_nonce_sha256,
            notes=("different signed semantics",),
        )
        changed_verifier, changed_signature = _human_authority(changed_claim)
        changed_proof = reviewer_auth._verify_pilot_exact_task_pr_reviewer_request_authorization(
            reviewer_target_attestation=target_attestation,
            authorization=changed_claim,
            signature=changed_signature,
            verifier=changed_verifier,
            now_provider=lambda: "2026-09-15T06:25:31Z",
        )
        _reject(lambda: reservation._require_fresh_proof_identity(supplied, changed_proof))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(
            reservation.PilotExactTaskPrReviewerRequestReservationReceipt.__dataclass_fields__
        )
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["properties"]["reviewer_request_authorization_consumed"]["const"] is True
        assert schema["properties"]["reviewer_mutation_authorized"]["const"] is False
        assert schema["properties"]["reviewer_request_performed"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(inspect.signature(
            reservation.reserve_pilot_exact_task_pr_reviewer_request
        ).parameters) == (
            "authorization_proof",
            "authorization_signature",
        )
        source = inspect.getsource(reservation)
        assert "request_pull_request_reviewers(" not in source
        assert "urllib.request" not in source
        assert "subprocess" not in source
    finally:
        ledger_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
