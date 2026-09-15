"""Adversarial contract for ADR-DC-066 reviewer handoff requirements."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_handoff_requirements as reviewer  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_transaction as transaction  # noqa: E402
from rsi_pilot_exact_task_pr_ready_for_review_node_identity_contract import _node_reader  # noqa: E402
from rsi_pilot_exact_task_pr_ready_for_review_transaction_contract import (  # noqa: E402
    READY_UPDATED,
    _broker_runner,
    _live_identity,
    _readback_reader,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-handoff-requirements-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        reviewer.PilotExactTaskPrReviewerHandoffRequirementsError,
        transaction.PilotExactTaskPrReadyTransactionError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-066 unexpectedly accepted unsafe reviewer handoff")


def _live_ready_transaction():
    (
        _tx,
        requirements,
        _source_identity,
        _receipt,
        _observation,
        cap,
        identity,
        broker_temp,
        reservation_ledger_temp,
        cleanup,
    ) = _live_identity()
    transaction_temp = TemporaryDirectory(prefix="rsi-pr-reviewer-handoff-ready-066-")
    ledger = transaction._PilotExactTaskPrReadyTransactionLedger(
        Path(transaction_temp.name)
    )
    calls = []
    times = iter(
        (
            "2026-09-15T06:24:56Z",
            "2026-09-15T06:24:57Z",
            "2026-09-15T06:24:58Z",
            "2026-09-15T06:24:59Z",
        )
    )
    result = transaction._execute_verified_pilot_exact_task_pr_ready_for_review(
        ready_node_identity=identity,
        ledger=ledger,
        state_reader=_node_reader,
        subprocess_runner=_broker_runner(
            identity=identity,
            capability_value=cap,
            calls=calls,
        ),
        readback_reader=_readback_reader,
        now_provider=lambda: next(times),
        broker_host_control_required=False,
    )
    assert len(calls) == 1
    cleanup_all = (
        transaction_temp,
        broker_temp,
        reservation_ledger_temp,
        *cleanup,
    )
    return result, requirements, cleanup_all


def _reader(*, ready_transaction, review_handoff_requirements):
    assert review_handoff_requirements.pr_title
    return {
        "request_url_sha256": hashlib.sha256(
            ready_transaction.pull_request_api_url.encode("utf-8")
        ).hexdigest(),
        "response_body_sha256": hashlib.sha256(b"reviewer-handoff-066").hexdigest(),
        "response_etag_sha256": hashlib.sha256(b"reviewer-etag-066").hexdigest(),
        "observed_updated_at_utc": READY_UPDATED,
        "requested_reviewer_count": 0,
        "requested_team_count": 0,
    }


class _FakeResponse:
    def __init__(self, payload: bytes, *, status: int = 200) -> None:
        self.status = status
        self.headers = {"ETag": 'W/"reviewer-handoff-066"'}
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
        return self.response


def _document(tx, requirements, *, reviewers=None, teams=None, draft=False, updated_at=READY_UPDATED):
    return {
        "number": tx.pull_request_number,
        "node_id": tx.pull_request_node_id,
        "url": tx.pull_request_api_url,
        "html_url": tx.pull_request_html_url,
        "state": "open",
        "closed_at": None,
        "merged_at": None,
        "draft": draft,
        "title": requirements.pr_title,
        "body": requirements.pr_body,
        "maintainer_can_modify": False,
        "updated_at": updated_at,
        "requested_reviewers": [] if reviewers is None else reviewers,
        "requested_teams": [] if teams is None else teams,
        "head": {
            "ref": tx.head_branch,
            "sha": tx.predicted_commit_sha,
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

    tx, requirements, cleanup = _live_ready_transaction()
    try:
        result = reviewer._materialize_verified_pilot_exact_task_pr_reviewer_handoff_requirements(
            ready_transaction=tx,
            reader=_reader,
            now_provider=lambda: "2026-09-15T06:25:10Z",
        )
        assert result.requirements_authenticated is True
        assert result.ready_transaction_sha256 == tx.sha256
        assert result.node_identity_sha256 == tx.node_identity_sha256
        assert result.ready_credential_capability_sha256 == tx.ready_credential_capability_sha256
        assert result.ready_state_observation_sha256 == tx.ready_state_observation_sha256
        assert result.ready_for_review_reservation_sha256 == tx.ready_for_review_reservation_sha256
        assert result.review_handoff_requirements_sha256 == requirements.sha256
        assert result.pr_create_transaction_sha256 == tx.pr_create_transaction_sha256
        assert result.predicted_commit_sha == tx.predicted_commit_sha
        assert result.review_handoff_plan_sha256 == tx.review_handoff_plan_sha256
        assert result.ready_for_review_nonce_sha256 == tx.ready_for_review_nonce_sha256
        assert result.required_reviewer_authorizer_actor_id == (
            requirements.required_ready_for_review_authorizer_actor_id
        )
        assert result.pull_request_number == tx.pull_request_number
        assert result.pull_request_node_id == tx.pull_request_node_id
        assert result.pull_request_node_id_sha256 == tx.pull_request_node_id_sha256
        assert result.ready_updated_at_utc == READY_UPDATED
        assert result.observed_updated_at_utc == READY_UPDATED
        assert result.materialized_at_utc == "2026-09-15T06:25:10Z"

        for field in (
            "post_ready_pr_reverified",
            "credential_free_read",
            "redirects_forbidden",
            "response_bounded",
            "pull_request_open_verified",
            "ready_state_verified",
            "exact_head_sha_verified",
            "exact_base_verified",
            "exact_metadata_verified",
            "no_requested_reviewers_verified",
            "reviewer_target_host_policy_required",
            "separate_human_reviewer_authorization_required",
            "one_shot_reviewer_request_nonce_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "ready_for_review_authorized",
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        plan = reviewer._handoff_plan(transaction=tx, requirements=requirements)
        assert plan["reviewer_selection_source"] == "host-pinned-reviewer-policy-only"
        assert plan["human_reviewer_request_authorization_required"] is True
        assert plan["one_shot_reviewer_request_nonce_required"] is True
        assert plan["expected_requested_reviewer_count"] == 0
        assert result.reviewer_handoff_plan_sha256 == reviewer._plan_sha256(plan)

        reloaded = reviewer.PilotExactTaskPrReviewerHandoffRequirements.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.requirements_authenticated is False

        reloaded_tx = transaction.PilotExactTaskPrReadyTransaction.from_mapping(
            tx.to_dict()
        )
        assert reloaded_tx.transaction_authenticated is False
        _reject(lambda: reviewer._require_live_transaction(reloaded_tx))

        drift = dict(_reader(ready_transaction=tx, review_handoff_requirements=requirements))
        drift["observed_updated_at_utc"] = "2026-09-15T06:25:01Z"
        _reject(lambda: reviewer._validate_reader_evidence(drift, transaction=tx))
        reviewer_drift = dict(_reader(ready_transaction=tx, review_handoff_requirements=requirements))
        reviewer_drift["requested_reviewer_count"] = 1
        _reject(lambda: reviewer._validate_reader_evidence(reviewer_drift, transaction=tx))

        document = _document(tx, requirements)
        payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
        opener = _FakeOpener(_FakeResponse(payload))
        with patch.object(reviewer.urllib.request, "build_opener", return_value=opener):
            evidence = reviewer._read_exact_ready_pr_for_reviewer_handoff(
                ready_transaction=tx,
                review_handoff_requirements=requirements,
            )
        assert evidence["requested_reviewer_count"] == 0
        assert evidence["requested_team_count"] == 0
        request, timeout = opener.requests[0]
        assert request.get_method() == "GET"
        assert request.full_url == tx.pull_request_api_url
        assert timeout == reviewer.PILOT_EXACT_TASK_PR_REVIEWER_HANDOFF_TIMEOUT_SECONDS
        lowered = {name.lower() for name in request.headers}
        assert "authorization" not in lowered
        assert "cookie" not in lowered

        requested_payload = json.dumps(
            _document(tx, requirements, reviewers=[{"login": "someone"}]),
            separators=(",", ":"),
        ).encode("utf-8")
        with patch.object(
            reviewer.urllib.request,
            "build_opener",
            return_value=_FakeOpener(_FakeResponse(requested_payload)),
        ):
            _reject(lambda: reviewer._read_exact_ready_pr_for_reviewer_handoff(
                ready_transaction=tx,
                review_handoff_requirements=requirements,
            ))

        draft_payload = json.dumps(
            _document(tx, requirements, draft=True),
            separators=(",", ":"),
        ).encode("utf-8")
        with patch.object(
            reviewer.urllib.request,
            "build_opener",
            return_value=_FakeOpener(_FakeResponse(draft_payload)),
        ):
            _reject(lambda: reviewer._read_exact_ready_pr_for_reviewer_handoff(
                ready_transaction=tx,
                review_handoff_requirements=requirements,
            ))

        serialized = result.to_dict()
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(serialized)
        assert set(schema["required"]) == set(serialized)
        assert schema["properties"]["no_requested_reviewers_verified"]["const"] is True
        assert schema["properties"]["reviewer_target_host_policy_required"]["const"] is True
        assert schema["properties"]["reviewer_mutation_authorized"]["const"] is False
        assert schema["properties"]["reviewer_request_performed"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            reviewer.materialize_pilot_exact_task_pr_reviewer_handoff_requirements
        ).parameters
        assert tuple(public_parameters) == ("ready_transaction",)

        source = inspect.getsource(reviewer)
        assert "request_pull_request_reviewers(" not in source
        assert "add_review_to_pr(" not in source
        assert "label_pr(" not in source
        assert "merge_pull_request(" not in source
        assert "method=\"GET\"" in source
        assert "reviewer_mutation_authorized: bool = False" in source
        assert "reviewer_request_performed: bool = False" in source
        assert "production_activation_authorized: bool = False" in source
    finally:
        for temp in cleanup:
            temp.cleanup()


if __name__ == "__main__":
    run_contract()
