"""Adversarial contract for ADR-DC-055 durable PR-mutation reservation."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_pr_mutation_authorization as auth  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_mutation_requirements as pr_requirements  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_mutation_reservation as reservation  # noqa: E402
from rsi_pilot_exact_task_pr_mutation_authorization_contract import (  # noqa: E402
    _human_authority,
    _live_remote_transaction,
)

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pr-mutation-reservation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        reservation.PilotExactTaskPrMutationReservationError,
        auth.PilotExactTaskPrMutationAuthorizationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-055 unexpectedly accepted unsafe PR reservation")


def run_contract() -> None:
    if os.name == "nt":
        return

    material = _live_remote_transaction()
    (
        transaction,
        identity,
        _publication_requirements,
        _credential_capability,
        broker_temp,
        remote_reservation_temp,
        transaction_temp,
        source_reservation_temp,
        execution_temp,
        local_reservation_temp,
        executor_capability_temp,
        admission_ledger_temp,
        source_temp,
    ) = material
    ledger_temp = TemporaryDirectory(prefix="rsi-pr-mutation-reservation-055-")
    try:
        with patch.object(
            pr_requirements,
            "_now_utc_seconds",
            return_value="2026-09-15T06:21:49Z",
        ):
            requirements = pr_requirements.materialize_pilot_exact_task_pr_mutation_requirements(
                transaction
            )
        nonce = hashlib.sha256(b"pr-mutation-nonce-055").hexdigest()
        claim = auth.build_pilot_exact_task_pr_mutation_authorization(
            pr_mutation_requirements=requirements,
            authorization_id="exact-pr-mutation-authorization-055",
            pr_mutation_authorizer_actor_id=(
                requirements.prior_remote_publication_authorizer_actor_id
            ),
            authorized_at_utc="2026-09-15T06:22:00Z",
            expires_at_utc="2026-09-15T06:32:00Z",
            pr_mutation_nonce_sha256=nonce,
            notes=("reserve one exact draft PR mutation",),
        )
        verifier, signature = _human_authority(claim)
        supplied = auth._verify_pilot_exact_task_pr_mutation_authorization(
            pr_mutation_requirements=requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:23:00Z",
        )
        fresh = auth._verify_pilot_exact_task_pr_mutation_authorization(
            pr_mutation_requirements=requirements,
            authorization=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T06:23:10Z",
        )
        assert supplied.sha256 != fresh.sha256
        reservation._require_fresh_proof_identity(supplied, fresh)

        ledger = reservation._PilotExactTaskPrMutationReservationLedger(
            Path(ledger_temp.name)
        )
        receipt = reservation._reserve_verified_pilot_exact_task_pr_mutation(
            supplied_authorization_proof=supplied,
            fresh_authorization_proof=fresh,
            ledger=ledger,
            now_provider=lambda: "2026-09-15T06:23:20Z",
        )
        assert receipt.reservation_authenticated is True
        assert receipt.reservation_key_sha256 == nonce
        assert receipt.pr_mutation_nonce_sha256 == nonce
        assert receipt.supplied_authorization_proof_sha256 == supplied.sha256
        assert receipt.fresh_authorization_proof_sha256 == fresh.sha256
        assert receipt.authorization_sha256 == claim.sha256
        assert receipt.authorization_signature_sha256 == signature.sha256
        assert receipt.pr_mutation_requirements_sha256 == requirements.sha256
        assert receipt.remote_write_transaction_sha256 == transaction.sha256
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.pr_plan_sha256 == requirements.pr_plan_sha256
        assert receipt.repository == "Ternedal/ModelRig"
        assert receipt.base_branch == "main"
        assert receipt.head_branch == requirements.head_branch
        assert receipt.fresh_verified_at_utc == "2026-09-15T06:23:10Z"
        assert receipt.reserved_at_utc == "2026-09-15T06:23:20Z"

        for field in (
            "host_replay_guard_committed",
            "human_pr_mutation_authorization_freshly_verified",
            "pr_mutation_authorization_consumed",
            "pr_mutation_slot_reserved",
            "no_existing_open_pr_observation_required",
            "create_new_draft_pull_request_required",
            "draft_pull_request_required",
        ):
            assert getattr(receipt, field) is True
        for field in (
            "maintainer_can_modify",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_created",
            "ready_for_review_authorized",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(receipt, field) is False

        marker = Path(ledger_temp.name) / f"{nonce}.json"
        assert marker.read_bytes() == receipt.canonical_json().encode("utf-8")

        reloaded_receipt = reservation.PilotExactTaskPrMutationReservationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded_receipt == receipt
        assert reloaded_receipt.sha256 == receipt.sha256
        assert reloaded_receipt.reservation_authenticated is False

        # The same signed one-shot PR nonce is permanently spent.
        _reject(
            lambda: reservation._reserve_verified_pilot_exact_task_pr_mutation(
                supplied_authorization_proof=supplied,
                fresh_authorization_proof=fresh,
                ledger=ledger,
                now_provider=lambda: "2026-09-15T06:23:21Z",
            )
        )

        # Serialized proof loses the live ADR-DC-054 requirements authority.
        reloaded_proof = auth.PilotExactTaskPrMutationAuthorizationProof.from_mapping(
            supplied.to_dict()
        )
        _reject(lambda: reservation._require_live_proof(reloaded_proof))

        # A separately signed semantic claim cannot masquerade as the fresh proof.
        other_claim = auth.build_pilot_exact_task_pr_mutation_authorization(
            pr_mutation_requirements=requirements,
            authorization_id="exact-pr-mutation-authorization-055-other",
            pr_mutation_authorizer_actor_id=(
                requirements.prior_remote_publication_authorizer_actor_id
            ),
            authorized_at_utc="2026-09-15T06:22:00Z",
            expires_at_utc="2026-09-15T06:32:00Z",
            pr_mutation_nonce_sha256=hashlib.sha256(b"other-pr-nonce").hexdigest(),
        )
        other_verifier, other_signature = _human_authority(other_claim)
        other_proof = auth._verify_pilot_exact_task_pr_mutation_authorization(
            pr_mutation_requirements=requirements,
            authorization=other_claim,
            signature=other_signature,
            verifier=other_verifier,
            now_provider=lambda: "2026-09-15T06:23:10Z",
        )
        _reject(lambda: reservation._require_fresh_proof_identity(supplied, other_proof))

        _reject(
            lambda: reservation._require_reservation_window(
                fresh,
                at_utc="2026-09-15T06:24:11Z",
            )
        )

        for field in (
            "host_replay_guard_committed",
            "human_pr_mutation_authorization_freshly_verified",
            "pr_mutation_authorization_consumed",
            "pr_mutation_slot_reserved",
            "no_existing_open_pr_observation_required",
            "create_new_draft_pull_request_required",
            "draft_pull_request_required",
        ):
            changed = receipt.to_dict()
            changed[field] = False
            _reject(
                lambda changed=changed: reservation.PilotExactTaskPrMutationReservationReceipt.from_mapping(
                    changed
                )
            )
        for field in (
            "maintainer_can_modify",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_created",
            "ready_for_review_authorized",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            changed = receipt.to_dict()
            changed[field] = True
            _reject(
                lambda changed=changed: reservation.PilotExactTaskPrMutationReservationReceipt.from_mapping(
                    changed
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["pr_mutation_authorization_consumed"]["const"] is True
        assert schema["properties"]["pr_mutation_slot_reserved"]["const"] is True
        assert schema["properties"]["pull_request_create_authorized"]["const"] is False
        assert schema["properties"]["pull_request_created"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            reservation.reserve_pilot_exact_task_pr_mutation
        ).parameters
        assert tuple(public_parameters) == (
            "authorization_proof",
            "authorization_signature",
        )
        source = inspect.getsource(reservation)
        assert "create_pull_request(" not in source
        assert "update_pull_request(" not in source
        assert "mark_pull_request_ready_for_review(" not in source
        assert "request_pull_request_reviewers(" not in source
        assert "label_pr(" not in source
        assert "merge_pull_request(" not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
    finally:
        ledger_temp.cleanup()
        broker_temp.cleanup()
        remote_reservation_temp.cleanup()
        transaction_temp.cleanup()
        source_reservation_temp.cleanup()
        execution_temp.cleanup()
        local_reservation_temp.cleanup()
        executor_capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
