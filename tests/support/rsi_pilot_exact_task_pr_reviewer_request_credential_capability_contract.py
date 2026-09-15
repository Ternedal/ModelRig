"""Adversarial contract for ADR-DC-071 reviewer-request credential capability."""
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

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pr_reviewer_identity_state_observation as observation,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pr_reviewer_request_credential_capability as capability,
)
from kaliv_dev_control import (  # noqa: E402
    _improvement_pilot_exact_task_pr_reviewer_request_credential_capability_impl
    as impl,
)
from kaliv_dev_control import (  # noqa: E402
    _improvement_pilot_exact_task_pr_reviewer_request_credential_capability_production_boundary
    as production,
)
from rsi_pilot_exact_task_pr_reviewer_identity_state_observation_contract import (  # noqa: E402
    _live_reservation,
    _pr_evidence,
    _reviewer_evidence,
)

CAPABILITY_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-request-credential-capability-v1.schema.json"
)
POLICY_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-request-credential-broker-policy-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        capability.PilotExactTaskPrReviewerRequestCredentialCapabilityError,
        production.PilotExactTaskPrReviewerRequestCredentialCapabilityProductionBoundaryError,
        observation.PilotExactTaskPrReviewerIdentityStateObservationError,
        ValueError,
        TypeError,
        OSError,
    ):
        return
    raise AssertionError("ADR-DC-071 unexpectedly accepted unsafe credential capability")


def _live_observation():
    receipt, target, requirements, cleanup = _live_reservation()
    result = observation._observe_verified_pilot_exact_task_pr_reviewer_identity_state(
        reviewer_request_reservation=receipt,
        reviewer_reader=_reviewer_evidence,
        pr_reader=_pr_evidence,
        now_provider=lambda: "2026-09-15T06:25:40Z",
    )
    assert result.observation_authenticated is True
    return result, cleanup


def _descriptor(path: Path, *, operation_set=None):
    payload = path.read_bytes()
    return {
        "broker_policy_sha256": hashlib.sha256(b"reviewer-policy-071").hexdigest(),
        "broker_executable_path": os.fspath(path),
        "broker_executable_path_sha256": hashlib.sha256(
            os.fsencode(os.path.abspath(os.fspath(path)))
        ).hexdigest(),
        "broker_executable_sha256": hashlib.sha256(payload).hexdigest(),
        "broker_version": "1.0.0",
        "credential_protocol": "github-rest-reviewer-request-broker-v1",
        "operation_set": (
            "check-reviewer-requestability+request-exact-reviewer"
            if operation_set is None
            else operation_set
        ),
        "secret_source": "host-secret-store-only",
        "secret_transport": "broker-owned-https-only",
        "api_origin": "https://api.github.com",
    }


def _policy(path: Path, broker_sha256: str) -> dict:
    return {
        "schema": production.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "api_origin": "https://api.github.com",
        "repository": "Ternedal/ModelRig",
        "operation_set": "check-reviewer-requestability+request-exact-reviewer",
        "credential_protocol": "github-rest-reviewer-request-broker-v1",
        "broker_version": "1.0.0",
        "broker_executable_path": os.fspath(path),
        "broker_executable_sha256": broker_sha256,
        "secret_source": "host-secret-store-only",
        "secret_transport": "broker-owned-https-only",
        "reviewer_requestability_read_required": True,
        "reviewer_request_write_required": True,
        "team_reviewer_write_forbidden": True,
        "self_review_forbidden": True,
        "pull_request_create_write_forbidden": True,
        "pull_request_metadata_write_forbidden": True,
        "ready_for_review_write_forbidden": True,
        "label_write_forbidden": True,
        "merge_write_forbidden": True,
        "repository_contents_write_forbidden": True,
        "administration_write_forbidden": True,
        "release_write_forbidden": True,
    }


def run_contract() -> None:
    if os.name == "nt":
        return

    state, cleanup = _live_observation()
    broker_temp = TemporaryDirectory(prefix="rsi-reviewer-credential-071-")
    try:
        broker_path = Path(broker_temp.name) / "reviewer-broker"
        broker_path.write_bytes(b"#!/bin/sh\nexit 0\n")
        broker_path.chmod(0o700)
        descriptor = _descriptor(broker_path)

        result = capability._materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability(
            reviewer_identity_state_observation=state,
            broker_descriptor=descriptor,
            now_provider=lambda: "2026-09-15T06:25:41Z",
        )
        assert result.capability_authenticated is True
        assert result.reviewer_identity_state_observation_sha256 == state.sha256
        assert result.reviewer_request_reservation_sha256 == state.reviewer_request_reservation_sha256
        assert result.reviewer_target_attestation_sha256 == state.reviewer_target_attestation_sha256
        assert result.ready_transaction_sha256 == state.ready_transaction_sha256
        assert result.predicted_commit_sha == state.predicted_commit_sha
        assert result.reviewer_target_policy_sha256 == state.reviewer_target_policy_sha256
        assert result.reviewer_target_policy_epoch == state.reviewer_target_policy_epoch
        assert result.reviewer_request_nonce_sha256 == state.reviewer_request_nonce_sha256
        assert result.reviewer_login == state.reviewer_login
        assert result.reviewer_user_id == state.reviewer_user_id
        assert result.reviewer_node_id_sha256 == state.reviewer_node_id_sha256
        assert result.pull_request_author_user_id == state.pull_request_author_user_id
        assert result.broker_policy_sha256 == descriptor["broker_policy_sha256"]
        assert result.broker_executable_path_sha256 == descriptor["broker_executable_path_sha256"]
        assert result.broker_executable_sha256 == descriptor["broker_executable_sha256"]
        assert result.credential_protocol == "github-rest-reviewer-request-broker-v1"
        assert result.credential_operation_set == "check-reviewer-requestability+request-exact-reviewer"
        assert result.materialized_at_utc == "2026-09-15T06:25:41Z"

        for field in (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_public_identity_verified",
            "reviewer_not_pr_author_verified",
            "fresh_exact_pr_state_observed",
            "no_requested_reviewers_verified",
            "credential_broker_host_pinned",
            "credential_broker_binary_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "credentialed_requestability_check_required",
            "one_shot_reviewer_request_transaction_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "post_reviewer_request_readback_required",
            "team_reviewers_forbidden",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
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

        serialized = result.to_dict()
        assert os.fspath(broker_path) not in result.canonical_json()
        reloaded = capability.PilotExactTaskPrReviewerRequestCredentialCapability.from_mapping(
            serialized
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.capability_authenticated is False

        reloaded_state = observation.PilotExactTaskPrReviewerIdentityStateObservation.from_mapping(
            state.to_dict()
        )
        assert reloaded_state.observation_authenticated is False
        _reject(lambda: capability._require_live_observation(reloaded_state))
        _reject(lambda: capability._materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability(
            reviewer_identity_state_observation=state,
            broker_descriptor=_descriptor(
                broker_path,
                operation_set="request-exact-reviewer",
            ),
            now_provider=lambda: "2026-09-15T06:25:41Z",
        ))

        policy_path = Path(broker_temp.name) / "policy.json"
        policy = _policy(broker_path, hashlib.sha256(broker_path.read_bytes()).hexdigest())
        policy_path.write_bytes(production._canonical_bytes(policy))
        loaded = production._load_broker_descriptor_at(
            policy_path,
            broker_path,
            require_host_control=False,
        )
        assert loaded["broker_executable_sha256"] == result.broker_executable_sha256
        assert loaded["operation_set"] == result.credential_operation_set

        policy_path.write_bytes(production._canonical_bytes({
            **policy,
            "merge_write_forbidden": False,
        }))
        _reject(lambda: production._load_broker_descriptor_at(
            policy_path,
            broker_path,
            require_host_control=False,
        ))

        policy_path.write_bytes(production._canonical_bytes(policy))
        broker_path.chmod(0o600)
        _reject(lambda: production._load_broker_descriptor_at(
            policy_path,
            broker_path,
            require_host_control=False,
        ))
        broker_path.chmod(0o700)

        capability_schema = json.loads(CAPABILITY_SCHEMA.read_text(encoding="utf-8"))
        policy_schema = json.loads(POLICY_SCHEMA.read_text(encoding="utf-8"))
        assert set(capability_schema["properties"]) == set(
            capability.PilotExactTaskPrReviewerRequestCredentialCapability.__dataclass_fields__
        )
        assert set(capability_schema["required"]) == set(capability_schema["properties"])
        assert set(policy_schema["properties"]) == production._POLICY_FIELDS
        assert set(policy_schema["required"]) == set(policy_schema["properties"])
        assert capability_schema["properties"]["reviewer_requestability_verified"]["const"] is False
        assert capability_schema["properties"]["reviewer_mutation_authorized"]["const"] is False
        assert capability_schema["properties"]["production_activation_authorized"]["const"] is False

        assert list(inspect.signature(
            capability.materialize_pilot_exact_task_pr_reviewer_request_credential_capability
        ).parameters) == ["reviewer_identity_state_observation"]
        source = inspect.getsource(impl) + inspect.getsource(production)
        for forbidden in (
            "urllib.request",
            "requests.",
            "subprocess",
            "request_pull_request_reviewers(",
            "mark_pull_request_ready_for_review(",
            "merge_pull_request(",
        ):
            assert forbidden not in source

        from rsi_pilot_exact_task_pr_reviewer_requestability_preflight_contract import (
            run_contract as run_reviewer_requestability_preflight_contract,
        )
        run_reviewer_requestability_preflight_contract()
    finally:
        broker_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
