"""Adversarial contract for ADR-DC-092 exact review-evidence requirements."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEV = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEV):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_review_evidence_requirements as requirements  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_policy as policy  # noqa: E402
import rsi_pilot_exact_task_pr_review_policy_contract as parent  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-review-evidence-requirements-v1.schema.json"


def _reject(fn):
    try:
        fn()
    except (
        requirements.PilotExactTaskPrReviewEvidenceRequirementsError,
        policy.PilotExactTaskPrReviewPolicyError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-092 accepted unsafe review-evidence requirements")


def _source():
    observed, cap, strict, req, upstream_live, items, temp = parent._source()
    review_policy = policy.synthesize_pilot_exact_task_pr_review_policy(observed)
    assert review_policy.policy_authenticated is True
    return review_policy, observed, cap, strict, req, upstream_live, items, temp


def _shape(*, result="SUPPORTED", count=1, dismiss=True, codeowners=False, last_push=True, conversations=True):
    return SimpleNamespace(
        synthesis_result=result,
        effective_required_approving_review_count=count,
        effective_dismiss_stale_reviews=dismiss,
        effective_require_code_owner_reviews=codeowners,
        effective_require_last_push_approval=last_push,
        effective_required_conversation_resolution=conversations,
    )


def run_contract():
    if os.name == "nt":
        return
    parent.run_contract()
    review_policy, observed, cap, strict, req, upstream_live, items, temp = _source()
    try:
        result = requirements.plan_pilot_exact_task_pr_review_evidence_requirements(review_policy)
        assert result.requirements_authenticated is True
        assert result.review_policy_sha256 == review_policy.sha256
        assert result.review_thread_state_observation_sha256 == observed.sha256
        assert result.review_thread_read_capability_sha256 == cap.sha256
        assert result.strict_base_sync_preflight_sha256 == strict.sha256
        assert result.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == observed.pull_request_number
        assert result.predicted_commit_sha == observed.predicted_commit_sha
        assert result.strict_base_tip_sha == observed.strict_base_tip_sha
        assert result.review_threads_inventory_sha256 == observed.review_threads_inventory_sha256
        assert result.github_review_decision == observed.github_review_decision
        assert result.observed_review_thread_count == observed.review_thread_count
        assert result.observed_unresolved_review_thread_count == observed.unresolved_review_thread_count

        # Current canonical fixture policy: one approval, dismiss stale, last-push approval, resolve conversations.
        assert result.policy_synthesis_result == "SUPPORTED"
        assert result.requirements_result == "SUPPORTED"
        assert result.policy_required_approving_review_count == 1
        assert result.policy_dismiss_stale_reviews is True
        assert result.policy_require_code_owner_reviews is False
        assert result.policy_require_last_push_approval is True
        assert result.policy_required_conversation_resolution is True
        assert result.exact_head_submitted_review_inventory_required is True
        assert result.approval_count_evidence_required is True
        assert result.stale_review_freshness_evidence_required is True
        assert result.code_owner_change_set_evidence_required is False
        assert result.code_owner_identity_evidence_required is False
        assert result.latest_push_actor_evidence_required is True
        assert result.conversation_resolution_evidence_required is True
        assert result.conversation_resolution_evidence_available is True
        assert result.exact_head_commit_binding_required is True
        assert result.reviewer_identity_binding_required is True
        assert result.graphql_review_decision_summary_only is True
        assert result.graphql_review_decision_sufficient_for_pass is False
        assert result.manual_or_new_policy_parser_required is False

        live = requirements._get_live_pr_review_evidence_requirements_inputs(result)
        assert live is not None
        assert live["review_policy"] is review_policy
        assert live["review_thread_state_observation"] is observed
        assert live["evidence_requirements"]["latest_push_actor_evidence_required"] is True

        # Serialized receipts are structurally valid but inert.
        replay = requirements.PilotExactTaskPrReviewEvidenceRequirements.from_mapping(result.to_dict())
        assert replay == result and replay.requirements_authenticated is False
        loose_policy = policy.PilotExactTaskPrReviewPolicy.from_mapping(review_policy.to_dict())
        assert loose_policy.policy_authenticated is False
        _reject(lambda: requirements.plan_pilot_exact_task_pr_review_evidence_requirements(loose_policy))

        # ReviewDecision is never sufficient to satisfy review policy by itself.
        assert result.github_review_decision in {"NONE", "APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED"}
        assert result.graphql_review_decision_sufficient_for_pass is False

        no_reviews = requirements._requirements_from_policy(
            _shape(count=0, dismiss=False, codeowners=False, last_push=False, conversations=False)
        )
        assert no_reviews["requirements_result"] == "SUPPORTED"
        assert no_reviews["exact_head_submitted_review_inventory_required"] is False
        assert no_reviews["approval_count_evidence_required"] is False
        assert no_reviews["latest_push_actor_evidence_required"] is False
        assert no_reviews["conversation_resolution_evidence_required"] is False

        codeowner = requirements._requirements_from_policy(
            _shape(count=2, dismiss=True, codeowners=True, last_push=False, conversations=True)
        )
        assert codeowner["exact_head_submitted_review_inventory_required"] is True
        assert codeowner["approval_count_evidence_required"] is True
        assert codeowner["stale_review_freshness_evidence_required"] is True
        assert codeowner["code_owner_change_set_evidence_required"] is True
        assert codeowner["code_owner_identity_evidence_required"] is True
        assert codeowner["latest_push_actor_evidence_required"] is False
        assert codeowner["conversation_resolution_evidence_required"] is True

        unsupported = requirements._requirements_from_policy(
            _shape(result="UNSUPPORTED", count=0, dismiss=False, codeowners=False, last_push=False, conversations=False)
        )
        assert unsupported["requirements_result"] == "UNSUPPORTED"
        assert unsupported["manual_or_new_policy_parser_required"] is True
        for key, value in unsupported.items():
            if key not in {"requirements_result", "manual_or_new_policy_parser_required"}:
                assert value is True

        # Receipt-level hash/authority/boolean tamper must fail structurally.
        tampered = result.to_dict(); tampered["merge_authorized"] = True
        _reject(lambda: requirements.PilotExactTaskPrReviewEvidenceRequirements.from_mapping(tampered))
        tampered = result.to_dict(); tampered["evidence_requirements_sha256"] = "4" * 64
        _reject(lambda: requirements.PilotExactTaskPrReviewEvidenceRequirements.from_mapping(tampered))
        tampered = result.to_dict(); tampered["effective_review_policy_sha256"] = "5" * 64
        _reject(lambda: requirements.PilotExactTaskPrReviewEvidenceRequirements.from_mapping(tampered))
        tampered = result.to_dict(); tampered["policy_dismiss_stale_reviews"] = 1
        _reject(lambda: requirements.PilotExactTaskPrReviewEvidenceRequirements.from_mapping(tampered))
        tampered = result.to_dict(); tampered["latest_push_actor_evidence_required"] = False
        _reject(lambda: requirements.PilotExactTaskPrReviewEvidenceRequirements.from_mapping(tampered))
        tampered = result.to_dict(); tampered["graphql_review_decision_sufficient_for_pass"] = True
        _reject(lambda: requirements.PilotExactTaskPrReviewEvidenceRequirements.from_mapping(tampered))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(requirements.PilotExactTaskPrReviewEvidenceRequirements.__dataclass_fields__)
        assert len(fields) == 57
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["graphql_review_decision_summary_only"]["const"] is True
        assert schema["properties"]["graphql_review_decision_sufficient_for_pass"]["const"] is False
        assert schema["properties"]["review_evidence_evaluation_required"]["const"] is True
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert tuple(inspect.signature(requirements.plan_pilot_exact_task_pr_review_evidence_requirements).parameters) == ("review_policy",)

        source = inspect.getsource(requirements)
        for forbidden in (
            "run_bounded_subprocess", "urllib.request", "requests.", "httpx.", "Authorization",
            "merge_pull_request(", "resolve_review_thread(", "add_review_to_pr(", "label_pr(",
            "request_pull_request_reviewers(",
        ):
            assert forbidden not in source
    finally:
        parent.parent.parent.parent._cleanup(items)
        temp.cleanup()


if __name__ == "__main__":
    run_contract()
