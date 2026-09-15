"""Adversarial contract for ADR-DC-061 ready-for-review reservation."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_authorization as ready_auth  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_reservation as reservation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_handoff_requirements as handoff  # noqa: E402
from rsi_pilot_exact_task_pr_ready_for_review_authorization_contract import _human_authority  # noqa: E402
from rsi_pilot_exact_task_pr_review_handoff_requirements_contract import _live_transaction, _reader  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-ready-for-review-reservation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        reservation.PilotExactTaskPrReadyReservationError,
        ready_auth.PilotExactTaskPrReadyAuthorizationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-061 unexpectedly accepted unsafe ready reservation")


def run_contract() -> None:
    if os.name == "nt":
        return

    tx, _pr_requirements, identity, cleanup = _live_transaction()
    ledger_temp = TemporaryDirectory(prefix="rsi-pr-ready-reservation-061-")
    try:
        requirements = handoff._materialize_verified_pilot_exact_task_pr_review_handoff_requirements(
            pr_create_transaction=tx,
            reader=_reader,
            now_provider=lambda: "2026-09-15T06:24:00Z",
        )
        ready_nonce = hashlib.sha256(b"ready-for-review-nonce-061").hexdigest()
        claim = ready_auth.build_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=requirements,
            authorization_id="exact-pr-ready-authorization-061",
            ready_for_review_authorizer_actor_id=(
                requirements.required_ready_for_review_authorizer_actor_id
            ),
            authorized_at_utc="2026-09-15T06:24:10Z",
            expires_at_utc="2026-09-15T06:34:00Z",
            ready_for_review_nonce_sha256=ready_nonce,
            notes=("reserve exact ready-for-review handoff only",),
        )
        verifier, signature = _human_authority(claim)
        proof = ready_auth._verify_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:24:20Z",
        )
        fresh = ready_auth._verify_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:24:30Z",
        )

        ledger = reservation._PilotExactTaskPrReadyReservationLedger(
            Path(ledger_temp.name)
        )
        receipt = reservation._reserve_verified_pilot_exact_task_pr_ready_for_review(
            supplied_authorization_proof=proof,
            fresh_authorization_proof=fresh,
            ledger=ledger,
            now_provider=lambda: "2026-09-15T06:24:40Z",
        )
        assert receipt.reservation_authenticated is True
        assert receipt.reservation_key_sha256 == ready_nonce
        assert receipt.ready_for_review_nonce_sha256 == ready_nonce
        assert receipt.pr_mutation_nonce_sha256 == tx.pr_mutation_nonce_sha256
        assert receipt.review_handoff_requirements_sha256 == requirements.sha256
        assert receipt.pr_create_transaction_sha256 == tx.sha256
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.review_handoff_plan_sha256 == requirements.review_handoff_plan_sha256
        assert receipt.repository == "Ternedal/ModelRig"
        assert receipt.pull_request_number == tx.pull_request_number
        assert receipt.pull_request_api_url == tx.pull_request_api_url
        assert receipt.pull_request_html_url == tx.pull_request_html_url
        assert receipt.base_branch == "main"
        assert receipt.head_branch == tx.head_branch
        assert receipt.fresh_verified_at_utc == "2026-09-15T06:24:30Z"
        assert receipt.reserved_at_utc == "2026-09-15T06:24:40Z"

        for field in (
            "host_replay_guard_committed",
            "human_ready_for_review_authorization_freshly_verified",
            "ready_for_review_authorization_consumed",
            "ready_for_review_slot_reserved",
            "fresh_pr_state_revalidation_before_ready_required",
            "reviewer_mutation_separate_authority_required",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        ):
            assert getattr(receipt, field) is True
        for field in (
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "ready_for_review_authorized",
            "ready_for_review_performed",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(receipt, field) is False

        path = ledger._path(ready_nonce)
        assert path.is_file()
        expected_payload = receipt.canonical_json().encode("utf-8")
        assert path.read_bytes() == expected_payload

        later_fresh = ready_auth._verify_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:24:45Z",
        )
        _reject(
            lambda: reservation._reserve_verified_pilot_exact_task_pr_ready_for_review(
                supplied_authorization_proof=proof,
                fresh_authorization_proof=later_fresh,
                ledger=ledger,
                now_provider=lambda: "2026-09-15T06:24:50Z",
            )
        )
        assert path.read_bytes() == expected_payload

        reloaded = reservation.PilotExactTaskPrReadyReservationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.reservation_authenticated is False

        reloaded_proof = ready_auth.PilotExactTaskPrReadyAuthorizationProof.from_mapping(
            proof.to_dict()
        )
        _reject(lambda: reservation._require_live_proof(reloaded_proof))

        changed_claim = ready_auth.build_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=requirements,
            authorization_id="changed-ready-authorization-061",
            ready_for_review_authorizer_actor_id=(
                requirements.required_ready_for_review_authorizer_actor_id
            ),
            authorized_at_utc="2026-09-15T06:24:10Z",
            expires_at_utc="2026-09-15T06:34:00Z",
            ready_for_review_nonce_sha256=ready_nonce,
            notes=("different signed payload",),
        )
        changed_verifier, changed_signature = _human_authority(changed_claim)
        changed_proof = ready_auth._verify_pilot_exact_task_pr_ready_authorization(
            review_handoff_requirements=requirements,
            authorization=changed_claim,
            signature=changed_signature,
            verifier=changed_verifier,
            now_provider=lambda: "2026-09-15T06:24:30Z",
        )
        _reject(lambda: reservation._require_fresh_proof_identity(proof, changed_proof))
        _reject(
            lambda: reservation._require_reservation_window(
                fresh,
                at_utc="2026-09-15T06:25:31Z",
            )
        )

        path.write_bytes(b"tampered-ready-reservation")
        assert receipt.reservation_authenticated is False

        serialized = receipt.to_dict()
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(serialized)
        assert set(schema["required"]) == set(serialized)
        assert schema["properties"]["ready_for_review_authorization_consumed"]["const"] is True
        assert schema["properties"]["ready_for_review_slot_reserved"]["const"] is True
        assert schema["properties"]["ready_for_review_authorized"]["const"] is False
        assert schema["properties"]["ready_for_review_performed"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            reservation.reserve_pilot_exact_task_pr_ready_for_review
        ).parameters
        assert tuple(public_parameters) == (
            "authorization_proof",
            "authorization_signature",
        )

        _reject(
            lambda: reservation.reserve_pilot_exact_task_pr_ready_for_review(
                proof,
                signature,
            )
        )

        source = inspect.getsource(reservation)
        assert "urllib.request" not in source
        assert "requests." not in source
        assert "create_pull_request(" not in source
        assert "update_pull_request(" not in source
        assert "mark_pull_request_ready_for_review(" not in source
        assert "request_pull_request_reviewers(" not in source
        assert "merge_pull_request(" not in source
        assert "ready_for_review_authorized: bool = False" in source
        assert "ready_for_review_performed: bool = False" in source
        assert "production_activation_authorized: bool = False" in source
    finally:
        ledger_temp.cleanup()
        for temp in cleanup:
            temp.cleanup()


if __name__ == "__main__":
    run_contract()
