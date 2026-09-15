"""Adversarial contract for ADR-DC-078 checkpoint-bound review-state capability."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_review_observation_checkpoint as checkpoint  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_state_credential_capability as capability  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_review_state_credential_capability_production_boundary as production  # noqa: E402
import rsi_pilot_exact_task_pr_review_observation_checkpoint_contract as parent  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-review-state-credential-capability-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        capability.PilotExactTaskPrReviewStateCredentialCapabilityError,
        checkpoint.PilotExactTaskPrReviewObservationCheckpointError,
        production.PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-078 unexpectedly accepted unsafe review-state capability")


def _descriptor(root: Path):
    broker = root / "review-state-broker"
    broker.write_bytes(b"adr-dc-078-review-state-broker")
    return {
        "broker_policy_sha256": hashlib.sha256(b"policy-078").hexdigest(),
        "broker_executable_path": os.fspath(broker.resolve()),
        "broker_executable_path_sha256": hashlib.sha256(
            os.fsencode(os.path.abspath(os.fspath(broker.resolve())))
        ).hexdigest(),
        "broker_executable_sha256": hashlib.sha256(broker.read_bytes()).hexdigest(),
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
        "graphql_query_sha256": hashlib.sha256(
            capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_QUERY.encode("utf-8")
        ).hexdigest(),
    }


def _materialize(value, descriptor, *, at="2026-09-16T06:25:46Z"):
    return capability._materialize_verified_pilot_exact_task_pr_review_state_credential_capability(
        review_observation_checkpoint=value,
        broker_descriptor=descriptor,
        now_provider=lambda: at,
    )


def _policy(descriptor):
    return {
        "schema": production.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "api_origin": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_API_ORIGIN,
        "graphql_endpoint": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_ENDPOINT,
        "repository": "Ternedal/ModelRig",
        "credential_account": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_ACCOUNT,
        "credential_protocol": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_PROTOCOL,
        "broker_version": descriptor["broker_version"],
        "broker_executable_path": descriptor["broker_executable_path"],
        "broker_executable_sha256": descriptor["broker_executable_sha256"],
        "secret_source": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_SOURCE,
        "secret_transport": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_TRANSPORT,
        "allowed_operations": [
            capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION,
            capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION,
        ],
        "reviews_path_template": capability.PILOT_EXACT_TASK_PR_REVIEW_STATE_REVIEWS_PATH_TEMPLATE,
        "graphql_query_sha256": descriptor["graphql_query_sha256"],
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
    source, tx_ledger, write_temp, parent_temp, cleanup = parent._live_attestation()
    ledger_temp = TemporaryDirectory(prefix="rsi-review-checkpoint-078-")
    broker_temp = TemporaryDirectory(prefix="rsi-review-broker-078-")
    try:
        ledger = checkpoint._ReviewObservationCheckpointLedger(
            Path(ledger_temp.name),
            require_host_control=False,
        )
        durable = parent._checkpoint(source, ledger)
        assert durable.checkpoint_authenticated is True

        # Simulate process restart: ADR-DC-076 provenance disappears; ADR-DC-077 reload survives.
        checkpoint._live_records.clear()
        loaded = ledger.load(durable.checkpoint_key_sha256)
        assert loaded.checkpoint_authenticated is True
        descriptor = _descriptor(Path(broker_temp.name))

        result = _materialize(loaded, descriptor)
        assert result.capability_authenticated is True
        assert result.review_observation_checkpoint_sha256 == loaded.sha256
        assert result.checkpoint_key_sha256 == loaded.checkpoint_key_sha256
        assert result.ledger_root_path_sha256 == loaded.ledger_root_path_sha256
        assert result.source_reviewer_request_attestation_sha256 == loaded.source_reviewer_request_attestation_sha256
        assert result.reviewer_write_transaction_sha256 == loaded.reviewer_write_transaction_sha256
        assert result.reviewer_request_nonce_sha256 == loaded.reviewer_request_nonce_sha256
        assert result.pull_request_number == loaded.pull_request_number
        assert result.predicted_commit_sha == loaded.predicted_commit_sha
        assert result.reviewer_login == loaded.reviewer_login
        assert result.reviewer_user_id == loaded.reviewer_user_id
        assert result.checkpointed_at_utc == loaded.checkpointed_at_utc

        # A human review may arrive much later; capability materialization has no short source-age TTL.
        assert result.materialized_at_utc == "2026-09-16T06:25:46Z"

        for field in (
            "checkpoint_reauthenticated_verified",
            "restart_safe_source_verified",
            "reviewer_request_performed_verified",
            "exact_requested_reviewer_verified",
            "team_reviewers_absent_verified",
            "review_state_credential_capability_materialized",
            "read_broker_host_pinned",
            "read_broker_binary_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "reviews_read_only",
            "review_threads_read_only",
            "review_decision_read_only",
            "graphql_queries_only",
            "graphql_mutations_forbidden",
            "graphql_introspection_forbidden",
            "redirect_following_forbidden",
            "collaborator_permission_read_forbidden",
            "other_repository_reads_forbidden",
            "review_submission_write_forbidden",
            "review_dismissal_write_forbidden",
            "review_thread_mutation_forbidden",
            "reviewer_request_write_forbidden",
            "pull_request_create_forbidden",
            "pull_request_metadata_write_forbidden",
            "ready_for_review_write_forbidden",
            "label_write_forbidden",
            "merge_write_forbidden",
            "repository_contents_write_forbidden",
            "administration_write_forbidden",
            "release_write_forbidden",
            "deployment_write_forbidden",
            "fresh_exact_pr_revalidation_required",
            "review_state_observation_required",
            "checkpoint_reusable_for_future_observation",
        ):
            assert getattr(result, field) is True
        for field in (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "nonce_reusable",
            "reviewer_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "merge_readiness_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        replayed = capability.PilotExactTaskPrReviewStateCredentialCapability.from_mapping(
            result.to_dict()
        )
        assert replayed == result
        assert replayed.sha256 == result.sha256
        assert replayed.capability_authenticated is False

        loose_checkpoint = checkpoint.PilotExactTaskPrReviewObservationCheckpoint.from_mapping(
            loaded.to_dict()
        )
        assert loose_checkpoint.checkpoint_authenticated is False
        _reject(lambda: _materialize(loose_checkpoint, descriptor))

        bad = dict(descriptor)
        bad["rest_operation"] = "list-all-repository-events"
        _reject(lambda: _materialize(loaded, bad))
        bad = dict(descriptor)
        bad["graphql_query_sha256"] = hashlib.sha256(b"mutation").hexdigest()
        _reject(lambda: _materialize(loaded, bad))
        _reject(lambda: _materialize(loaded, descriptor, at="2026-09-15T06:25:45Z"))

        policy = _policy(descriptor)
        payload = json.dumps(
            policy,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        parsed = production._parse_policy(
            payload,
            broker_path=Path(descriptor["broker_executable_path"]),
            implementation=capability._implementation,
        )
        assert parsed["other_repository_reads_forbidden"] is True
        widened = dict(policy)
        widened["other_repository_reads_forbidden"] = False
        widened_payload = json.dumps(
            widened,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        _reject(
            lambda: production._parse_policy(
                widened_payload,
                broker_path=Path(descriptor["broker_executable_path"]),
                implementation=capability._implementation,
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(capability.PilotExactTaskPrReviewStateCredentialCapability.__dataclass_fields__)
        assert len(fields) == 96
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["checkpoint_reauthenticated_verified"]["const"] is True
        assert schema["properties"]["fresh_exact_pr_revalidation_required"]["const"] is True
        assert schema["properties"]["review_submission_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(
            inspect.signature(
                capability.materialize_pilot_exact_task_pr_review_state_credential_capability
            ).parameters
        ) == ("review_observation_checkpoint",)

        implementation_source = inspect.getsource(capability._implementation)
        for forbidden in (
            "import subprocess",
            "urllib",
            "requests.",
            "httpx",
            "Authorization",
            "create_once_file",
            "request_pull_request_reviewers",
            "add_review_to_pr",
            "resolve_review_thread",
            "merge_pull_request(",
            "label_pr(",
        ):
            assert forbidden not in implementation_source
        assert "MAX_SOURCE_AGE" not in implementation_source
        production_source = inspect.getsource(production)
        assert '"other_repository_reads_forbidden": True' in production_source
        assert '"graphql_mutation_forbidden": True' in production_source
    finally:
        ledger_temp.cleanup()
        broker_temp.cleanup()
        tx_ledger.cleanup()
        write_temp.cleanup()
        parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
