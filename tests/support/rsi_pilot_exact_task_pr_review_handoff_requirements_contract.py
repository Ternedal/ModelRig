"""Adversarial contract for ADR-DC-059 review-handoff requirements."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_credential_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_create_transaction as transaction  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_handoff_requirements as handoff  # noqa: E402
from rsi_pilot_exact_task_pr_credential_capability_contract import _descriptor  # noqa: E402
from rsi_pilot_exact_task_pr_create_transaction_contract import (  # noqa: E402
    _broker_runner,
    _fresh_reader,
    _readback_reader,
)
from rsi_pilot_exact_task_pr_state_observation_contract import (  # noqa: E402
    _live_observation,
    _reservation_material,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-review-handoff-requirements-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        handoff.PilotExactTaskPrReviewHandoffRequirementsError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-059 unexpectedly accepted unsafe review-handoff state")


def _live_transaction():
    material = _reservation_material()
    (
        receipt,
        identity,
        requirements,
        pr_reservation_ledger_temp,
        remote_broker_temp,
        remote_reservation_temp,
        remote_transaction_temp,
        source_reservation_temp,
        execution_temp,
        local_reservation_temp,
        executor_capability_temp,
        admission_ledger_temp,
        source_temp,
    ) = material
    pr_broker_temp = TemporaryDirectory(prefix="rsi-pr-review-handoff-broker-059-")
    transaction_temp = TemporaryDirectory(prefix="rsi-pr-review-handoff-create-059-")
    supplied_observation = _live_observation(receipt)
    broker_path = Path(pr_broker_temp.name) / "rsi-github-pr-broker-v1"
    broker_path.write_bytes(b"broker-059")
    descriptor = _descriptor(broker_path)
    pr_capability = capability._materialize_verified_pilot_exact_task_pr_credential_capability(
        pr_state_observation=supplied_observation,
        broker_descriptor=descriptor,
        now_provider=lambda: "2026-09-15T06:23:40Z",
    )
    ledger = transaction._PilotExactTaskPrCreateTransactionLedger(
        Path(transaction_temp.name)
    )
    number = 1459
    times = iter(
        (
            "2026-09-15T06:23:41Z",
            "2026-09-15T06:23:42Z",
            "2026-09-15T06:23:43Z",
            "2026-09-15T06:23:44Z",
            "2026-09-15T06:23:45Z",
        )
    )
    result = transaction._execute_verified_pilot_exact_task_pr_create(
        pr_credential_capability=pr_capability,
        ledger=ledger,
        state_reader=_fresh_reader,
        subprocess_runner=_broker_runner(
            number=number,
            expected_capability=pr_capability,
            expected_requirements=requirements,
            calls=[],
        ),
        readback_reader=_readback_reader(number=number, calls=[]),
        now_provider=lambda: next(times),
        broker_host_control_required=False,
    )
    cleanup = (
        transaction_temp,
        pr_broker_temp,
        pr_reservation_ledger_temp,
        remote_broker_temp,
        remote_reservation_temp,
        remote_transaction_temp,
        source_reservation_temp,
        execution_temp,
        local_reservation_temp,
        executor_capability_temp,
        admission_ledger_temp,
        source_temp,
    )
    return result, requirements, identity, cleanup


def _reader(*, pr_create_transaction, pr_mutation_requirements):
    number = pr_create_transaction.pull_request_number
    url = f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{number}"
    return {
        "request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
        "response_body_sha256": hashlib.sha256(b"post-create-059").hexdigest(),
        "response_etag_sha256": hashlib.sha256(b"etag-059").hexdigest(),
        "observed_updated_at_utc": "2026-09-15T06:23:50Z",
        "pull_request_number": number,
        "api_url": pr_create_transaction.pull_request_api_url,
        "html_url": pr_create_transaction.pull_request_html_url,
    }


class _FakeResponse:
    def __init__(self, payload: bytes, *, status: int = 200, headers=None) -> None:
        self.status = status
        self.headers = headers or {"ETag": 'W/"review-handoff-059"'}
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


def _document(tx, requirements, *, draft=True, head_sha=None, title=None):
    number = tx.pull_request_number
    return {
        "number": number,
        "url": tx.pull_request_api_url,
        "html_url": tx.pull_request_html_url,
        "state": "open",
        "closed_at": None,
        "merged_at": None,
        "draft": draft,
        "title": requirements.pr_title if title is None else title,
        "body": requirements.pr_body,
        "maintainer_can_modify": False,
        "updated_at": "2026-09-15T06:23:50Z",
        "head": {
            "ref": tx.head_branch,
            "sha": tx.predicted_commit_sha if head_sha is None else head_sha,
            "repo": {"full_name": "Ternedal/ModelRig"},
        },
        "base": {
            "ref": "main",
            "repo": {"full_name": "Ternedal/ModelRig"},
        },
    }


def run_contract() -> None:
    if os.name == "nt":
        return

    tx, requirements, identity, cleanup = _live_transaction()
    try:
        assert tx.transaction_authenticated is True
        result = handoff._materialize_verified_pilot_exact_task_pr_review_handoff_requirements(
            pr_create_transaction=tx,
            reader=_reader,
            now_provider=lambda: "2026-09-15T06:24:00Z",
        )
        assert result.requirements_authenticated is True
        assert result.pr_create_transaction_sha256 == tx.sha256
        assert result.pr_credential_capability_sha256 == tx.pr_credential_capability_sha256
        assert result.pr_mutation_reservation_sha256 == tx.pr_mutation_reservation_sha256
        assert result.pr_mutation_requirements_sha256 == requirements.sha256
        assert result.remote_write_transaction_sha256 == tx.remote_write_transaction_sha256
        assert result.predicted_commit_sha == identity.predicted_commit_sha
        assert result.pr_plan_sha256 == requirements.pr_plan_sha256
        assert result.pr_mutation_nonce_sha256 == tx.pr_mutation_nonce_sha256
        assert result.required_ready_for_review_authorizer_actor_id == (
            requirements.prior_remote_publication_authorizer_actor_id
        )
        assert result.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == 1459
        assert result.base_branch == "main"
        assert result.head_branch == requirements.head_branch
        assert result.pr_title == requirements.pr_title
        assert result.pr_body == requirements.pr_body
        assert result.observed_updated_at_utc == "2026-09-15T06:23:50Z"
        assert result.materialized_at_utc == "2026-09-15T06:24:00Z"

        plan = handoff._handoff_plan(
            transaction=tx,
            requirements=requirements,
            evidence=_reader(
                pr_create_transaction=tx,
                pr_mutation_requirements=requirements,
            ),
        )
        assert plan["operation"] == "mark-pull-request-ready-for-review"
        assert plan["pull_request_number"] == tx.pull_request_number
        assert plan["head_sha"] == tx.predicted_commit_sha
        assert plan["expected_draft"] is True
        assert plan["expected_maintainer_can_modify"] is False
        assert result.review_handoff_plan_sha256 == handoff._plan_sha256(plan)

        for field in (
            "post_create_pr_reverified",
            "credential_free_read",
            "redirects_forbidden",
            "response_bounded",
            "pull_request_open_verified",
            "draft_state_verified",
            "exact_head_sha_verified",
            "exact_base_verified",
            "exact_metadata_verified",
            "ready_for_review_handoff_required",
            "separate_human_ready_for_review_authorization_required",
            "one_shot_ready_for_review_nonce_required",
            "fresh_pr_state_revalidation_before_ready_required",
            "reviewer_mutation_separate_authority_required",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "maintainer_can_modify",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "ready_for_review_authorization_consumed",
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

        serialized = result.to_dict()
        reloaded = handoff.PilotExactTaskPrReviewHandoffRequirements.from_mapping(serialized)
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.requirements_authenticated is False

        reloaded_tx = transaction.PilotExactTaskPrCreateTransaction.from_mapping(tx.to_dict())
        assert reloaded_tx.transaction_authenticated is False
        _reject(lambda: handoff._require_live_transaction(reloaded_tx))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(serialized)
        assert set(schema["required"]) == set(serialized)
        assert schema["properties"]["post_create_pr_reverified"]["const"] is True
        assert schema["properties"]["ready_for_review_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        payload = json.dumps(
            _document(tx, requirements),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        fake = _FakeOpener(_FakeResponse(payload))
        with patch.object(handoff.urllib.request, "build_opener", return_value=fake):
            evidence = handoff._read_exact_draft_pr_state(
                pr_create_transaction=tx,
                pr_mutation_requirements=requirements,
            )
        assert evidence["pull_request_number"] == tx.pull_request_number
        assert evidence["observed_updated_at_utc"] == "2026-09-15T06:23:50Z"
        assert len(fake.requests) == 1
        request, timeout = fake.requests[0]
        assert request.get_method() == "GET"
        assert request.full_url == tx.pull_request_api_url
        assert timeout == handoff.PILOT_EXACT_TASK_PR_REVIEW_HANDOFF_TIMEOUT_SECONDS
        lowered = {name.lower() for name in request.headers}
        assert "authorization" not in lowered
        assert "cookie" not in lowered

        ready_payload = json.dumps(
            _document(tx, requirements, draft=False),
            separators=(",", ":"),
        ).encode("utf-8")
        with patch.object(
            handoff.urllib.request,
            "build_opener",
            return_value=_FakeOpener(_FakeResponse(ready_payload)),
        ):
            _reject(lambda: handoff._read_exact_draft_pr_state(
                pr_create_transaction=tx,
                pr_mutation_requirements=requirements,
            ))

        drift_payload = json.dumps(
            _document(tx, requirements, head_sha="f" * 40),
            separators=(",", ":"),
        ).encode("utf-8")
        with patch.object(
            handoff.urllib.request,
            "build_opener",
            return_value=_FakeOpener(_FakeResponse(drift_payload)),
        ):
            _reject(lambda: handoff._read_exact_draft_pr_state(
                pr_create_transaction=tx,
                pr_mutation_requirements=requirements,
            ))

        title_payload = json.dumps(
            _document(tx, requirements, title="drifted title"),
            separators=(",", ":"),
        ).encode("utf-8")
        with patch.object(
            handoff.urllib.request,
            "build_opener",
            return_value=_FakeOpener(_FakeResponse(title_payload)),
        ):
            _reject(lambda: handoff._read_exact_draft_pr_state(
                pr_create_transaction=tx,
                pr_mutation_requirements=requirements,
            ))

        redirect = urllib.error.HTTPError(
            tx.pull_request_api_url,
            302,
            "redirect",
            {},
            None,
        )
        with patch.object(
            handoff.urllib.request,
            "build_opener",
            return_value=_FakeOpener(redirect),
        ):
            _reject(lambda: handoff._read_exact_draft_pr_state(
                pr_create_transaction=tx,
                pr_mutation_requirements=requirements,
            ))

        _reject(lambda: handoff._materialize_verified_pilot_exact_task_pr_review_handoff_requirements(
            pr_create_transaction=tx,
            reader=lambda **_: {
                **_reader(
                    pr_create_transaction=tx,
                    pr_mutation_requirements=requirements,
                ),
                "pull_request_number": tx.pull_request_number + 1,
            },
            now_provider=lambda: "2026-09-15T06:24:00Z",
        ))
        _reject(lambda: handoff._materialize_verified_pilot_exact_task_pr_review_handoff_requirements(
            pr_create_transaction=tx,
            reader=_reader,
            now_provider=lambda: "2026-09-15T06:23:49Z",
        ))

        public_parameters = inspect.signature(
            handoff.materialize_pilot_exact_task_pr_review_handoff_requirements
        ).parameters
        assert tuple(public_parameters) == ("pr_create_transaction",)
        source = inspect.getsource(handoff)
        assert 'method="GET"' in source
        assert "_NoRedirectHandler" in source
        assert "create_pull_request(" not in source
        assert "update_pull_request(" not in source
        assert "mark_pull_request_ready_for_review(" not in source
        assert "request_pull_request_reviewers(" not in source
        assert "merge_pull_request(" not in source
        assert "Bearer " not in source
        assert "Authorization" not in source
        assert "ready_for_review_authorized: bool = False" in source
        assert "production_activation_authorized: bool = False" in source
    finally:
        for temp in cleanup:
            temp.cleanup()


if __name__ == "__main__":
    run_contract()
