"""Adversarial contract for ADR-DC-070 exact reviewer identity observation."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_identity_observation as identity  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_reservation as reservation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_target_attestation as target_boundary  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_request_reservation_contract import _material  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-identity-observation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        identity.PilotExactTaskPrReviewerIdentityObservationError,
        reservation.PilotExactTaskPrReviewerRequestReservationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-070 unexpectedly accepted unsafe reviewer identity")


def _live_reservation():
    target, _claim, _signature, supplied, fresh, cleanup = _material()
    ledger_temp = TemporaryDirectory(prefix="rsi-reviewer-identity-070-")
    ledger = reservation._PilotExactTaskPrReviewerRequestReservationLedger(
        Path(ledger_temp.name)
    )
    receipt = reservation._reserve_verified_pilot_exact_task_pr_reviewer_request(
        supplied_authorization_proof=supplied,
        fresh_authorization_proof=fresh,
        ledger=ledger,
        now_provider=lambda: "2026-09-15T06:25:32Z",
    )
    assert receipt.reservation_authenticated is True
    target_inputs = target_boundary._get_live_pr_reviewer_target_attestation_inputs(
        target
    )
    requirements = target_inputs["reviewer_handoff_requirements"]
    return receipt, target, requirements, (ledger_temp, *cleanup)


def _reader(
    *,
    reviewer_request_reservation,
    reviewer_target_attestation,
    review_handoff_requirements,
):
    receipt = reviewer_request_reservation
    target = reviewer_target_attestation
    assert review_handoff_requirements.requirements_authenticated is True
    assert target.sha256 == receipt.reviewer_target_attestation_sha256
    user_url = f"https://api.github.com/users/{receipt.reviewer_login}"
    return {
        "reviewer_user_api_url": user_url,
        "reviewer_user_html_url": f"https://github.com/{receipt.reviewer_login}",
        "reviewer_user_node_id_sha256": hashlib.sha256(
            b"MDQ6VXNlcjI0NjgxMzU3OQ=="
        ).hexdigest(),
        "pull_request_author_login": "modelrig-author",
        "pull_request_author_user_id": 135792468,
        "user_request_url_sha256": hashlib.sha256(
            user_url.encode("utf-8")
        ).hexdigest(),
        "user_response_body_sha256": hashlib.sha256(
            b"reviewer-user-070"
        ).hexdigest(),
        "user_response_etag_sha256": hashlib.sha256(
            b"reviewer-user-etag-070"
        ).hexdigest(),
        "pr_request_url_sha256": hashlib.sha256(
            receipt.pull_request_api_url.encode("utf-8")
        ).hexdigest(),
        "pr_response_body_sha256": hashlib.sha256(
            b"reviewer-pr-070"
        ).hexdigest(),
        "pr_response_etag_sha256": hashlib.sha256(
            b"reviewer-pr-etag-070"
        ).hexdigest(),
    }


class _FakeResponse:
    def __init__(self, payload: bytes, *, etag: str) -> None:
        self.status = 200
        self.headers = {"ETag": etag}
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, maximum: int) -> bytes:
        return self._payload[:maximum]


class _FakeOpener:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("unexpected extra GitHub read")
        return self.responses.pop(0)


def _user_document(receipt):
    return {
        "login": receipt.reviewer_login,
        "id": receipt.reviewer_user_id,
        "node_id": "MDQ6VXNlcjI0NjgxMzU3OQ==",
        "type": "User",
        "url": f"https://api.github.com/users/{receipt.reviewer_login}",
        "html_url": f"https://github.com/{receipt.reviewer_login}",
    }


def _pr_document(
    receipt,
    target,
    requirements,
    *,
    author_login="modelrig-author",
    author_id=135792468,
    reviewers=None,
):
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
        "updated_at": target.ready_updated_at_utc,
        "user": {"login": author_login, "id": author_id},
        "requested_reviewers": [] if reviewers is None else reviewers,
        "requested_teams": [],
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
        result = identity._observe_verified_pilot_exact_task_pr_reviewer_identity(
            reviewer_request_reservation=receipt,
            reader=_reader,
            now_provider=lambda: "2026-09-15T06:25:33Z",
        )
        assert result.observation_authenticated is True
        assert result.reviewer_request_reservation_sha256 == receipt.sha256
        assert result.reviewer_target_attestation_sha256 == target.sha256
        assert result.reviewer_request_nonce_sha256 == receipt.reviewer_request_nonce_sha256
        assert result.reviewer_target_policy_sha256 == receipt.reviewer_target_policy_sha256
        assert result.reviewer_target_policy_epoch == 1
        assert result.reviewer_login == "modelrig-reviewer"
        assert result.reviewer_user_id == 246813579
        assert result.pull_request_author_login == "modelrig-author"
        assert result.pull_request_author_user_id == 135792468
        assert result.reserved_at_utc == "2026-09-15T06:25:32Z"
        assert result.observed_at_utc == "2026-09-15T06:25:33Z"

        for field in (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_verified",
            "pull_request_author_verified",
            "self_review_excluded",
            "no_requested_reviewers_verified",
            "exact_pr_state_reverified",
            "credential_free_reads",
            "redirects_forbidden",
            "response_bounded",
            "reviewer_requestability_observation_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
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

        reloaded = identity.PilotExactTaskPrReviewerIdentityObservation.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.observation_authenticated is False

        reloaded_reservation = (
            reservation.PilotExactTaskPrReviewerRequestReservationReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded_reservation.reservation_authenticated is False
        _reject(lambda: identity._require_live_reservation(reloaded_reservation))

        self_review = dict(
            _reader(
                reviewer_request_reservation=receipt,
                reviewer_target_attestation=target,
                review_handoff_requirements=requirements,
            )
        )
        self_review["pull_request_author_login"] = receipt.reviewer_login
        self_review["pull_request_author_user_id"] = receipt.reviewer_user_id
        _reject(
            lambda: identity._validate_reader_evidence(
                self_review,
                reservation=receipt,
            )
        )

        drift = dict(
            _reader(
                reviewer_request_reservation=receipt,
                reviewer_target_attestation=target,
                review_handoff_requirements=requirements,
            )
        )
        drift["pr_request_url_sha256"] = "1" * 64
        _reject(
            lambda: identity._validate_reader_evidence(
                drift,
                reservation=receipt,
            )
        )

        stale_reader_called = False

        def stale_reader(**_kwargs):
            nonlocal stale_reader_called
            stale_reader_called = True
            return {}

        _reject(
            lambda: identity._observe_verified_pilot_exact_task_pr_reviewer_identity(
                reviewer_request_reservation=receipt,
                reader=stale_reader,
                now_provider=lambda: "2026-09-15T06:26:33Z",
            )
        )
        assert stale_reader_called is False

        user_payload = json.dumps(
            _user_document(receipt),
            separators=(",", ":"),
        ).encode("utf-8")
        pr_payload = json.dumps(
            _pr_document(receipt, target, requirements),
            separators=(",", ":"),
        ).encode("utf-8")
        opener = _FakeOpener(
            [
                _FakeResponse(user_payload, etag='"user-070"'),
                _FakeResponse(pr_payload, etag='"pr-070"'),
            ]
        )
        with patch.object(
            identity.urllib.request,
            "build_opener",
            return_value=opener,
        ):
            evidence = identity._read_exact_reviewer_identity(
                reviewer_request_reservation=receipt,
                reviewer_target_attestation=target,
                review_handoff_requirements=requirements,
            )
        assert evidence["pull_request_author_login"] == "modelrig-author"
        assert len(opener.requests) == 2
        for request, timeout in opener.requests:
            assert request.get_method() == "GET"
            assert (
                timeout
                == identity.PILOT_EXACT_TASK_PR_REVIEWER_IDENTITY_TIMEOUT_SECONDS
            )
            lowered = {name.lower() for name in request.headers}
            assert "authorization" not in lowered
            assert "cookie" not in lowered

        self_payload = json.dumps(
            _pr_document(
                receipt,
                target,
                requirements,
                author_login=receipt.reviewer_login,
                author_id=receipt.reviewer_user_id,
            ),
            separators=(",", ":"),
        ).encode("utf-8")
        self_opener = _FakeOpener(
            [
                _FakeResponse(user_payload, etag='"user-070-self"'),
                _FakeResponse(self_payload, etag='"pr-070-self"'),
            ]
        )
        with patch.object(
            identity.urllib.request,
            "build_opener",
            return_value=self_opener,
        ):
            _reject(
                lambda: identity._read_exact_reviewer_identity(
                    reviewer_request_reservation=receipt,
                    reviewer_target_attestation=target,
                    review_handoff_requirements=requirements,
                )
            )

        requested_payload = json.dumps(
            _pr_document(
                receipt,
                target,
                requirements,
                reviewers=[{"login": "someone"}],
            ),
            separators=(",", ":"),
        ).encode("utf-8")
        requested_opener = _FakeOpener(
            [
                _FakeResponse(user_payload, etag='"user-070-requested"'),
                _FakeResponse(requested_payload, etag='"pr-070-requested"'),
            ]
        )
        with patch.object(
            identity.urllib.request,
            "build_opener",
            return_value=requested_opener,
        ):
            _reject(
                lambda: identity._read_exact_reviewer_identity(
                    reviewer_request_reservation=receipt,
                    reviewer_target_attestation=target,
                    review_handoff_requirements=requirements,
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(
            identity.PilotExactTaskPrReviewerIdentityObservation.__dataclass_fields__
        )
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["properties"]["reviewer_request_authorization_consumed"]["const"] is True
        assert schema["properties"]["reviewer_requestability_observation_required"]["const"] is True
        assert schema["properties"]["reviewer_mutation_authorized"]["const"] is False
        assert schema["properties"]["reviewer_request_performed"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert list(
            inspect.signature(
                identity.observe_pilot_exact_task_pr_reviewer_identity
            ).parameters
        ) == ["reviewer_request_reservation"]
        source = inspect.getsource(identity)
        assert 'method="GET"' in source
        assert 'method="POST"' not in source
        assert "/collaborators/" not in source
        for forbidden in (
            "request_pull_request_reviewers(",
            "add_review_to_pr(",
            "label_pr(",
            "merge_pull_request(",
            "subprocess",
        ):
            assert forbidden not in source
    finally:
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
