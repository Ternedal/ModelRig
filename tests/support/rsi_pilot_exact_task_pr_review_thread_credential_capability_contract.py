"""Adversarial contract for ADR-DC-079 exact review-thread GraphQL capability."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_submitted_review_observation as observation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_thread_credential_capability as capability  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_review_thread_credential_capability_production_boundary as production  # noqa: E402
import rsi_pilot_exact_task_pr_submitted_review_observation_contract as parent  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-review-thread-credential-capability-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        capability.PilotExactTaskPrReviewThreadCredentialCapabilityError,
        observation.PilotExactTaskPrSubmittedReviewObservationError,
        production.PilotExactTaskPrReviewThreadCredentialCapabilityProductionBoundaryError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-079 unexpectedly accepted unsafe review-thread capability")


def _descriptor(root: Path):
    broker = root / "review-thread-broker"
    broker.write_bytes(b"adr-dc-079-review-thread-broker")
    return {
        "broker_policy_sha256": hashlib.sha256(b"policy-079").hexdigest(),
        "broker_executable_path": os.fspath(broker.resolve()),
        "broker_executable_path_sha256": hashlib.sha256(
            os.fsencode(os.path.abspath(os.fspath(broker.resolve())))
        ).hexdigest(),
        "broker_executable_sha256": hashlib.sha256(broker.read_bytes()).hexdigest(),
        "broker_version": "1.0.0",
        "credential_protocol": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_CREDENTIAL_PROTOCOL,
        "graphql_operation": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_GRAPHQL_OPERATION,
        "secret_source": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_SECRET_SOURCE,
        "secret_transport": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_SECRET_TRANSPORT,
        "graphql_endpoint": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_GRAPHQL_ENDPOINT,
        "credential_account": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_CREDENTIAL_ACCOUNT,
        "graphql_query_sha256": hashlib.sha256(
            capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_GRAPHQL_QUERY.encode("utf-8")
        ).hexdigest(),
    }


def _materialize(source, descriptor, *, at="2026-09-15T06:25:50Z"):
    return capability._materialize_verified_pilot_exact_task_pr_review_thread_credential_capability(
        submitted_review_observation=source,
        broker_descriptor=descriptor,
        now_provider=lambda: at,
    )


def _policy(descriptor):
    return {
        "schema": production.PILOT_EXACT_TASK_PR_REVIEW_THREAD_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "graphql_endpoint": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_GRAPHQL_ENDPOINT,
        "repository": "Ternedal/ModelRig",
        "credential_account": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_CREDENTIAL_ACCOUNT,
        "credential_protocol": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_CREDENTIAL_PROTOCOL,
        "operation": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_GRAPHQL_OPERATION,
        "broker_version": descriptor["broker_version"],
        "broker_executable_path": descriptor["broker_executable_path"],
        "broker_executable_sha256": descriptor["broker_executable_sha256"],
        "secret_source": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_SECRET_SOURCE,
        "secret_transport": capability.PILOT_EXACT_TASK_PR_REVIEW_THREAD_SECRET_TRANSPORT,
        "graphql_query_sha256": descriptor["graphql_query_sha256"],
        "graphql_query_only": True,
        "graphql_mutation_forbidden": True,
        "graphql_introspection_forbidden": True,
        "rest_review_read_forbidden": True,
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
    checkpoint, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = parent._live_checkpoint()
    broker_temp = TemporaryDirectory(prefix="rsi-review-thread-broker-079-")
    try:
        reviews = [
            parent._review(
                checkpoint,
                review_id=7901,
                node_id="PRR_kwDOexact079",
                state="APPROVED",
            )
        ]
        source = parent._observe(
            checkpoint,
            parent._stable_transport(checkpoint, reviews, requested=False),
        )
        assert source.observation_authenticated is True
        assert source.second_observed_at_utc == "2026-09-15T06:25:49Z"
        assert source.latest_exact_head_review_state == "APPROVED"
        assert source.review_policy_evaluated is False

        descriptor = _descriptor(Path(broker_temp.name))
        result = _materialize(source, descriptor)
        assert result.capability_authenticated is True
        assert result.submitted_review_observation_sha256 == source.sha256
        assert result.review_observation_checkpoint_sha256 == source.review_observation_checkpoint_sha256
        assert result.checkpoint_key_sha256 == source.checkpoint_key_sha256
        assert result.reviewer_request_nonce_sha256 == source.reviewer_request_nonce_sha256
        assert result.pull_request_number == source.pull_request_number
        assert result.predicted_commit_sha == source.predicted_commit_sha
        assert result.reviewer_login == source.reviewer_login
        assert result.reviewer_user_id == source.reviewer_user_id
        assert result.reviews_evidence_sha256 == source.reviews_evidence_sha256
        assert result.latest_exact_head_review_state == "APPROVED"
        assert result.exact_head_approved_review_count == 1
        assert result.materialized_at_utc == "2026-09-15T06:25:50Z"

        for field in (
            "submitted_review_observation_verified",
            "source_exact_pr_identity_revalidated",
            "source_exact_head_revalidated",
            "source_submitted_reviews_verified",
            "source_review_policy_not_evaluated",
            "review_thread_credential_capability_materialized",
            "read_broker_host_pinned",
            "read_broker_binary_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "review_decision_read_only",
            "review_threads_read_only",
            "graphql_queries_only",
            "graphql_mutations_forbidden",
            "graphql_introspection_forbidden",
            "redirect_following_forbidden",
            "rest_review_read_forbidden",
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
            "exact_graphql_pr_revalidation_required",
            "review_thread_state_observation_required",
            "review_policy_evaluation_required",
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

        replayed = capability.PilotExactTaskPrReviewThreadCredentialCapability.from_mapping(
            result.to_dict()
        )
        assert replayed == result and replayed.sha256 == result.sha256
        assert replayed.capability_authenticated is False

        source_copy = observation.PilotExactTaskPrSubmittedReviewObservation.from_mapping(
            source.to_dict()
        )
        assert source_copy.observation_authenticated is False
        _reject(lambda: _materialize(source_copy, descriptor))

        _reject(lambda: _materialize(source, descriptor, at="2026-09-15T06:25:48Z"))
        _reject(lambda: _materialize(source, descriptor, at="2026-09-15T06:26:20Z"))

        bad = dict(descriptor)
        bad["graphql_operation"] = "query-arbitrary-repository"
        _reject(lambda: _materialize(source, bad))
        bad = dict(descriptor)
        bad["graphql_query_sha256"] = hashlib.sha256(b"mutation").hexdigest()
        _reject(lambda: _materialize(source, bad))

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
        assert parsed["graphql_query_only"] is True
        assert parsed["rest_review_read_forbidden"] is True
        assert parsed["other_repository_reads_forbidden"] is True
        for weakened_field in (
            "rest_review_read_forbidden",
            "other_repository_reads_forbidden",
            "graphql_mutation_forbidden",
        ):
            weakened = dict(policy)
            weakened[weakened_field] = False
            weakened_payload = json.dumps(
                weakened,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            _reject(
                lambda payload=weakened_payload: production._parse_policy(
                    payload,
                    broker_path=Path(descriptor["broker_executable_path"]),
                    implementation=capability._implementation,
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(capability.PilotExactTaskPrReviewThreadCredentialCapability.__dataclass_fields__)
        assert len(fields) == 95
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["review_thread_credential_capability_materialized"]["const"] is True
        assert schema["properties"]["rest_review_read_forbidden"]["const"] is True
        assert schema["properties"]["review_policy_evaluation_required"]["const"] is True
        assert schema["properties"]["review_submission_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(
            inspect.signature(
                capability.materialize_pilot_exact_task_pr_review_thread_credential_capability
            ).parameters
        ) == ("submitted_review_observation",)

        implementation_source = inspect.getsource(capability._implementation)
        for forbidden in (
            "import subprocess",
            "urllib",
            "requests.",
            "httpx",
            "Authorization",
            "create_once_file",
            "UrllibReadOnlyTransport",
            "/reviews?",
            "request_pull_request_reviewers",
            "add_review_to_pr",
            "resolve_review_thread",
            "merge_pull_request(",
            "label_pr(",
        ):
            assert forbidden not in implementation_source
        production_source = inspect.getsource(production)
        assert '"rest_review_read_forbidden": True' in production_source
        assert '"other_repository_reads_forbidden": True' in production_source
        assert '"graphql_mutation_forbidden": True' in production_source
    finally:
        broker_temp.cleanup()
        ledger_temp.cleanup()
        tx_ledger.cleanup()
        write_temp.cleanup()
        parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
