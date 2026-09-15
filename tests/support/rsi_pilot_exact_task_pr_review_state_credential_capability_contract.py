"""Adversarial contract for ADR-DC-077 review-state credential capability."""
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
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEVCONTROL_SRC):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_review_state_credential_capability as capability  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_review_state_credential_capability_impl as impl  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_review_state_credential_capability_production_boundary as production  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_attestation as attestation  # noqa: E402
import rsi_pilot_exact_task_pr_reviewer_request_attestation_contract as parent  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-review-state-credential-capability-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (
        capability.PilotExactTaskPrReviewStateCredentialCapabilityError,
        attestation.PilotExactTaskPrReviewerRequestAttestationError,
        production.PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError,
        ValueError, TypeError, OSError, AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-077 unexpectedly accepted unsafe review-state capability")


def _live_attestation():
    tx, ledger_temp, write_temp, parent_temp, cleanup = parent._live_transaction()
    reader, calls = parent._reader(tx)
    value = parent._attest(tx, reader)
    assert value.attestation_authenticated is True
    assert len(calls) == 2
    return value, ledger_temp, write_temp, parent_temp, cleanup


def _descriptor(broker_path: Path, *, policy_suffix: bytes = b"policy-077"):
    broker_bytes = b"#!/bin/sh\nexit 77\n"
    return {
        "broker_policy_sha256": hashlib.sha256(policy_suffix).hexdigest(),
        "broker_executable_path": os.fspath(broker_path),
        "broker_executable_path_sha256": hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(broker_path)))).hexdigest(),
        "broker_executable_sha256": hashlib.sha256(broker_bytes).hexdigest(),
        "broker_version": "1.0.0",
        "credential_protocol": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_PROTOCOL,
        "rest_operation": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION,
        "graphql_operation": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION,
        "secret_source": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_SOURCE,
        "secret_transport": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_TRANSPORT,
        "api_origin": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_API_ORIGIN,
        "graphql_endpoint": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_ENDPOINT,
        "credential_account": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_ACCOUNT,
        "reviews_path_template": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_REVIEWS_PATH_TEMPLATE,
        "graphql_query_sha256": hashlib.sha256(capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_QUERY.encode("utf-8")).hexdigest(),
    }


def _materialize(value, descriptor):
    return capability._materialize_verified_pilot_exact_task_pr_review_state_credential_capability(
        reviewer_request_attestation=value,
        broker_descriptor=descriptor,
        now_provider=lambda: "2026-09-15T06:26:00Z",
    )


def _policy(broker_path: Path, broker_sha256: str) -> dict:
    return {
        "schema": production.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "api_origin": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_API_ORIGIN,
        "graphql_endpoint": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_ENDPOINT,
        "repository": "Ternedal/ModelRig",
        "credential_account": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_ACCOUNT,
        "credential_protocol": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_PROTOCOL,
        "broker_version": "1.0.0",
        "broker_executable_path": os.fspath(broker_path),
        "broker_executable_sha256": broker_sha256,
        "secret_source": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_SOURCE,
        "secret_transport": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_TRANSPORT,
        "allowed_operations": [
            capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION,
            capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION,
        ],
        "reviews_path_template": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_REVIEWS_PATH_TEMPLATE,
        "graphql_query_sha256": hashlib.sha256(capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_QUERY.encode("utf-8")).hexdigest(),
        "reviews_read_only": True,
        "review_threads_read_only": True,
        "review_decision_read_only": True,
        "graphql_queries_only": True,
        "graphql_mutation_forbidden": True,
        "graphql_introspection_forbidden": True,
        "collaborator_permission_read_forbidden": True,
        "other_repository_reads_forbidden": True,
        "review_submission_write_forbidden": True,
        "review_dismissal_write_forbidden": True,
        "review_thread_mutation_forbidden": True,
        "reviewer_request_write_forbidden": True,
        "pull_request_create_forbidden": True,
        "pull_request_metadata_write_forbidden": True,
        "ready_for_review_write_forbidden": True,
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
    parent.run_contract()
    value, ledger_temp, write_temp, parent_temp, cleanup = _live_attestation()
    broker_temp = TemporaryDirectory(prefix="rsi-review-state-077-broker-")
    try:
        broker_path = Path(broker_temp.name) / "review-state-broker"
        broker_path.write_bytes(b"#!/bin/sh\nexit 77\n")
        broker_path.chmod(0o700)
        descriptor = _descriptor(broker_path)
        result = _materialize(value, descriptor)
        assert result.capability_authenticated is True
        assert result.reviewer_request_attestation_sha256 == value.sha256
        assert result.reviewer_write_transaction_sha256 == value.reviewer_write_transaction_sha256
        assert result.reviewer_request_nonce_sha256 == value.reviewer_request_nonce_sha256
        assert result.pull_request_number == value.pull_request_number
        assert result.predicted_commit_sha == value.predicted_commit_sha
        assert result.reviewer_login == value.reviewer_login
        assert result.reviewer_user_id == value.reviewer_user_id
        assert result.stable_post_request_response_body_sha256 == value.second_response_body_sha256
        assert result.stable_post_request_response_etag_sha256 == value.second_response_etag_sha256
        assert result.graphql_query_sha256 == descriptor["graphql_query_sha256"]

        for field in (
            "post_reviewer_request_attestation_verified", "reviewer_request_performed_verified",
            "exact_requested_reviewer_verified", "team_reviewers_absent_verified",
            "exact_pr_state_verified", "review_state_credential_capability_materialized",
            "read_broker_host_pinned", "read_broker_binary_verified",
            "credential_secret_not_loaded", "credential_broker_owns_https",
            "reviews_read_only", "review_threads_read_only", "review_decision_read_only",
            "graphql_queries_only", "graphql_mutations_forbidden",
            "graphql_introspection_forbidden", "redirect_following_forbidden",
            "collaborator_permission_read_forbidden", "other_repository_reads_forbidden",
            "review_submission_write_forbidden", "review_dismissal_write_forbidden",
            "review_thread_mutation_forbidden", "reviewer_request_write_forbidden",
            "pull_request_create_forbidden", "pull_request_metadata_write_forbidden",
            "ready_for_review_write_forbidden", "label_write_forbidden",
            "merge_write_forbidden", "repository_contents_write_forbidden",
            "administration_write_forbidden", "release_write_forbidden",
            "deployment_write_forbidden", "review_state_observation_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "credential_material_in_artifact", "credential_material_in_process_arguments",
            "credential_material_in_environment", "nonce_reusable",
            "reviewer_mutation_authorized", "review_submission_authorized",
            "review_thread_mutation_authorized", "merge_readiness_authorized",
            "label_mutation_authorized", "merge_authorized", "release_authorized",
            "deploy_authorized", "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        reloaded = capability.PilotExactTaskPrReviewStateCredentialCapability.from_mapping(result.to_dict())
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.capability_authenticated is False

        reloaded_source = attestation.PilotExactTaskPrReviewerRequestAttestation.from_mapping(value.to_dict())
        assert reloaded_source.attestation_authenticated is False
        _reject(lambda: capability._require_live_attestation(reloaded_source))

        bad_operation = dict(descriptor)
        bad_operation["rest_operation"] = "get-collaborator-permission"
        _reject(lambda: _materialize(value, bad_operation))
        bad_query = dict(descriptor)
        bad_query["graphql_query_sha256"] = hashlib.sha256(b"query Other{viewer{login}}").hexdigest()
        _reject(lambda: _materialize(value, bad_query))
        _reject(lambda: capability._materialize_verified_pilot_exact_task_pr_review_state_credential_capability(
            reviewer_request_attestation=value,
            broker_descriptor=descriptor,
            now_provider=lambda: "2026-09-15T06:25:44Z",
        ))

        policy = _policy(broker_path, descriptor["broker_executable_sha256"])
        payload = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        parsed = production._parse_policy(payload, broker_path=broker_path, implementation=impl)
        assert parsed["allowed_operations"] == [
            capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION,
            capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION,
        ]
        assert parsed["graphql_queries_only"] is True
        assert parsed["graphql_mutation_forbidden"] is True
        assert parsed["review_submission_write_forbidden"] is True
        assert parsed["merge_write_forbidden"] is True

        widened = dict(policy)
        widened["other_repository_reads_forbidden"] = False
        widened_payload = json.dumps(widened, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        _reject(lambda: production._parse_policy(widened_payload, broker_path=broker_path, implementation=impl))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(capability.PilotExactTaskPrReviewStateCredentialCapability.__dataclass_fields__)
        assert len(fields) == 90
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["review_state_credential_capability_materialized"]["const"] is True
        assert schema["properties"]["review_submission_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(inspect.signature(capability.materialize_pilot_exact_task_pr_review_state_credential_capability).parameters) == ("reviewer_request_attestation",)
        source = inspect.getsource(impl)
        for forbidden in (
            "import subprocess", "run_bounded_subprocess", "urllib.request",
            "import requests", "import httpx", "create_once_file", "Authorization",
        ):
            assert forbidden not in source
        assert "materialize_pilot_exact_task_pr_review_state_credential_capability" in source
        assert "review_state_observation_required" in source
    finally:
        broker_temp.cleanup()
        ledger_temp.cleanup()
        write_temp.cleanup()
        parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
