"""Adversarial contract for ADR-DC-071 reviewer-request credential capability."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_identity_state_observation as observation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_credential_capability as credential  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_reviewer_request_credential_capability_production_boundary as production  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_identity_state_observation_contract import (  # noqa: E402
    _live_reservation,
    _pr_evidence,
    _reviewer_evidence,
)

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-reviewer-request-credential-capability-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (
        credential.PilotExactTaskPrReviewerRequestCredentialCapabilityError,
        observation.PilotExactTaskPrReviewerIdentityStateObservationError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-071 unexpectedly accepted unsafe credential capability")


def _live_observation():
    receipt, _target, _requirements, cleanup = _live_reservation()
    result = observation._observe_verified_pilot_exact_task_pr_reviewer_identity_state(
        reviewer_request_reservation=receipt,
        reviewer_reader=_reviewer_evidence,
        pr_reader=_pr_evidence,
        now_provider=lambda: "2026-09-15T06:25:40Z",
    )
    assert result.observation_authenticated is True
    return result, cleanup


def _descriptor():
    broker_path = Path("/opt/modelrig/bin/rsi-github-reviewer-requestability-broker-v1")
    return {
        "broker_policy_sha256": hashlib.sha256(b"reviewer-request-policy-071").hexdigest(),
        "broker_executable_path": os.fspath(broker_path),
        "broker_executable_path_sha256": hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(broker_path)))).hexdigest(),
        "broker_executable_sha256": hashlib.sha256(b"reviewer-request-broker-071").hexdigest(),
        "broker_version": "1.0.0",
        "credential_protocol": credential.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_PROTOCOL,
        "operation": credential.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_OPERATION,
        "secret_source": credential.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_SOURCE,
        "secret_transport": credential.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_SECRET_TRANSPORT,
        "api_origin": credential.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_API_ORIGIN,
        "credential_account": credential.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_ACCOUNT,
    }


def _policy(*, broker_path: Path, broker_sha256: str):
    return {
        "schema": production.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "api_origin": "https://api.github.com",
        "repository": "Ternedal/ModelRig",
        "credential_account": "Ternedal",
        "operation": "get-collaborator-permission",
        "credential_protocol": "github-rest-reviewer-requestability-broker-v1",
        "broker_version": "1.0.0",
        "broker_executable_path": os.fspath(broker_path),
        "broker_executable_sha256": broker_sha256,
        "secret_source": "host-secret-store-only",
        "secret_transport": "broker-owned-https-only",
        "collaborator_permission_read_required": True,
        "other_repository_reads_forbidden": True,
        "reviewer_write_forbidden": True,
        "pull_request_write_forbidden": True,
        "label_write_forbidden": True,
        "merge_write_forbidden": True,
        "repository_contents_write_forbidden": True,
        "administration_write_forbidden": True,
        "release_write_forbidden": True,
        "deployment_write_forbidden": True,
        "redirect_following_forbidden": True,
    }


def run_contract() -> None:
    if os.name == "nt":
        return

    observed, cleanup = _live_observation()
    try:
        descriptor = _descriptor()
        result = credential._materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability(
            reviewer_identity_state_observation=observed,
            broker_descriptor=descriptor,
            now_provider=lambda: "2026-09-15T06:25:41Z",
        )
        assert result.capability_authenticated is True
        assert result.reviewer_identity_state_observation_sha256 == observed.sha256
        assert result.reviewer_request_reservation_sha256 == observed.reviewer_request_reservation_sha256
        assert result.reviewer_target_attestation_sha256 == observed.reviewer_target_attestation_sha256
        assert result.predicted_commit_sha == observed.predicted_commit_sha
        assert result.reviewer_login == observed.reviewer_login
        assert result.reviewer_user_id == observed.reviewer_user_id
        assert result.pull_request_number == observed.pull_request_number
        assert result.broker_policy_sha256 == descriptor["broker_policy_sha256"]
        assert result.credential_account_sha256 == hashlib.sha256(b"Ternedal").hexdigest()
        assert result.materialized_at_utc == "2026-09-15T06:25:41Z"

        for field in (
            "reviewer_request_authorization_consumed", "reviewer_request_slot_reserved",
            "reviewer_identity_verified", "ready_pr_state_freshly_revalidated",
            "no_requested_reviewers_verified", "credentialed_reviewer_requestability_check_required",
            "credential_broker_host_pinned", "credential_broker_binary_verified",
            "credential_account_host_pinned", "credential_secret_not_loaded",
            "credential_broker_owns_https", "exact_read_only_permission_operation_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required", "team_reviewers_forbidden",
        ):
            assert getattr(result, field) is True
        for field in (
            "reviewer_requestability_verified", "credential_material_in_artifact",
            "credential_material_in_process_arguments", "credential_material_in_environment",
            "reviewer_mutation_authorized", "reviewer_request_performed",
            "label_mutation_authorized", "merge_authorized", "release_authorized",
            "deploy_authorized", "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        reloaded = credential.PilotExactTaskPrReviewerRequestCredentialCapability.from_mapping(result.to_dict())
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.capability_authenticated is False

        reloaded_observation = observation.PilotExactTaskPrReviewerIdentityStateObservation.from_mapping(observed.to_dict())
        assert reloaded_observation.observation_authenticated is False
        _reject(lambda: credential._require_live_observation(reloaded_observation))

        wrong_account = dict(descriptor)
        wrong_account["credential_account"] = "other-account"
        _reject(lambda: credential._descriptor(wrong_account))
        wrong_path_hash = dict(descriptor)
        wrong_path_hash["broker_executable_path_sha256"] = "1" * 64
        _reject(lambda: credential._descriptor(wrong_path_hash))

        _reject(lambda: credential._materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability(
            reviewer_identity_state_observation=observed,
            broker_descriptor=descriptor,
            now_provider=lambda: "2026-09-15T06:26:41Z",
        ))

        broker_path = Path("/opt/modelrig/bin/rsi-github-reviewer-requestability-broker-v1")
        broker_sha256 = hashlib.sha256(b"broker-policy-test-071").hexdigest()
        policy = _policy(broker_path=broker_path, broker_sha256=broker_sha256)
        payload = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        parsed = production._parse_policy(payload, broker_path=broker_path)
        assert parsed["collaborator_permission_read_required"] is True
        assert parsed["other_repository_reads_forbidden"] is True
        assert parsed["reviewer_write_forbidden"] is True
        assert parsed["merge_write_forbidden"] is True
        assert parsed["credential_account"] == "Ternedal"

        weakened = dict(policy)
        weakened["reviewer_write_forbidden"] = False
        weakened_payload = json.dumps(weakened, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        _reject(lambda: production._parse_policy(weakened_payload, broker_path=broker_path))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(credential.PilotExactTaskPrReviewerRequestCredentialCapability.__dataclass_fields__)
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["properties"]["reviewer_requestability_verified"]["const"] is False
        assert schema["properties"]["credential_secret_not_loaded"]["const"] is True
        assert schema["properties"]["reviewer_mutation_authorized"]["const"] is False
        assert schema["properties"]["reviewer_request_performed"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(inspect.signature(credential.materialize_pilot_exact_task_pr_reviewer_request_credential_capability).parameters) == ("reviewer_identity_state_observation",)
        production_source = inspect.getsource(production)
        for forbidden in (
            "request_pull_request_reviewers(", "add_review_to_pr(",
            "merge_pull_request(", "bearer_token(", "urllib.request", "subprocess",
        ):
            assert forbidden not in production_source
        class_source = inspect.getsource(credential.PilotExactTaskPrReviewerRequestCredentialCapability)
        assert "credential_secret_not_loaded: bool = True" in class_source
        assert "reviewer_mutation_authorized: bool = False" in class_source
    finally:
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
