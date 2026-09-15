"""Adversarial contract for ADR-DC-063 ready-for-review credential capability."""
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

from kaliv_dev_control import _improvement_pilot_exact_task_pr_ready_for_review_credential_capability_impl as impl  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_ready_for_review_credential_capability_production_boundary as production  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_credential_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_state_observation as state  # noqa: E402
from rsi_pilot_exact_task_pr_ready_for_review_state_observation_contract import _fresh_reader, _material  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-ready-for-review-credential-capability-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (
        capability.PilotExactTaskPrReadyCredentialCapabilityError,
        production.PilotExactTaskPrReadyCredentialCapabilityProductionBoundaryError,
        state.PilotExactTaskPrReadyStateObservationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-063 unexpectedly accepted unsafe credential authority")


def _canonical(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _policy(broker_path: Path, broker_sha256: str) -> dict:
    return {
        "schema": production.PILOT_EXACT_TASK_PR_READY_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "api_origin": "https://api.github.com/graphql",
        "repository": "Ternedal/ModelRig",
        "operation": "mark-pull-request-ready-for-review",
        "credential_protocol": "github-graphql-ready-for-review-broker-v1",
        "broker_version": "1.0.0",
        "broker_executable_path": os.fspath(broker_path),
        "broker_executable_sha256": broker_sha256,
        "secret_source": "host-secret-store-only",
        "secret_transport": "broker-owned-https-only",
        "ready_for_review_write_required": True,
        "pull_request_create_write_forbidden": True,
        "pull_request_metadata_write_forbidden": True,
        "reviewer_write_forbidden": True,
        "label_write_forbidden": True,
        "merge_write_forbidden": True,
        "repository_contents_write_forbidden": True,
        "administration_write_forbidden": True,
        "release_write_forbidden": True,
    }


def run_contract() -> None:
    if os.name == "nt":
        return

    tx, requirements, identity, receipt, ledger_temp, cleanup = _material()
    broker_temp = TemporaryDirectory(prefix="rsi-pr-ready-capability-063-")
    try:
        observation = state._observe_verified_pilot_exact_task_pr_ready_for_review_state(
            ready_for_review_reservation=receipt,
            reader=_fresh_reader,
            now_provider=lambda: "2026-09-15T06:24:50Z",
        )
        assert observation.observation_authenticated is True

        root = Path(broker_temp.name)
        broker_path = root / "rsi-github-pr-ready-broker-v1"
        broker_bytes = b"broker-063-ready-for-review-only"
        broker_path.write_bytes(broker_bytes)
        broker_sha256 = hashlib.sha256(broker_bytes).hexdigest()
        policy_path = root / "policy.json"
        policy = _policy(broker_path, broker_sha256)
        policy_path.write_bytes(_canonical(policy))

        descriptor = production._load_broker_descriptor_at(
            policy_path,
            broker_path,
            require_host_control=False,
        )
        assert descriptor["operation"] == "mark-pull-request-ready-for-review"
        assert descriptor["credential_protocol"] == "github-graphql-ready-for-review-broker-v1"
        assert descriptor["api_origin"] == "https://api.github.com/graphql"
        assert descriptor["broker_executable_sha256"] == broker_sha256

        result = capability._materialize_verified_pilot_exact_task_pr_ready_credential_capability(
            ready_state_observation=observation,
            broker_descriptor=descriptor,
            now_provider=lambda: "2026-09-15T06:24:51Z",
        )
        assert result.capability_authenticated is True
        assert result.ready_state_observation_sha256 == observation.sha256
        assert result.ready_for_review_reservation_sha256 == receipt.sha256
        assert result.review_handoff_requirements_sha256 == requirements.sha256
        assert result.pr_create_transaction_sha256 == tx.sha256
        assert result.predicted_commit_sha == identity.predicted_commit_sha
        assert result.pull_request_number == tx.pull_request_number
        assert result.repository == "Ternedal/ModelRig"
        assert result.base_branch == "main"
        assert result.head_branch == tx.head_branch
        assert result.ready_for_review_nonce_sha256 == receipt.ready_for_review_nonce_sha256
        assert result.signed_observed_updated_at_utc == observation.signed_observed_updated_at_utc
        assert result.fresh_observed_updated_at_utc == observation.fresh_observed_updated_at_utc
        assert result.credential_operation == "mark-pull-request-ready-for-review"
        assert result.credential_protocol == "github-graphql-ready-for-review-broker-v1"
        assert result.api_origin == "https://api.github.com/graphql"
        assert result.credential_secret_not_loaded is True
        assert result.credential_broker_owns_https is True

        for field in (
            "ready_for_review_authorization_consumed",
            "ready_for_review_slot_reserved",
            "fresh_exact_pr_state_observed",
            "signed_updated_at_still_current",
            "credential_broker_host_pinned",
            "credential_broker_binary_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "one_shot_ready_for_review_transaction_required",
            "fresh_pr_state_revalidation_before_ready_required",
            "post_ready_readback_verification_required",
            "reviewer_mutation_separate_authority_required",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
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
        assert "broker_executable_path" not in serialized
        assert os.fspath(broker_path) not in result.canonical_json()
        reloaded = capability.PilotExactTaskPrReadyCredentialCapability.from_mapping(serialized)
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.capability_authenticated is False

        reloaded_observation = state.PilotExactTaskPrReadyStateObservation.from_mapping(
            observation.to_dict()
        )
        assert reloaded_observation.observation_authenticated is False
        _reject(lambda: capability._materialize_verified_pilot_exact_task_pr_ready_credential_capability(
            ready_state_observation=reloaded_observation,
            broker_descriptor=descriptor,
            now_provider=lambda: "2026-09-15T06:24:51Z",
        ))

        wrong_descriptor = dict(descriptor)
        wrong_descriptor["operation"] = "create-draft-pull-request"
        _reject(lambda: capability._materialize_verified_pilot_exact_task_pr_ready_credential_capability(
            ready_state_observation=observation,
            broker_descriptor=wrong_descriptor,
            now_provider=lambda: "2026-09-15T06:24:51Z",
        ))
        wrong_descriptor = dict(descriptor)
        wrong_descriptor["credential_protocol"] = "github-rest-ready-for-review-broker-v1"
        _reject(lambda: capability._materialize_verified_pilot_exact_task_pr_ready_credential_capability(
            ready_state_observation=observation,
            broker_descriptor=wrong_descriptor,
            now_provider=lambda: "2026-09-15T06:24:51Z",
        ))

        permissive = dict(policy)
        permissive["pull_request_create_write_forbidden"] = False
        _reject(lambda: production._parse_policy(_canonical(permissive), broker_path=broker_path))
        permissive = dict(policy)
        permissive["reviewer_write_forbidden"] = False
        _reject(lambda: production._parse_policy(_canonical(permissive), broker_path=broker_path))
        permissive = dict(policy)
        permissive["merge_write_forbidden"] = False
        _reject(lambda: production._parse_policy(_canonical(permissive), broker_path=broker_path))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(serialized)
        assert set(schema["required"]) == set(serialized)
        assert schema["properties"]["credential_operation"]["const"] == "mark-pull-request-ready-for-review"
        assert schema["properties"]["credential_protocol"]["const"] == "github-graphql-ready-for-review-broker-v1"
        assert schema["properties"]["api_origin"]["const"] == "https://api.github.com/graphql"
        assert schema["properties"]["ready_for_review_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            capability.materialize_pilot_exact_task_pr_ready_credential_capability
        ).parameters
        assert tuple(public_parameters) == ("ready_state_observation",)

        source = inspect.getsource(impl)
        assert "urllib.request" not in source
        assert "requests." not in source
        assert "subprocess" not in source
        assert "create_pull_request(" not in source
        assert "update_pull_request(" not in source
        assert "mark_pull_request_ready_for_review(" not in source
        assert "request_pull_request_reviewers(" not in source
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
