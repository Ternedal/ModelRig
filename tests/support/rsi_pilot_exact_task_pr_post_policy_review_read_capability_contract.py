"""Adversarial contract for ADR-DC-092 post-policy review read capability."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEV = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEV):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_post_policy_review_read_capability as capability
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_policy as policy
from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation as observation_boundary
from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability as prior_capability_boundary
from kaliv_dev_control import _improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability_production_boundary as production
import rsi_pilot_exact_task_pr_review_policy_contract as parent

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-post-policy-review-read-capability-v1.schema.json"


def _reject(fn):
    try:
        fn()
    except (
        capability.PilotExactTaskPrPostPolicyReviewReadCapabilityError,
        policy.PilotExactTaskPrReviewPolicyError,
        ValueError, TypeError, OSError, AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-092 accepted unsafe post-policy read capability")


def _source():
    observed, prior_capability, strict, req, upstream_live, items, temp = parent._source()
    review_policy = policy.synthesize_pilot_exact_task_pr_review_policy(observed)
    assert review_policy.policy_authenticated is True
    observed_live = observation_boundary._get_live_pr_strict_synced_review_thread_state_observation_inputs(observed)
    assert observed_live is not None and observed_live["review_thread_read_capability"] is prior_capability
    prior_live = prior_capability_boundary._get_live_pr_strict_synced_review_thread_read_capability_inputs(prior_capability)
    assert prior_live is not None
    descriptor = dict(prior_live["broker_descriptor"])
    return review_policy, observed, prior_capability, strict, descriptor, items, temp


def _materialize(review_policy, descriptor, *, at="2026-09-15T19:30:21Z"):
    return capability._materialize_verified_pilot_exact_task_pr_post_policy_review_read_capability(
        review_policy=review_policy,
        broker_descriptor=descriptor,
        now_provider=lambda: at,
    )


def run_contract():
    if os.name == "nt":
        return
    parent.run_contract()
    review_policy, observed, prior_capability, strict, descriptor, items, temp = _source()
    try:
        result = _materialize(review_policy, descriptor)
        assert result.capability_authenticated is True
        assert result.review_policy_sha256 == review_policy.sha256
        assert result.review_thread_state_observation_sha256 == observed.sha256
        assert result.prior_review_read_capability_sha256 == prior_capability.sha256
        assert result.strict_base_sync_preflight_sha256 == strict.sha256
        assert result.ruleset_applicability_sha256 == review_policy.ruleset_applicability_sha256
        assert result.ruleset_observation_sha256 == review_policy.ruleset_observation_sha256
        assert result.branch_protection_observation_sha256 == review_policy.branch_protection_observation_sha256
        assert result.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == review_policy.pull_request_number
        assert result.predicted_commit_sha == review_policy.predicted_commit_sha
        assert result.strict_base_tip_sha == review_policy.strict_base_tip_sha
        assert result.effective_review_policy_sha256 == review_policy.effective_review_policy_sha256
        assert result.graphql_operation == prior_capability.graphql_operation
        assert result.graphql_query_sha256 == prior_capability.graphql_query_sha256
        assert result.credential_account_sha256 == hashlib.sha256(b"Ternedal").hexdigest()
        assert result.materialized_at_utc == "2026-09-15T19:30:21Z"

        for field in (
            "source_review_policy_verified", "source_review_observation_verified",
            "source_review_policy_supported", "effective_review_policy_hash_verified",
            "fresh_source_window_verified", "post_policy_review_read_capability_materialized",
            "read_broker_host_pinned", "read_broker_binary_verified", "credential_secret_not_loaded",
            "credential_broker_owns_https", "graphql_query_only", "graphql_mutations_forbidden",
            "graphql_introspection_forbidden", "other_repository_reads_forbidden",
            "fresh_review_reobservation_required", "review_policy_evaluation_required",
            "fresh_required_status_reobservation_before_merge_required",
            "fresh_merge_transaction_revalidation_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "branch_policy_fully_evaluated", "review_thread_policy_evaluated",
            "credential_material_in_artifact", "credential_material_in_process_arguments",
            "credential_material_in_environment", "review_thread_mutation_authorized",
            "review_submission_authorized", "merge_readiness_authorized", "merge_authorized",
            "release_authorized", "deploy_authorized", "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        live = capability._get_live_pr_post_policy_review_read_capability_inputs(result)
        assert live is not None and live["review_policy"] is review_policy
        assert dict(live["broker_descriptor"]) == descriptor

        replay = capability.PilotExactTaskPrPostPolicyReviewReadCapability.from_mapping(result.to_dict())
        assert replay == result and replay.capability_authenticated is False

        loose_policy = policy.PilotExactTaskPrReviewPolicy.from_mapping(review_policy.to_dict())
        assert loose_policy.policy_authenticated is False
        _reject(lambda: _materialize(loose_policy, descriptor))

        _reject(lambda: _materialize(review_policy, descriptor, at="2026-09-15T19:30:51Z"))
        _reject(lambda: _materialize(review_policy, descriptor, at="2026-09-15T19:30:19Z"))

        bad = dict(descriptor)
        bad["credential_protocol"] = "other-v1"
        _reject(lambda: _materialize(review_policy, bad))
        bad = dict(descriptor)
        bad["graphql_query_sha256"] = "4" * 64
        _reject(lambda: _materialize(review_policy, bad))
        bad = dict(descriptor)
        bad["broker_executable_path_sha256"] = "5" * 64
        _reject(lambda: _materialize(review_policy, bad))

        tampered = review_policy.to_dict()
        tampered["effective_dismiss_stale_reviews"] = 1
        weak = policy.PilotExactTaskPrReviewPolicy.from_mapping(tampered)
        _reject(lambda: capability._effective_policy(weak))
        tampered = review_policy.to_dict()
        tampered["effective_required_approving_review_count"] += 1
        weak = policy.PilotExactTaskPrReviewPolicy.from_mapping(tampered)
        _reject(lambda: capability._effective_policy(weak))
        tampered = review_policy.to_dict()
        tampered["synthesis_result"] = "UNSUPPORTED"
        weak = policy.PilotExactTaskPrReviewPolicy.from_mapping(tampered)
        _reject(lambda: capability._effective_policy(weak))

        original = production._canonical_broker_descriptor
        calls = []
        try:
            def forbidden(*_args, **_kwargs):
                calls.append(True)
                raise AssertionError("host state touched before live ADR-DC-091 validation")
            production._canonical_broker_descriptor = forbidden
            _reject(lambda: capability.materialize_pilot_exact_task_pr_post_policy_review_read_capability(loose_policy))
            assert calls == []
        finally:
            production._canonical_broker_descriptor = original

        tampered = result.to_dict()
        tampered["merge_authorized"] = True
        _reject(lambda: capability.PilotExactTaskPrPostPolicyReviewReadCapability.from_mapping(tampered))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(capability.PilotExactTaskPrPostPolicyReviewReadCapability.__dataclass_fields__)
        assert len(fields) == 56
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["post_policy_review_read_capability_materialized"]["const"] is True
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert tuple(inspect.signature(capability.materialize_pilot_exact_task_pr_post_policy_review_read_capability).parameters) == ("review_policy",)

        source = inspect.getsource(capability)
        for forbidden in (
            "run_bounded_subprocess", "urllib.request", "requests.", "httpx.",
            "merge_pull_request(", "resolve_review_thread(", "add_review_to_pr(",
            "dismiss_pull_request_review(", "request_pull_request_reviewers(", "label_pr(",
        ):
            assert forbidden not in source
    finally:
        parent.parent.parent._cleanup(items)
        temp.cleanup()


if __name__ == "__main__":
    run_contract()
