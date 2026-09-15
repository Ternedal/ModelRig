"""Adversarial contract for ADR-DC-064 exact GraphQL PR node identity."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_credential_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_node_identity as node_identity  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_state_observation as state  # noqa: E402
from rsi_pilot_exact_task_pr_ready_for_review_state_observation_contract import _fresh_reader, _material  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-ready-for-review-node-identity-v1.schema.json"
NODE_ID = "PR_kwDOTMQCit4A064"


def _reject(fn) -> None:
    try:
        fn()
    except (
        node_identity.PilotExactTaskPrReadyNodeIdentityError,
        capability.PilotExactTaskPrReadyCredentialCapabilityError,
        state.PilotExactTaskPrReadyStateObservationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-064 unexpectedly accepted unsafe node identity")


def _descriptor(path: Path) -> dict[str, str]:
    return {
        "broker_policy_sha256": hashlib.sha256(b"ready-policy-064").hexdigest(),
        "broker_executable_path": os.fspath(path),
        "broker_executable_path_sha256": hashlib.sha256(
            os.fsencode(os.path.abspath(os.fspath(path)))
        ).hexdigest(),
        "broker_executable_sha256": hashlib.sha256(b"ready-broker-064").hexdigest(),
        "broker_version": "1.0.0",
        "credential_protocol": "github-graphql-ready-for-review-broker-v1",
        "operation": "mark-pull-request-ready-for-review",
        "secret_source": "host-secret-store-only",
        "secret_transport": "broker-owned-https-only",
        "api_origin": "https://api.github.com/graphql",
    }


def _node_reader(*, ready_credential_capability, review_handoff_requirements):
    url = ready_credential_capability.pull_request_api_url
    return {
        "request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
        "response_body_sha256": hashlib.sha256(b"node-identity-064").hexdigest(),
        "response_etag_sha256": hashlib.sha256(b"etag-node-064").hexdigest(),
        "pull_request_node_id": NODE_ID,
        "pull_request_node_id_sha256": hashlib.sha256(NODE_ID.encode("utf-8")).hexdigest(),
        "observed_updated_at_utc": ready_credential_capability.fresh_observed_updated_at_utc,
    }


class _FakeResponse:
    def __init__(self, payload: bytes, *, status: int = 200, headers=None) -> None:
        self.status = status
        self.headers = headers or {"ETag": 'W/"node-064"'}
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


def _document(cap, requirements, *, node_id=NODE_ID, updated_at=None, head_sha=None):
    return {
        "number": cap.pull_request_number,
        "node_id": node_id,
        "url": cap.pull_request_api_url,
        "html_url": cap.pull_request_html_url,
        "state": "open",
        "closed_at": None,
        "merged_at": None,
        "draft": True,
        "title": requirements.pr_title,
        "body": requirements.pr_body,
        "maintainer_can_modify": False,
        "updated_at": cap.fresh_observed_updated_at_utc if updated_at is None else updated_at,
        "head": {
            "ref": cap.head_branch,
            "sha": cap.predicted_commit_sha if head_sha is None else head_sha,
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

    tx, requirements, identity, receipt, ledger_temp, cleanup = _material()
    broker_temp = TemporaryDirectory(prefix="rsi-pr-ready-node-064-")
    try:
        observation = state._observe_verified_pilot_exact_task_pr_ready_for_review_state(
            ready_for_review_reservation=receipt,
            reader=_fresh_reader,
            now_provider=lambda: "2026-09-15T06:24:50Z",
        )
        broker_path = Path(broker_temp.name) / "rsi-github-pr-ready-broker-v1"
        broker_path.write_bytes(b"ready-broker-064")
        cap = capability._materialize_verified_pilot_exact_task_pr_ready_credential_capability(
            ready_state_observation=observation,
            broker_descriptor=_descriptor(broker_path),
            now_provider=lambda: "2026-09-15T06:24:51Z",
        )
        assert cap.capability_authenticated is True

        result = node_identity._attest_verified_pilot_exact_task_pr_ready_node_identity(
            ready_credential_capability=cap,
            reader=_node_reader,
            now_provider=lambda: "2026-09-15T06:24:55Z",
        )
        assert result.identity_authenticated is True
        assert result.ready_credential_capability_sha256 == cap.sha256
        assert result.ready_state_observation_sha256 == observation.sha256
        assert result.ready_for_review_reservation_sha256 == receipt.sha256
        assert result.review_handoff_requirements_sha256 == requirements.sha256
        assert result.pr_create_transaction_sha256 == tx.sha256
        assert result.predicted_commit_sha == identity.predicted_commit_sha
        assert result.pull_request_number == tx.pull_request_number
        assert result.pull_request_node_id == NODE_ID
        assert result.pull_request_node_id_sha256 == hashlib.sha256(NODE_ID.encode("utf-8")).hexdigest()
        assert result.observed_updated_at_utc == observation.fresh_observed_updated_at_utc

        for field in (
            "credential_free_rest_read",
            "fixed_origin_rest_read",
            "redirects_forbidden",
            "response_bounded",
            "exact_pr_state_reverified",
            "graphql_pull_request_node_identity_verified",
            "graphql_ready_for_review_mutation_required",
            "ready_for_review_authorization_consumed",
            "ready_for_review_slot_reserved",
        ):
            assert getattr(result, field) is True
        for field in (
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

        reloaded = node_identity.PilotExactTaskPrReadyNodeIdentity.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.identity_authenticated is False

        reloaded_cap = capability.PilotExactTaskPrReadyCredentialCapability.from_mapping(
            cap.to_dict()
        )
        assert reloaded_cap.capability_authenticated is False
        _reject(lambda: node_identity._require_live_capability(reloaded_cap))

        def drift_reader(*, ready_credential_capability, review_handoff_requirements):
            evidence = dict(_node_reader(
                ready_credential_capability=ready_credential_capability,
                review_handoff_requirements=review_handoff_requirements,
            ))
            evidence["observed_updated_at_utc"] = "2026-09-15T06:23:51Z"
            return evidence

        _reject(lambda: node_identity._attest_verified_pilot_exact_task_pr_ready_node_identity(
            ready_credential_capability=cap,
            reader=drift_reader,
            now_provider=lambda: "2026-09-15T06:24:55Z",
        ))
        _reject(lambda: node_identity._attest_verified_pilot_exact_task_pr_ready_node_identity(
            ready_credential_capability=cap,
            reader=_node_reader,
            now_provider=lambda: "2026-09-15T06:25:52Z",
        ))

        payload = json.dumps(
            _document(cap, requirements),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        opener = _FakeOpener(_FakeResponse(payload))
        with patch("urllib.request.build_opener", return_value=opener):
            evidence = node_identity._read_exact_pr_node_identity(
                ready_credential_capability=cap,
                review_handoff_requirements=requirements,
            )
        assert evidence["pull_request_node_id"] == NODE_ID
        assert len(opener.requests) == 1
        request, timeout = opener.requests[0]
        assert request.get_method() == "GET"
        assert request.full_url == cap.pull_request_api_url
        assert timeout == node_identity.PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_TIMEOUT_SECONDS
        header_names = {name.lower() for name in request.headers}
        assert "authorization" not in header_names
        assert "cookie" not in header_names

        drift_payload = json.dumps(
            _document(cap, requirements, updated_at="2026-09-15T06:23:51Z"),
            separators=(",", ":"),
        ).encode("utf-8")
        with patch("urllib.request.build_opener", return_value=_FakeOpener(_FakeResponse(drift_payload))):
            _reject(lambda: node_identity._read_exact_pr_node_identity(
                ready_credential_capability=cap,
                review_handoff_requirements=requirements,
            ))
        head_payload = json.dumps(
            _document(cap, requirements, head_sha="f" * 40),
            separators=(",", ":"),
        ).encode("utf-8")
        with patch("urllib.request.build_opener", return_value=_FakeOpener(_FakeResponse(head_payload))):
            _reject(lambda: node_identity._read_exact_pr_node_identity(
                ready_credential_capability=cap,
                review_handoff_requirements=requirements,
            ))
        redirect = urllib.error.HTTPError(
            cap.pull_request_api_url,
            302,
            "redirect",
            {},
            None,
        )
        with patch("urllib.request.build_opener", return_value=_FakeOpener(redirect)):
            _reject(lambda: node_identity._read_exact_pr_node_identity(
                ready_credential_capability=cap,
                review_handoff_requirements=requirements,
            ))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        serialized = result.to_dict()
        assert set(schema["properties"]) == set(serialized)
        assert set(schema["required"]) == set(serialized)
        assert schema["properties"]["graphql_pull_request_node_identity_verified"]["const"] is True
        assert schema["properties"]["graphql_ready_for_review_mutation_required"]["const"] is True
        assert schema["properties"]["ready_for_review_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            node_identity.attest_pilot_exact_task_pr_ready_node_identity
        ).parameters
        assert tuple(public_parameters) == ("ready_credential_capability",)

        source = inspect.getsource(node_identity)
        assert "method=\"GET\"" in source
        assert "markPullRequestReadyForReview" not in source
        assert "subprocess" not in source
        assert "create_pull_request(" not in source
        assert "update_pull_request(" not in source
        assert "merge_pull_request(" not in source
        assert "ready_for_review_authorized: bool = False" in source
        assert "production_activation_authorized: bool = False" in source
    finally:
        broker_temp.cleanup()
        ledger_temp.cleanup()
        for temp in cleanup:
            temp.cleanup()


if __name__ == "__main__":
    run_contract()
