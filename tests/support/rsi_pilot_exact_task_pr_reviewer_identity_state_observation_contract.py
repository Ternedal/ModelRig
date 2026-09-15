"""Adversarial contract for ADR-DC-070 reviewer identity and PR-state observation."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_identity_state_observation as observation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_reservation as reservation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_target_attestation as target_boundary  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_request_reservation_contract import _material  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-identity-state-observation-v1.schema.json"
)
REVIEWER_NODE_ID = "MDQ6VXNlcjI0NjgxMzU3OQ=="
AUTHOR_ID = 97531
AUTHOR_LOGIN = "modelrig-author"


def _reject(fn) -> None:
    try:
        fn()
    except (
        observation.PilotExactTaskPrReviewerIdentityStateObservationError,
        reservation.PilotExactTaskPrReviewerRequestReservationError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-070 unexpectedly accepted unsafe reviewer observation")


def _live_reservation():
    target, _claim, _signature, supplied, fresh, cleanup = _material()
    ledger_temp = TemporaryDirectory(prefix="rsi-reviewer-identity-state-070-")
    ledger = reservation._PilotExactTaskPrReviewerRequestReservationLedger(
        Path(ledger_temp.name)
    )
    receipt = reservation._reserve_verified_pilot_exact_task_pr_reviewer_request(
        supplied_authorization_proof=supplied,
        fresh_authorization_proof=fresh,
        ledger=ledger,
        now_provider=lambda: "2026-09-15T06:25:32Z",
    )
    inputs = target_boundary._get_live_pr_reviewer_target_attestation_inputs(target)
    requirements = inputs["reviewer_handoff_requirements"]
    return receipt, target, requirements, (ledger_temp, *cleanup)


def _reviewer_evidence(*, reservation_receipt, reviewer_target):
    assert reservation_receipt.reviewer_user_id == reviewer_target.reviewer_user_id
    url = f"https://api.github.com/users/{reviewer_target.reviewer_login}"
    return {
        "reviewer_request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
        "reviewer_response_body_sha256": hashlib.sha256(b"reviewer-identity-070").hexdigest(),
        "reviewer_response_etag_sha256": hashlib.sha256(b"reviewer-etag-070").hexdigest(),
        "reviewer_node_id_sha256": hashlib.sha256(REVIEWER_NODE_ID.encode("utf-8")).hexdigest(),
    }


def _pr_evidence(*, reservation_receipt, reviewer_target, reviewer_handoff_requirements):
    assert reviewer_handoff_requirements.pr_title
    return {
        "pr_request_url_sha256": hashlib.sha256(
            reservation_receipt.pull_request_api_url.encode("utf-8")
        ).hexdigest(),
        "pr_response_body_sha256": hashlib.sha256(b"reviewer-pr-state-070").hexdigest(),
        "pr_response_etag_sha256": hashlib.sha256(b"reviewer-pr-etag-070").hexdigest(),
        "pull_request_author_login": AUTHOR_LOGIN,
        "pull_request_author_user_id": AUTHOR_ID,
        "observed_updated_at_utc": reviewer_target.ready_updated_at_utc,
        "requested_reviewer_count": 0,
        "requested_team_count": 0,
    }


class _FakeResponse:
    def __init__(self, document: dict, *, status: int = 200, etag: str = 'W/"070"') -> None:
        self.status = status
        self.headers = {"ETag": etag}
        self._payload = json.dumps(document, separators=(",", ":")).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, maximum: int) -> bytes:
        return self._payload[:maximum]


class _FakeOpener:
    def __init__(self, response) -> None:
        self.response = response
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        return self.response


def _reviewer_document(target, *, user_id=None, login=None):
    selected_login = target.reviewer_login if login is None else login
    return {
        "login": selected_login,
        "id": target.reviewer_user_id if user_id is None else user_id,
        "node_id": REVIEWER_NODE_ID,
        "type": "User",
        "url": f"https://api.github.com/users/{target.reviewer_login}",
    }


def _pr_document(receipt, target, requirements, *, reviewers=None, teams=None, author_id=AUTHOR_ID, updated_at=None):
    return {
        "number": receipt.pull_request_number,
        "node_id": requirements.pull_request_node_id,
        "url": receipt.pull_request_api_url,
        "html_url": receipt.pull_request_html_url,
        "state": "open",
        "closed_at": None,
        "merged_at": None,
        "draft": False,
        "title": requirements.pr_title,
        "body": requirements.pr_body,
        "maintainer_can_modify": False,
        "updated_at": target.ready_updated_at_utc if updated_at is None else updated_at,
        "requested_reviewers": [] if reviewers is None else reviewers,
        "requested_teams": [] if teams is None else teams,
        "user": {"login": AUTHOR_LOGIN, "id": author_id},
        "head": {
            "ref": receipt.head_branch,
            "sha": receipt.predicted_commit_sha,
            "repo": {"full_name": receipt.repository},
        },
        "base": {
            "ref": receipt.base_branch,
            "repo": {"full_name": receipt.repository},
        },
    }


def run_contract() -> None:
    if os.name == "nt":
        return

    receipt, target, requirements, cleanup = _live_reservation()
    try:
        result = observation._observe_verified_pilot_exact_task_pr_reviewer_identity_state(
            reviewer_request_reservation=receipt,
            reviewer_reader=_reviewer_evidence,
            pr_reader=_pr_evidence,
            now_provider=lambda: "2026-09-15T06:25:40Z",
        )
        assert result.observation_authenticated is True
        assert result.reviewer_request_reservation_sha256 == receipt.sha256
        assert result.reviewer_target_attestation_sha256 == target.sha256
        assert result.reviewer_handoff_requirements_sha256 == requirements.sha256
        assert result.ready_transaction_sha256 == target.ready_transaction_sha256
        assert result.predicted_commit_sha == receipt.predicted_commit_sha
        assert result.reviewer_target_policy_sha256 == target.reviewer_target_policy_sha256
        assert result.reviewer_target_policy_epoch == target.reviewer_target_policy_epoch
        assert result.ready_for_review_nonce_sha256 == receipt.ready_for_review_nonce_sha256
        assert result.reviewer_request_nonce_sha256 == receipt.reviewer_request_nonce_sha256
        assert result.reviewer_login == target.reviewer_login
        assert result.reviewer_user_id == target.reviewer_user_id
        assert result.pull_request_author_login == AUTHOR_LOGIN
        assert result.pull_request_author_user_id == AUTHOR_ID
        assert result.ready_updated_at_utc == target.ready_updated_at_utc
        assert result.observed_updated_at_utc == target.ready_updated_at_utc
        assert result.observed_at_utc == "2026-09-15T06:25:40Z"

        for field in (
            "reviewer_public_identity_verified",
            "reviewer_numeric_user_id_verified",
            "reviewer_not_pr_author_verified",
            "ready_pr_state_freshly_revalidated",
            "no_requested_reviewers_verified",
            "credential_free_reads",
            "redirects_forbidden",
            "responses_bounded",
            "credentialed_reviewer_requestability_check_required",
            "reviewer_request_credential_capability_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "reviewer_requestability_verified",
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        reloaded = observation.PilotExactTaskPrReviewerIdentityStateObservation.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.observation_authenticated is False

        reloaded_receipt = reservation.PilotExactTaskPrReviewerRequestReservationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded_receipt.reservation_authenticated is False
        _reject(lambda: observation._require_live_reservation(reloaded_receipt))

        too_late = lambda: observation._observe_verified_pilot_exact_task_pr_reviewer_identity_state(
            reviewer_request_reservation=receipt,
            reviewer_reader=_reviewer_evidence,
            pr_reader=_pr_evidence,
            now_provider=lambda: "2026-09-15T06:26:33Z",
        )
        _reject(too_late)

        reviewer_opener = _FakeOpener(_FakeResponse(_reviewer_document(target)))
        with patch.object(observation.urllib.request, "build_opener", return_value=reviewer_opener):
            evidence = observation._read_exact_reviewer_identity(
                reservation_receipt=receipt,
                reviewer_target=target,
            )
        assert evidence["reviewer_node_id_sha256"] == hashlib.sha256(
            REVIEWER_NODE_ID.encode("utf-8")
        ).hexdigest()
        request, timeout = reviewer_opener.requests[0]
        assert request.get_method() == "GET"
        assert request.full_url == f"https://api.github.com/users/{target.reviewer_login}"
        assert timeout == observation.PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_STATE_TIMEOUT_SECONDS
        lowered = {name.lower() for name in request.headers}
        assert "authorization" not in lowered
        assert "cookie" not in lowered

        wrong_id_opener = _FakeOpener(
            _FakeResponse(_reviewer_document(target, user_id=target.reviewer_user_id + 1))
        )
        with patch.object(observation.urllib.request, "build_opener", return_value=wrong_id_opener):
            _reject(lambda: observation._read_exact_reviewer_identity(
                reservation_receipt=receipt,
                reviewer_target=target,
            ))

        pr_opener = _FakeOpener(_FakeResponse(_pr_document(receipt, target, requirements)))
        with patch.object(observation.urllib.request, "build_opener", return_value=pr_opener):
            pr_evidence = observation._read_exact_ready_pr_state(
                reservation_receipt=receipt,
                reviewer_target=target,
                reviewer_handoff_requirements=requirements,
            )
        assert pr_evidence["pull_request_author_user_id"] == AUTHOR_ID
        request, _timeout = pr_opener.requests[0]
        assert request.get_method() == "GET"
        assert request.full_url == receipt.pull_request_api_url
        lowered = {name.lower() for name in request.headers}
        assert "authorization" not in lowered
        assert "cookie" not in lowered

        self_review_opener = _FakeOpener(
            _FakeResponse(
                _pr_document(
                    receipt,
                    target,
                    requirements,
                    author_id=target.reviewer_user_id,
                )
            )
        )
        with patch.object(observation.urllib.request, "build_opener", return_value=self_review_opener):
            _reject(lambda: observation._read_exact_ready_pr_state(
                reservation_receipt=receipt,
                reviewer_target=target,
                reviewer_handoff_requirements=requirements,
            ))

        requested_opener = _FakeOpener(
            _FakeResponse(
                _pr_document(
                    receipt,
                    target,
                    requirements,
                    reviewers=[{"login": target.reviewer_login}],
                )
            )
        )
        with patch.object(observation.urllib.request, "build_opener", return_value=requested_opener):
            _reject(lambda: observation._read_exact_ready_pr_state(
                reservation_receipt=receipt,
                reviewer_target=target,
                reviewer_handoff_requirements=requirements,
            ))

        stale_opener = _FakeOpener(
            _FakeResponse(
                _pr_document(
                    receipt,
                    target,
                    requirements,
                    updated_at="2026-09-15T06:25:41Z",
                )
            )
        )
        with patch.object(observation.urllib.request, "build_opener", return_value=stale_opener):
            _reject(lambda: observation._read_exact_ready_pr_state(
                reservation_receipt=receipt,
                reviewer_target=target,
                reviewer_handoff_requirements=requirements,
            ))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(
            observation.PilotExactTaskPrReviewerIdentityStateObservation.__dataclass_fields__
        )
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["properties"]["reviewer_requestability_verified"]["const"] is False
        assert schema["properties"]["credentialed_reviewer_requestability_check_required"]["const"] is True
        assert schema["properties"]["reviewer_mutation_authorized"]["const"] is False
        assert schema["properties"]["reviewer_request_performed"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(inspect.signature(
            observation.observe_pilot_exact_task_pr_reviewer_identity_state
        ).parameters) == ("reviewer_request_reservation",)
        source = inspect.getsource(observation)
        for forbidden in (
            "request_pull_request_reviewers(",
            "add_review_to_pr(",
            "merge_pull_request(",
            "subprocess",
        ):
            assert forbidden not in source
        assert "reviewer_requestability_verified: bool = False" in source
        assert "reviewer_mutation_authorized: bool = False" in source

        from rsi_pilot_exact_task_pr_reviewer_request_credential_capability_contract import (
            run_contract as run_reviewer_request_credential_capability_contract,
        )
        run_reviewer_request_credential_capability_contract()
    finally:
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
