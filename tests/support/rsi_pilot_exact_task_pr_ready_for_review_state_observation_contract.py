"""Adversarial contract for ADR-DC-062 fresh ready-for-review state observation."""
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
from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_state_observation as state  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_handoff_requirements as handoff  # noqa: E402
from rsi_pilot_exact_task_pr_ready_for_review_authorization_contract import _human_authority  # noqa: E402
from rsi_pilot_exact_task_pr_review_handoff_requirements_contract import _live_transaction, _reader  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-ready-for-review-state-observation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        state.PilotExactTaskPrReadyStateObservationError,
        reservation.PilotExactTaskPrReadyReservationError,
        ready_auth.PilotExactTaskPrReadyAuthorizationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-062 unexpectedly accepted unsafe fresh PR state")


def _material():
    tx, _pr_requirements, identity, cleanup = _live_transaction()
    requirements = handoff._materialize_verified_pilot_exact_task_pr_review_handoff_requirements(
        pr_create_transaction=tx,
        reader=_reader,
        now_provider=lambda: "2026-09-15T06:24:00Z",
    )
    nonce = hashlib.sha256(b"ready-for-review-nonce-062").hexdigest()
    claim = ready_auth.build_pilot_exact_task_pr_ready_authorization(
        review_handoff_requirements=requirements,
        authorization_id="exact-pr-ready-authorization-062",
        ready_for_review_authorizer_actor_id=(
            requirements.required_ready_for_review_authorizer_actor_id
        ),
        authorized_at_utc="2026-09-15T06:24:10Z",
        expires_at_utc="2026-09-15T06:34:00Z",
        ready_for_review_nonce_sha256=nonce,
        notes=("observe exact ready-for-review state only",),
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
    ledger_temp = TemporaryDirectory(prefix="rsi-pr-ready-state-062-reservation-")
    ledger = reservation._PilotExactTaskPrReadyReservationLedger(
        Path(ledger_temp.name)
    )
    receipt = reservation._reserve_verified_pilot_exact_task_pr_ready_for_review(
        supplied_authorization_proof=proof,
        fresh_authorization_proof=fresh,
        ledger=ledger,
        now_provider=lambda: "2026-09-15T06:24:40Z",
    )
    return tx, requirements, identity, receipt, ledger_temp, cleanup


def _fresh_reader(*, pr_create_transaction, pr_mutation_requirements):
    return dict(
        _reader(
            pr_create_transaction=pr_create_transaction,
            pr_mutation_requirements=pr_mutation_requirements,
        )
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    tx, requirements, identity, receipt, ledger_temp, cleanup = _material()
    try:
        result = state._observe_verified_pilot_exact_task_pr_ready_for_review_state(
            ready_for_review_reservation=receipt,
            reader=_fresh_reader,
            now_provider=lambda: "2026-09-15T06:24:50Z",
        )
        assert result.observation_authenticated is True
        assert result.ready_for_review_reservation_sha256 == receipt.sha256
        assert result.review_handoff_requirements_sha256 == requirements.sha256
        assert result.pr_create_transaction_sha256 == tx.sha256
        assert result.predicted_commit_sha == identity.predicted_commit_sha
        assert result.review_handoff_plan_sha256 == requirements.review_handoff_plan_sha256
        assert result.ready_for_review_nonce_sha256 == receipt.ready_for_review_nonce_sha256
        assert result.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == tx.pull_request_number
        assert result.pull_request_api_url == tx.pull_request_api_url
        assert result.pull_request_html_url == tx.pull_request_html_url
        assert result.base_branch == "main"
        assert result.head_branch == tx.head_branch
        assert result.signed_observed_updated_at_utc == "2026-09-15T06:23:50Z"
        assert result.fresh_observed_updated_at_utc == "2026-09-15T06:23:50Z"
        assert result.observed_at_utc == "2026-09-15T06:24:50Z"

        for field in (
            "ready_for_review_authorization_consumed",
            "ready_for_review_slot_reserved",
            "credential_free_read_verified",
            "redirects_forbidden",
            "response_bounded",
            "pull_request_open_verified",
            "draft_state_verified",
            "exact_head_sha_verified",
            "exact_base_verified",
            "exact_metadata_verified",
            "signed_updated_at_still_current",
            "ready_for_review_transaction_required",
            "reviewer_mutation_separate_authority_required",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        ):
            assert getattr(result, field) is True
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
            assert getattr(result, field) is False

        reloaded = state.PilotExactTaskPrReadyStateObservation.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.observation_authenticated is False

        reloaded_receipt = reservation.PilotExactTaskPrReadyReservationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded_receipt.reservation_authenticated is False
        _reject(lambda: state._require_live_reservation(reloaded_receipt))

        def drifted_reader(*, pr_create_transaction, pr_mutation_requirements):
            evidence = _fresh_reader(
                pr_create_transaction=pr_create_transaction,
                pr_mutation_requirements=pr_mutation_requirements,
            )
            evidence["observed_updated_at_utc"] = "2026-09-15T06:23:51Z"
            return evidence

        _reject(
            lambda: state._observe_verified_pilot_exact_task_pr_ready_for_review_state(
                ready_for_review_reservation=receipt,
                reader=drifted_reader,
                now_provider=lambda: "2026-09-15T06:24:50Z",
            )
        )

        def wrong_url_reader(*, pr_create_transaction, pr_mutation_requirements):
            evidence = _fresh_reader(
                pr_create_transaction=pr_create_transaction,
                pr_mutation_requirements=pr_mutation_requirements,
            )
            evidence["request_url_sha256"] = hashlib.sha256(
                b"https://api.github.com/repos/Ternedal/Other/pulls/1"
            ).hexdigest()
            return evidence

        _reject(
            lambda: state._observe_verified_pilot_exact_task_pr_ready_for_review_state(
                ready_for_review_reservation=receipt,
                reader=wrong_url_reader,
                now_provider=lambda: "2026-09-15T06:24:50Z",
            )
        )

        _reject(
            lambda: state._observe_verified_pilot_exact_task_pr_ready_for_review_state(
                ready_for_review_reservation=receipt,
                reader=_fresh_reader,
                now_provider=lambda: "2026-09-15T06:25:41Z",
            )
        )

        serialized = result.to_dict()
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(serialized)
        assert set(schema["required"]) == set(serialized)
        assert schema["properties"]["signed_updated_at_still_current"]["const"] is True
        assert schema["properties"]["ready_for_review_transaction_required"]["const"] is True
        assert schema["properties"]["ready_for_review_authorized"]["const"] is False
        assert schema["properties"]["ready_for_review_performed"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            state.observe_pilot_exact_task_pr_ready_for_review_state
        ).parameters
        assert tuple(public_parameters) == ("ready_for_review_reservation",)

        source = inspect.getsource(state)
        assert "create_pull_request(" not in source
        assert "update_pull_request(" not in source
        assert "mark_pull_request_ready_for_review(" not in source
        assert "request_pull_request_reviewers(" not in source
        assert "merge_pull_request(" not in source
        assert "reader=requirements_boundary._read_exact_draft_pr_state" in source
        assert "ready_for_review_authorized: bool = False" in source
        assert "ready_for_review_performed: bool = False" in source
        assert "production_activation_authorized: bool = False" in source
    finally:
        ledger_temp.cleanup()
        for temp in cleanup:
            temp.cleanup()


if __name__ == "__main__":
    run_contract()
