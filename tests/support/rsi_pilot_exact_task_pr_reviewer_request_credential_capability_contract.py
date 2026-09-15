"""Adversarial contract for ADR-DC-071 read-only reviewer requestability capability."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_identity_observation as identity  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_credential_capability as capability  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_reviewer_request_credential_capability_impl as impl  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_reviewer_request_credential_capability_production_boundary as production  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_identity_observation_contract import (  # noqa: E402
    _live_reservation,
    _reader as _identity_reader,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-request-credential-capability-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        capability.PilotExactTaskPrReviewerRequestCredentialCapabilityError,
        production.PilotExactTaskPrReviewerRequestCredentialCapabilityProductionBoundaryError,
        identity.PilotExactTaskPrReviewerIdentityObservationError,
        ValueError,
        TypeError,
        OSError,
    ):
        return
    raise AssertionError("ADR-DC-071 unexpectedly accepted unsafe credential capability")


def _live_identity():
    receipt, _target, _requirements, cleanup = _live_reservation()
    result = identity._observe_verified_pilot_exact_task_pr_reviewer_identity(
        reviewer_request_reservation=receipt,
        reader=_identity_reader,
        now_provider=lambda: "2026-09-15T06:25:33Z",
    )
    assert result.observation_authenticated is True
    assert result.reviewer_request_authorization_consumed is True
    assert result.reviewer_request_slot_reserved is True
    assert result.reviewer_requestability_observation_required is True
    return result, cleanup


def _descriptor(path: Path, *, broker_bytes: bytes = b"reviewer-requestability-broker-071"):
    absolute = Path(path).resolve()
    return {
        "broker_policy_sha256": hashlib.sha256(b"reviewer-requestability-policy-071").hexdigest(),
        "broker_executable_path": os.fspath(absolute),
        "broker_executable_path_sha256": hashlib.sha256(
            os.fsencode(os.path.abspath(os.fspath(absolute)))
        ).hexdigest(),
        "broker_executable_sha256": hashlib.sha256(broker_bytes).hexdigest(),
        "broker_version": "1.0.0",
        "credential_protocol": "github-rest-reviewer-requestability-broker-v1",
        "operation": "get-collaborator-permission",
        "secret_source": "host-secret-store-only",
        "secret_transport": "broker-owned-https-only",
        "api_origin": "https://api.github.com",
        "credential_account": "Ternedal",
    }


def _policy(*, broker_path: Path, broker_bytes: bytes) -> dict:
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
        "broker_executable_sha256": hashlib.sha256(broker_bytes).hexdigest(),
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

    identity_value, cleanup = _live_identity()
    descriptor_temp = TemporaryDirectory(prefix="rsi-reviewer-requestability-credential-071-")
    try:
        descriptor_path = Path(descriptor_temp.name) / "broker"
        descriptor = _descriptor(descriptor_path)
        result = (
            capability._materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability(
                reviewer_identity_observation=identity_value,
                broker_descriptor=descriptor,
                now_provider=lambda: "2026-09-15T06:25:34Z",
            )
        )
        assert result.capability_authenticated is True
        assert result.reviewer_identity_observation_sha256 == identity_value.sha256
        assert (
            result.reviewer_request_reservation_sha256
            == identity_value.reviewer_request_reservation_sha256
        )
        assert (
            result.reviewer_target_attestation_sha256
            == identity_value.reviewer_target_attestation_sha256
        )
        assert (
            result.reviewer_handoff_requirements_sha256
            == identity_value.reviewer_handoff_requirements_sha256
        )
        assert result.reviewer_target_policy_sha256 == identity_value.reviewer_target_policy_sha256
        assert result.reviewer_target_policy_epoch == identity_value.reviewer_target_policy_epoch
        assert result.reviewer_request_nonce_sha256 == identity_value.reviewer_request_nonce_sha256
        assert result.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == identity_value.pull_request_number
        assert result.pull_request_api_url == identity_value.pull_request_api_url
        assert result.pull_request_html_url == identity_value.pull_request_html_url
        assert result.pull_request_node_id_sha256 == identity_value.pull_request_node_id_sha256
        assert result.predicted_commit_sha == identity_value.predicted_commit_sha
        assert result.reviewer_login == identity_value.reviewer_login
        assert result.reviewer_user_id == identity_value.reviewer_user_id
        assert result.identity_observed_at_utc == identity_value.observed_at_utc
        assert result.broker_policy_sha256 == descriptor["broker_policy_sha256"]
        assert result.broker_executable_path_sha256 == descriptor["broker_executable_path_sha256"]
        assert result.broker_executable_sha256 == descriptor["broker_executable_sha256"]
        assert result.broker_version == "1.0.0"
        assert result.credential_protocol == "github-rest-reviewer-requestability-broker-v1"
        assert result.credential_operation == "get-collaborator-permission"
        assert result.secret_source == "host-secret-store-only"
        assert result.secret_transport == "broker-owned-https-only"
        assert result.api_origin == "https://api.github.com"
        assert result.credential_account_sha256 == hashlib.sha256(b"Ternedal").hexdigest()
        assert result.materialized_at_utc == "2026-09-15T06:25:34Z"

        for field in (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_verified",
            "exact_pr_state_reverified",
            "reviewer_requestability_observation_required",
            "credential_broker_host_pinned",
            "credential_broker_binary_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "collaborator_permission_read_required",
            "other_repository_reads_forbidden",
            "reviewer_write_forbidden",
            "pull_request_write_forbidden",
            "redirect_following_forbidden",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "post_request_readback_verification_required",
            "one_shot_reviewer_request_transaction_required",
            "team_reviewers_forbidden",
        ):
            assert getattr(result, field) is True
        for field in (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        live = capability._get_live_pr_reviewer_request_credential_capability_inputs(result)
        assert live is not None
        assert live["reviewer_identity_observation"] is identity_value
        assert live["credential_broker_descriptor"]["operation"] == (
            "get-collaborator-permission"
        )
        assert live["credential_broker_descriptor"]["credential_account"] == "Ternedal"

        reloaded = capability.PilotExactTaskPrReviewerRequestCredentialCapability.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.capability_authenticated is False

        replayed_identity = identity.PilotExactTaskPrReviewerIdentityObservation.from_mapping(
            identity_value.to_dict()
        )
        assert replayed_identity.observation_authenticated is False
        _reject(
            lambda: capability._materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability(
                reviewer_identity_observation=replayed_identity,
                broker_descriptor=descriptor,
                now_provider=lambda: "2026-09-15T06:25:34Z",
            )
        )

        wrong_operation = dict(descriptor)
        wrong_operation["operation"] = "request-pull-request-reviewer"
        _reject(lambda: capability._descriptor(wrong_operation))
        wrong_protocol = dict(descriptor)
        wrong_protocol["credential_protocol"] = "github-rest-reviewer-request-broker-v1"
        _reject(lambda: capability._descriptor(wrong_protocol))
        wrong_account = dict(descriptor)
        wrong_account["credential_account"] = "someone-else"
        _reject(lambda: capability._descriptor(wrong_account))
        wrong_origin = dict(descriptor)
        wrong_origin["api_origin"] = "https://example.com"
        _reject(lambda: capability._descriptor(wrong_origin))
        relative = dict(descriptor)
        relative["broker_executable_path"] = "relative/broker"
        relative["broker_executable_path_sha256"] = hashlib.sha256(
            b"relative/broker"
        ).hexdigest()
        _reject(lambda: capability._descriptor(relative))
        wrong_path_hash = dict(descriptor)
        wrong_path_hash["broker_executable_path_sha256"] = "1" * 64
        _reject(lambda: capability._descriptor(wrong_path_hash))

        with TemporaryDirectory(prefix="rsi-reviewer-requestability-production-071-") as tmp:
            root = Path(tmp)
            broker_path = root / "broker"
            policy_path = root / "policy.json"
            broker_bytes = b"reviewer-requestability-broker-production-071"
            broker_path.write_bytes(broker_bytes)
            policy = _policy(broker_path=broker_path, broker_bytes=broker_bytes)
            payload = production._canonical_bytes(policy)
            policy_path.write_bytes(payload)

            loaded = production._load_broker_descriptor_at(
                policy_path,
                broker_path,
                require_host_control=False,
            )
            assert loaded["broker_executable_sha256"] == hashlib.sha256(
                broker_bytes
            ).hexdigest()
            assert loaded["operation"] == "get-collaborator-permission"
            assert loaded["credential_protocol"] == "github-rest-reviewer-requestability-broker-v1"
            assert loaded["credential_account"] == "Ternedal"
            assert loaded["api_origin"] == "https://api.github.com"

            broker_path.write_bytes(broker_bytes + b"tamper")
            _reject(
                lambda: production._load_broker_descriptor_at(
                    policy_path,
                    broker_path,
                    require_host_control=False,
                )
            )
            broker_path.write_bytes(broker_bytes)
            policy_path.write_bytes(payload + b"\n")
            _reject(
                lambda: production._load_broker_descriptor_at(
                    policy_path,
                    broker_path,
                    require_host_control=False,
                )
            )

            write_policy = dict(policy)
            write_policy["reviewer_write_forbidden"] = False
            _reject(
                lambda: production._parse_policy(
                    production._canonical_bytes(write_policy),
                    broker_path=broker_path,
                )
            )
            other_read_policy = dict(policy)
            other_read_policy["other_repository_reads_forbidden"] = False
            _reject(
                lambda: production._parse_policy(
                    production._canonical_bytes(other_read_policy),
                    broker_path=broker_path,
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(
            capability.PilotExactTaskPrReviewerRequestCredentialCapability.__dataclass_fields__
        )
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["credential_operation"]["const"] == (
            "get-collaborator-permission"
        )
        assert schema["properties"]["reviewer_write_forbidden"]["const"] is True
        assert schema["properties"]["pull_request_write_forbidden"]["const"] is True
        assert schema["properties"]["other_repository_reads_forbidden"]["const"] is True
        assert schema["properties"]["reviewer_mutation_authorized"]["const"] is False
        assert schema["properties"]["reviewer_request_performed"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert list(
            inspect.signature(
                capability.materialize_pilot_exact_task_pr_reviewer_request_credential_capability
            ).parameters
        ) == ["reviewer_identity_observation"]

        source = inspect.getsource(impl)
        for forbidden in (
            "urllib.request",
            "requests.",
            "httpx.",
            "subprocess",
            "EnvironmentFileGitHubCredentialProvider",
            "KALIV_GITHUB_TOKEN_FILE",
            "GITHUB_TOKEN",
            "GH_TOKEN",
            "request_pull_request_reviewers(",
            "remove_pull_request_reviewers(",
            "merge_pull_request(",
            "mark_pull_request_ready_for_review(",
        ):
            assert forbidden not in source

        production_source = inspect.getsource(production)
        assert "subprocess" not in production_source
        assert "urllib.request" not in production_source
        assert "EnvironmentFileGitHubCredentialProvider" not in production_source
        assert "KALIV_GITHUB_TOKEN_FILE" not in production_source
        assert '"reviewer_write_forbidden": True' in production_source
        assert '"pull_request_write_forbidden": True' in production_source
        assert '"other_repository_reads_forbidden": True' in production_source
    finally:
        descriptor_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
