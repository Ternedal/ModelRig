"""Adversarial contract for ADR-DC-056 read-only PR-state observation."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import urllib.error
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
from kaliv_dev_control import improvement_pilot_exact_task_pr_state_observation as observation  # noqa: E402
from rsi_pilot_exact_task_pr_mutation_authorization_contract import (  # noqa: E402
    _human_authority,
    _live_remote_transaction,
)

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pr-state-observation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        observation.PilotExactTaskPrStateObservationError,
        reservation.PilotExactTaskPrMutationReservationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-056 unexpectedly accepted unsafe PR-state evidence")


def _reservation_material():
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
    ledger_temp = TemporaryDirectory(prefix="rsi-pr-state-observation-056-")
    with patch.object(pr_requirements, "_now_utc_seconds", return_value="2026-09-15T06:21:49Z"):
        requirements = pr_requirements.materialize_pilot_exact_task_pr_mutation_requirements(transaction)
    nonce = hashlib.sha256(b"pr-mutation-nonce-056").hexdigest()
    claim = auth.build_pilot_exact_task_pr_mutation_authorization(
        pr_mutation_requirements=requirements,
        authorization_id="exact-pr-mutation-authorization-056",
        pr_mutation_authorizer_actor_id=requirements.prior_remote_publication_authorizer_actor_id,
        authorized_at_utc="2026-09-15T06:22:00Z",
        expires_at_utc="2026-09-15T06:32:00Z",
        pr_mutation_nonce_sha256=nonce,
        notes=("observe exact draft PR state only",),
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
    ledger = reservation._PilotExactTaskPrMutationReservationLedger(Path(ledger_temp.name))
    receipt = reservation._reserve_verified_pilot_exact_task_pr_mutation(
        supplied_authorization_proof=supplied,
        fresh_authorization_proof=fresh,
        ledger=ledger,
        now_provider=lambda: "2026-09-15T06:23:20Z",
    )
    return (
        receipt,
        identity,
        requirements,
        ledger_temp,
        broker_temp,
        remote_reservation_temp,
        transaction_temp,
        source_reservation_temp,
        execution_temp,
        local_reservation_temp,
        executor_capability_temp,
        admission_ledger_temp,
        source_temp,
    )


class _FakeResponse:
    def __init__(self, payload: bytes, *, status: int = 200, headers=None) -> None:
        self.status = status
        self.headers = headers or {"ETag": 'W/"fixture-056"'}
        self._payload = payload

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
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def run_contract() -> None:
    if os.name == "nt":
        return

    material = _reservation_material()
    (
        receipt,
        identity,
        requirements,
        ledger_temp,
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
    try:
        assert receipt.reservation_authenticated is True
        calls = []
        def reader(*, head_branch):
            calls.append(head_branch)
            url = observation._query_url(head_branch=head_branch)
            payload = b"[]"
            etag = 'W/"fixture-056"'
            return {
                "request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
                "response_body_sha256": hashlib.sha256(payload).hexdigest(),
                "response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(),
                "open_pr_match_count": 0,
            }

        result = observation._observe_verified_pilot_exact_task_pr_state(
            pr_mutation_reservation=receipt,
            reader=reader,
            now_provider=lambda: "2026-09-15T06:23:30Z",
        )
        assert calls == [receipt.head_branch]
        assert result.observation_authenticated is True
        assert result.pr_mutation_reservation_sha256 == receipt.sha256
        assert result.pr_mutation_requirements_sha256 == requirements.sha256
        assert result.remote_write_transaction_sha256 == receipt.remote_write_transaction_sha256
        assert result.predicted_commit_sha == identity.predicted_commit_sha
        assert result.pr_plan_sha256 == requirements.pr_plan_sha256
        assert result.pr_mutation_nonce_sha256 == receipt.pr_mutation_nonce_sha256
        assert result.repository == "Ternedal/ModelRig"
        assert result.base_branch == "main"
        assert result.head_branch == requirements.head_branch
        assert result.open_pr_match_count == 0
        assert result.observed_at_utc == "2026-09-15T06:23:30Z"

        for field in (
            "reservation_revalidated",
            "fixed_origin_github_read",
            "credential_free_read",
            "redirects_forbidden",
            "response_bounded",
            "no_existing_open_pr_verified",
            "create_new_draft_pull_request_required",
            "fresh_pr_state_revalidation_before_create_required",
        ):
            assert getattr(result, field) is True
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
            assert getattr(result, field) is False

        reloaded = observation.PilotExactTaskPrStateObservation.from_mapping(result.to_dict())
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.observation_authenticated is False

        reloaded_receipt = reservation.PilotExactTaskPrMutationReservationReceipt.from_mapping(receipt.to_dict())
        assert reloaded_receipt.reservation_authenticated is False
        _reject(lambda: observation._require_live_reservation(reloaded_receipt))

        _reject(lambda: observation._observe_verified_pilot_exact_task_pr_state(
            pr_mutation_reservation=receipt,
            reader=lambda **_: {
                "request_url_sha256": "1" * 64,
                "response_body_sha256": "2" * 64,
                "response_etag_sha256": "3" * 64,
                "open_pr_match_count": 1,
            },
            now_provider=lambda: "2026-09-15T06:23:31Z",
        ))

        url = observation._query_url(head_branch=receipt.head_branch)
        assert url.startswith("https://api.github.com/repos/Ternedal/ModelRig/pulls?")
        assert "state=open" in url
        assert "base=main" in url
        assert "per_page=2" in url
        assert urllib_parse_quote(receipt.head_branch) in url

        fake = _FakeOpener(_FakeResponse(b"[]"))
        with patch.object(observation.urllib.request, "build_opener", return_value=fake):
            evidence = observation._read_public_open_pr_state(head_branch=receipt.head_branch)
        assert evidence["open_pr_match_count"] == 0
        assert len(fake.requests) == 1
        request, timeout = fake.requests[0]
        assert request.full_url == url
        assert request.get_method() == "GET"
        assert timeout == observation.PILOT_EXACT_TASK_PR_STATE_OBSERVATION_TIMEOUT_SECONDS
        lowered = {name.lower() for name in request.headers}
        assert "authorization" not in lowered
        assert "cookie" not in lowered

        fake_existing = _FakeOpener(_FakeResponse(b'[{"number":123}]'))
        with patch.object(observation.urllib.request, "build_opener", return_value=fake_existing):
            _reject(lambda: observation._read_public_open_pr_state(head_branch=receipt.head_branch))

        fake_paged = _FakeOpener(_FakeResponse(b"[]", headers={
            "ETag": 'W/"fixture-056"',
            "Link": '<https://api.github.com/next>; rel="next"',
        }))
        with patch.object(observation.urllib.request, "build_opener", return_value=fake_paged):
            _reject(lambda: observation._read_public_open_pr_state(head_branch=receipt.head_branch))

        fake_redirect = _FakeOpener(urllib.error.HTTPError(url, 302, "redirect", {}, None))
        with patch.object(observation.urllib.request, "build_opener", return_value=fake_redirect):
            _reject(lambda: observation._read_public_open_pr_state(head_branch=receipt.head_branch))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(result.to_dict())
        assert set(schema["required"]) == set(result.to_dict())
        assert schema["properties"]["open_pr_match_count"]["const"] == 0
        assert schema["properties"]["no_existing_open_pr_verified"]["const"] is True
        assert schema["properties"]["pull_request_create_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(observation.observe_pilot_exact_task_pr_state).parameters
        assert tuple(public_parameters) == ("pr_mutation_reservation",)
        source = inspect.getsource(observation)
        assert "create_pull_request(" not in source
        assert "update_pull_request(" not in source
        assert "mark_pull_request_ready_for_review(" not in source
        assert "request_pull_request_reviewers(" not in source
        assert "label_pr(" not in source
        assert "merge_pull_request(" not in source
        assert "Bearer " not in source
        assert "token=" not in source.lower()
        assert "method=\"GET\"" in source
        assert "_NoRedirectHandler" in source
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


def urllib_parse_quote(value: str) -> str:
    import urllib.parse
    return urllib.parse.quote_plus(f"Ternedal:{value}")


if __name__ == "__main__":
    run_contract()
