"""Adversarial contract for ADR-DC-084 branch-policy-bound review-thread capability."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_observation as ruleset  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_branch_bound_review_thread_credential_capability as capability  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_branch_bound_review_thread_credential_capability_production_boundary as production  # noqa: E402
import rsi_pilot_exact_task_pr_ruleset_observation_contract as parent  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-branch-bound-review-thread-credential-capability-v1.schema.json"
BROKER_PATH = Path("/opt/modelrig/test/rsi-github-branch-bound-review-thread-read-broker-v1")
BROKER_SHA256 = "1" * 64
POLICY_SHA256 = "2" * 64


def _reject(fn) -> None:
    try:
        fn()
    except (
        capability.PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityError,
        ruleset.PilotExactTaskPrRulesetObservationError,
        production.PilotExactTaskPrBranchBoundReviewThreadCredentialCapabilityProductionBoundaryError,
        ValueError, TypeError, OSError, AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-084 unexpectedly accepted unsafe capability state")


def _descriptor() -> dict[str, str]:
    return {
        "broker_policy_sha256": POLICY_SHA256,
        "broker_executable_path": os.fspath(BROKER_PATH),
        "broker_executable_path_sha256": hashlib.sha256(
            os.fsencode(os.path.abspath(os.fspath(BROKER_PATH)))
        ).hexdigest(),
        "broker_executable_sha256": BROKER_SHA256,
        "broker_version": "test-v1",
        "credential_protocol": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_PROTOCOL,
        "graphql_operation": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_OPERATION,
        "secret_source": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_SOURCE,
        "secret_transport": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_TRANSPORT,
        "graphql_endpoint": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_ENDPOINT,
        "credential_account": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_ACCOUNT,
        "graphql_query_sha256": hashlib.sha256(
            capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_QUERY.encode("utf-8")
        ).hexdigest(),
    }


def _policy() -> dict[str, object]:
    return {
        "schema": production.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "graphql_endpoint": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_ENDPOINT,
        "repository": "Ternedal/ModelRig",
        "credential_account": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_ACCOUNT,
        "credential_protocol": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_CREDENTIAL_PROTOCOL,
        "operation": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_OPERATION,
        "broker_version": "test-v1",
        "broker_executable_path": os.fspath(BROKER_PATH),
        "broker_executable_sha256": BROKER_SHA256,
        "secret_source": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_SOURCE,
        "secret_transport": capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_SECRET_TRANSPORT,
        "graphql_query_sha256": hashlib.sha256(
            capability.PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_QUERY.encode("utf-8")
        ).hexdigest(),
        "ruleset_observation_required": True,
        "branch_policy_sources_required": True,
        "ruleset_policy_must_remain_unevaluated": True,
        "required_status_checks_must_remain_unevaluated": True,
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


def _source():
    branch, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = parent._branch_source()
    source = parent._observe(branch, parent._stable_transport())
    assert source.observation_authenticated is True
    return source, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup


def _materialize(value, at_utc="2026-09-15T06:26:13Z"):
    return capability._materialize_verified_pilot_exact_task_pr_branch_bound_review_thread_credential_capability(
        ruleset_observation=value,
        broker_descriptor=_descriptor(),
        now_provider=lambda: at_utc,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    parent.run_contract()
    source, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = _source()
    try:
        live = capability._require_live_ruleset_observation(source)
        branch = live["branch_protection_observation"]
        status = live["status_check_observation"]
        preflight = live["merge_preflight"]
        assert len(live["rulesets"]) == source.ruleset_count
        assert len(live["check_runs"]) == status.check_run_count
        assert len(live["legacy_statuses"]) == status.legacy_status_count

        result = _materialize(source)
        assert result.capability_authenticated is True
        assert result.ruleset_observation_sha256 == source.sha256
        assert result.branch_protection_observation_sha256 == branch.sha256
        assert result.status_check_observation_sha256 == status.sha256
        assert result.merge_preflight_sha256 == preflight.sha256
        assert result.review_disposition_sha256 == source.review_disposition_sha256
        assert result.predicted_commit_sha == source.predicted_commit_sha
        assert result.base_branch_tip_sha == source.base_branch_tip_sha
        assert result.pull_request_node_id_sha256 == preflight.pull_request_node_id_sha256
        assert result.reviewer_login == preflight.reviewer_login
        assert result.reviewer_user_id == preflight.reviewer_user_id
        assert result.pull_request_author_login == preflight.pull_request_author_login
        assert result.semantic_pr_title_sha256 == preflight.semantic_pr_title_sha256
        assert result.semantic_pr_body_sha256 == preflight.semantic_pr_body_sha256
        assert result.check_runs_inventory_sha256 == status.check_runs_inventory_sha256
        assert result.legacy_statuses_inventory_sha256 == status.legacy_statuses_inventory_sha256
        assert result.required_status_policy_sha256 == branch.required_status_policy_sha256
        assert result.normalized_protection_sha256 == branch.normalized_protection_sha256
        assert result.ruleset_inventory_sha256 == source.ruleset_inventory_sha256
        assert result.ruleset_combined_evidence_sha256 == source.second_combined_evidence_sha256
        assert result.ruleset_count == source.ruleset_count == 2
        assert result.active_ruleset_count == 1
        assert result.evaluate_ruleset_count == 1

        for field in (
            "ruleset_observation_verified", "branch_protection_observation_verified",
            "status_check_observation_verified", "source_merge_preflight_verified",
            "source_approved_review_verified", "source_exact_head_status_inventory_verified",
            "source_legacy_branch_protection_verified", "source_repository_rulesets_verified",
            "source_inherited_rulesets_verified", "source_branch_policy_sources_observed",
            "source_status_policy_not_evaluated", "source_required_status_checks_not_evaluated",
            "source_ruleset_policy_not_evaluated", "fresh_ruleset_observation_age_verified",
            "review_thread_credential_capability_materialized", "read_broker_host_pinned",
            "read_broker_binary_verified", "credential_secret_not_loaded", "credential_broker_owns_https",
            "review_decision_read_only", "review_threads_read_only", "graphql_queries_only",
            "graphql_mutations_forbidden", "graphql_introspection_forbidden", "redirect_following_forbidden",
            "rest_review_read_forbidden", "other_repository_reads_forbidden", "review_submission_write_forbidden",
            "review_dismissal_write_forbidden", "review_thread_mutation_forbidden", "reviewer_request_write_forbidden",
            "pull_request_create_forbidden", "pull_request_metadata_write_forbidden", "ready_for_review_write_forbidden",
            "label_write_forbidden", "merge_write_forbidden", "repository_contents_write_forbidden",
            "administration_write_forbidden", "release_write_forbidden", "deployment_write_forbidden",
            "review_thread_state_observation_required", "required_status_checks_evaluation_still_required",
            "ruleset_policy_evaluation_still_required", "fresh_review_reobservation_still_required",
            "fresh_merge_transaction_revalidation_still_required",
        ):
            assert getattr(result, field) is True

        for field in (
            "branch_policy_fully_evaluated", "credential_material_in_artifact",
            "credential_material_in_process_arguments", "credential_material_in_environment",
            "nonce_reusable", "reviewer_mutation_authorized", "review_submission_authorized",
            "review_thread_mutation_authorized", "merge_readiness_authorized", "label_mutation_authorized",
            "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        reloaded = capability.PilotExactTaskPrBranchBoundReviewThreadCredentialCapability.from_mapping(result.to_dict())
        assert reloaded == result and reloaded.sha256 == result.sha256
        assert reloaded.capability_authenticated is False

        loose = ruleset.PilotExactTaskPrRulesetObservation.from_mapping(source.to_dict())
        assert loose.observation_authenticated is False
        _reject(lambda: capability._require_live_ruleset_observation(loose))
        _reject(lambda: _materialize(loose))

        # Exactly 15 seconds from the second ADR-DC-083 observation is accepted.
        _materialize(source, "2026-09-15T06:26:13Z")
        _reject(lambda: _materialize(source, "2026-09-15T06:26:14Z"))
        _reject(lambda: _materialize(source, "2026-09-15T06:25:57Z"))

        bad_operation = _descriptor()
        bad_operation["graphql_operation"] = "query-other"
        _reject(lambda: capability._materialize_verified_pilot_exact_task_pr_branch_bound_review_thread_credential_capability(
            ruleset_observation=source, broker_descriptor=bad_operation, now_provider=lambda: "2026-09-15T06:26:13Z"
        ))
        bad_query = _descriptor()
        bad_query["graphql_query_sha256"] = "3" * 64
        _reject(lambda: capability._materialize_verified_pilot_exact_task_pr_branch_bound_review_thread_credential_capability(
            ruleset_observation=source, broker_descriptor=bad_query, now_provider=lambda: "2026-09-15T06:26:13Z"
        ))

        policy = _policy()
        parsed = production._parse_policy(
            production._canonical_bytes(policy), broker_path=BROKER_PATH, implementation=capability._implementation
        )
        assert parsed["ruleset_observation_required"] is True
        assert parsed["branch_policy_sources_required"] is True
        assert parsed["ruleset_policy_must_remain_unevaluated"] is True
        assert parsed["required_status_checks_must_remain_unevaluated"] is True
        for field in (
            "ruleset_observation_required", "branch_policy_sources_required",
            "ruleset_policy_must_remain_unevaluated", "required_status_checks_must_remain_unevaluated",
            "rest_review_read_forbidden", "other_repository_reads_forbidden", "graphql_mutation_forbidden",
        ):
            weakened = dict(policy)
            weakened[field] = False
            _reject(lambda weakened=weakened: production._parse_policy(
                production._canonical_bytes(weakened), broker_path=BROKER_PATH, implementation=capability._implementation
            ))

        # Production wrapper rejects a replay before touching host policy/broker state.
        original_loader = production._canonical_broker_descriptor
        calls = []
        try:
            def forbidden_loader(_implementation):
                calls.append(True)
                raise AssertionError("broker descriptor touched before live ruleset gate")
            production._canonical_broker_descriptor = forbidden_loader
            _reject(lambda: capability.materialize_pilot_exact_task_pr_branch_bound_review_thread_credential_capability(loose))
            assert calls == []
        finally:
            production._canonical_broker_descriptor = original_loader

        tampered = result.to_dict()
        tampered["ruleset_inventory_sha256"] = "4" * 64
        _reject(lambda: capability.PilotExactTaskPrBranchBoundReviewThreadCredentialCapability.from_mapping(tampered))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(capability.PilotExactTaskPrBranchBoundReviewThreadCredentialCapability.__dataclass_fields__)
        assert len(fields) == 114
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["source_branch_policy_sources_observed"]["const"] is True
        assert schema["properties"]["source_required_status_checks_not_evaluated"]["const"] is True
        assert schema["properties"]["source_ruleset_policy_not_evaluated"]["const"] is True
        assert schema["properties"]["branch_policy_fully_evaluated"]["const"] is False
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(inspect.signature(
            capability.materialize_pilot_exact_task_pr_branch_bound_review_thread_credential_capability
        ).parameters) == ("ruleset_observation",)
        impl_source = inspect.getsource(capability._implementation)
        assert "PILOT_EXACT_TASK_PR_BRANCH_BOUND_REVIEW_THREAD_GRAPHQL_QUERY" in impl_source
        for forbidden in (
            "UrllibReadOnlyTransport", "urllib", "requests.", "httpx", "subprocess", "run_bounded_subprocess",
            "Authorization", "request_pull_request_reviewers", "add_review_to_pr", "resolve_review_thread",
            "merge_pull_request(", "label_pr(", "enable_auto_merge",
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
