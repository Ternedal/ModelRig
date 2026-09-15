"""Adversarial contract for ADR-DC-082 status-bound review-thread capability."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEVCONTROL_SRC):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_status_check_observation as status_observation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_status_review_thread_credential_capability as capability  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_status_review_thread_credential_capability_production_boundary as production  # noqa: E402
import rsi_pilot_exact_task_pr_status_check_observation_contract as parent  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pr-status-review-thread-credential-capability-v1.schema.json"
)
BROKER_PATH = Path("/opt/modelrig/test/rsi-github-review-thread-read-broker-v1")
BROKER_SHA256 = "1" * 64
POLICY_SHA256 = "2" * 64


def _reject(fn) -> None:
    try:
        fn()
    except (
        capability.PilotExactTaskPrStatusReviewThreadCredentialCapabilityError,
        status_observation.PilotExactTaskPrStatusCheckObservationError,
        production.PilotExactTaskPrStatusReviewThreadCredentialCapabilityProductionBoundaryError,
        ValueError, TypeError, OSError, AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-082 unexpectedly accepted unsafe capability state")


def _descriptor() -> dict[str, str]:
    return {
        "broker_policy_sha256": POLICY_SHA256,
        "broker_executable_path": os.fspath(BROKER_PATH),
        "broker_executable_path_sha256": hashlib.sha256(
            os.fsencode(os.path.abspath(os.fspath(BROKER_PATH)))
        ).hexdigest(),
        "broker_executable_sha256": BROKER_SHA256,
        "broker_version": "test-v1",
        "credential_protocol": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_CREDENTIAL_PROTOCOL,
        "graphql_operation": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_OPERATION,
        "secret_source": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_SECRET_SOURCE,
        "secret_transport": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_SECRET_TRANSPORT,
        "graphql_endpoint": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_ENDPOINT,
        "credential_account": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_CREDENTIAL_ACCOUNT,
        "graphql_query_sha256": hashlib.sha256(
            capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_QUERY.encode("utf-8")
        ).hexdigest(),
    }


def _materialize(value, at_utc="2026-09-15T06:26:09Z"):
    return capability._materialize_verified_pilot_exact_task_pr_status_review_thread_credential_capability(
        status_check_observation=value,
        broker_descriptor=_descriptor(),
        now_provider=lambda: at_utc,
    )


def _policy() -> dict[str, object]:
    return {
        "schema": production.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "graphql_endpoint": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_ENDPOINT,
        "repository": "Ternedal/ModelRig",
        "credential_account": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_CREDENTIAL_ACCOUNT,
        "credential_protocol": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_CREDENTIAL_PROTOCOL,
        "operation": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_OPERATION,
        "broker_version": "test-v1",
        "broker_executable_path": os.fspath(BROKER_PATH),
        "broker_executable_sha256": BROKER_SHA256,
        "secret_source": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_SECRET_SOURCE,
        "secret_transport": capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_SECRET_TRANSPORT,
        "graphql_query_sha256": hashlib.sha256(
            capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_QUERY.encode("utf-8")
        ).hexdigest(),
        "status_observation_required": True,
        "status_policy_must_remain_unevaluated": True,
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
    preflight, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = parent._live_preflight()
    try:
        checks = [
            parent._check(preflight, run_id=9201, name="ci"),
            parent._check(
                preflight,
                run_id=9202,
                name="agent3-diagnostics",
                status="in_progress",
                conclusion=None,
            ),
        ]
        statuses = [parent._legacy(status_id=9301, context="legacy/security", state="success")]
        source = parent._observe(
            preflight,
            parent._stable_transport(preflight, checks, statuses),
        )
        assert source.observation_authenticated is True
        assert source.required_status_checks_evaluated is False
        assert source.status_policy_evaluated is False
        assert source.review_threads_preflight_required is True

        result = _materialize(source)
        assert result.capability_authenticated is True
        assert result.status_check_observation_sha256 == source.sha256
        assert result.merge_preflight_sha256 == source.merge_preflight_sha256
        assert result.review_disposition_sha256 == source.review_disposition_sha256
        assert result.predicted_commit_sha == source.predicted_commit_sha
        assert result.check_runs_inventory_sha256 == source.check_runs_inventory_sha256
        assert result.legacy_statuses_inventory_sha256 == source.legacy_statuses_inventory_sha256
        assert result.status_combined_evidence_sha256 == source.second_combined_evidence_sha256
        assert result.check_run_count == 2
        assert result.legacy_status_count == 1
        assert result.pull_request_node_id_sha256 == preflight.pull_request_node_id_sha256
        assert result.reviewer_login == preflight.reviewer_login
        assert result.pull_request_author_login == preflight.pull_request_author_login
        assert result.semantic_pr_title_sha256 == preflight.semantic_pr_title_sha256
        assert result.semantic_pr_body_sha256 == preflight.semantic_pr_body_sha256
        assert result.source_status_second_observed_at_utc == source.second_observed_at_utc

        for field in (
            "status_check_observation_verified", "source_merge_preflight_verified",
            "source_approved_review_verified", "source_exact_head_status_inventory_verified",
            "source_status_policy_not_evaluated", "source_required_status_checks_not_evaluated",
            "source_review_threads_required", "source_branch_policy_required",
            "source_fresh_review_reobservation_required",
            "source_fresh_merge_transaction_revalidation_required",
            "fresh_status_observation_age_verified", "review_thread_credential_capability_materialized",
            "read_broker_host_pinned", "read_broker_binary_verified", "credential_secret_not_loaded",
            "credential_broker_owns_https", "review_decision_read_only", "review_threads_read_only",
            "graphql_queries_only", "graphql_mutations_forbidden", "graphql_introspection_forbidden",
            "redirect_following_forbidden", "rest_review_read_forbidden", "other_repository_reads_forbidden",
            "review_submission_write_forbidden", "review_dismissal_write_forbidden",
            "review_thread_mutation_forbidden", "reviewer_request_write_forbidden",
            "pull_request_create_forbidden", "pull_request_metadata_write_forbidden",
            "ready_for_review_write_forbidden", "label_write_forbidden", "merge_write_forbidden",
            "repository_contents_write_forbidden", "administration_write_forbidden",
            "release_write_forbidden", "deployment_write_forbidden",
            "review_thread_state_observation_required", "required_status_checks_evaluation_still_required",
            "branch_policy_still_required", "fresh_review_reobservation_still_required",
            "fresh_merge_transaction_revalidation_still_required",
        ):
            assert getattr(result, field) is True

        for field in (
            "credential_material_in_artifact", "credential_material_in_process_arguments",
            "credential_material_in_environment", "nonce_reusable", "reviewer_mutation_authorized",
            "review_submission_authorized", "review_thread_mutation_authorized",
            "merge_readiness_authorized", "label_mutation_authorized", "merge_authorized",
            "release_authorized", "deploy_authorized", "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        reloaded = capability.PilotExactTaskPrStatusReviewThreadCredentialCapability.from_mapping(
            result.to_dict()
        )
        assert reloaded == result and reloaded.sha256 == result.sha256
        assert reloaded.capability_authenticated is False

        loose = status_observation.PilotExactTaskPrStatusCheckObservation.from_mapping(source.to_dict())
        assert loose.observation_authenticated is False
        _reject(lambda: capability._require_live_status_observation(loose))
        _reject(lambda: _materialize(loose))

        # Exactly 15 seconds from second status observation is accepted.
        _materialize(source, "2026-09-15T06:26:09Z")
        _reject(lambda: _materialize(source, "2026-09-15T06:26:10Z"))
        _reject(lambda: _materialize(source, "2026-09-15T06:25:53Z"))

        bad_operation = _descriptor()
        bad_operation["graphql_operation"] = "query-other"
        _reject(
            lambda: capability._materialize_verified_pilot_exact_task_pr_status_review_thread_credential_capability(
                status_check_observation=source,
                broker_descriptor=bad_operation,
                now_provider=lambda: "2026-09-15T06:26:09Z",
            )
        )
        bad_query = _descriptor()
        bad_query["graphql_query_sha256"] = "3" * 64
        _reject(
            lambda: capability._materialize_verified_pilot_exact_task_pr_status_review_thread_credential_capability(
                status_check_observation=source,
                broker_descriptor=bad_query,
                now_provider=lambda: "2026-09-15T06:26:09Z",
            )
        )

        policy = _policy()
        parsed = production._parse_policy(
            production._canonical_bytes(policy),
            broker_path=BROKER_PATH,
            implementation=capability._implementation,
        )
        assert parsed["status_observation_required"] is True
        assert parsed["status_policy_must_remain_unevaluated"] is True
        assert parsed["rest_review_read_forbidden"] is True
        assert parsed["graphql_mutation_forbidden"] is True
        for field in (
            "status_observation_required", "status_policy_must_remain_unevaluated",
            "rest_review_read_forbidden", "other_repository_reads_forbidden",
            "graphql_mutation_forbidden",
        ):
            weakened = dict(policy)
            weakened[field] = False
            _reject(
                lambda weakened=weakened: production._parse_policy(
                    production._canonical_bytes(weakened),
                    broker_path=BROKER_PATH,
                    implementation=capability._implementation,
                )
            )

        # Public production wrapper must reject replayed source before host broker load.
        original_loader = production._canonical_broker_descriptor
        calls = []
        try:
            def forbidden_loader(_implementation):
                calls.append(True)
                raise AssertionError("broker descriptor touched before live status gate")

            production._canonical_broker_descriptor = forbidden_loader
            _reject(
                lambda: capability.materialize_pilot_exact_task_pr_status_review_thread_credential_capability(
                    loose
                )
            )
            assert calls == []
        finally:
            production._canonical_broker_descriptor = original_loader

        tampered = source.to_dict()
        tampered["status_policy_evaluated"] = True
        _reject(lambda: status_observation.PilotExactTaskPrStatusCheckObservation.from_mapping(tampered))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(capability.PilotExactTaskPrStatusReviewThreadCredentialCapability.__dataclass_fields__)
        assert len(fields) == 95
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["source_status_policy_not_evaluated"]["const"] is True
        assert schema["properties"]["source_required_status_checks_not_evaluated"]["const"] is True
        assert schema["properties"]["required_status_checks_evaluation_still_required"]["const"] is True
        assert schema["properties"]["rest_review_read_forbidden"]["const"] is True
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(
            inspect.signature(
                capability.materialize_pilot_exact_task_pr_status_review_thread_credential_capability
            ).parameters
        ) == ("status_check_observation",)
        impl_source = inspect.getsource(capability._implementation)
        assert "PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_QUERY" in impl_source
        for forbidden in (
            "UrllibReadOnlyTransport", "urllib", "requests.", "httpx", "subprocess",
            "run_bounded_subprocess", "Authorization", "request_pull_request_reviewers",
            "add_review_to_pr", "resolve_review_thread", "merge_pull_request(",
            "label_pr(", "enable_auto_merge",
        ):
            assert forbidden not in impl_source
    finally:
        ledger_temp.cleanup()
        tx_ledger.cleanup()
        write_temp.cleanup()
        parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
