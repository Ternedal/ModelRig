from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kaliv_dev_control.campaign import (
    CampaignError,
    CampaignState,
    DevelopmentCampaign,
)
from kaliv_dev_control.commands import CommandReceipt
from kaliv_dev_control.contract import (
    DevelopmentTask,
    MergeAuthority,
    Risk,
    TaskBudget,
)
from kaliv_dev_control.evidence import ScopeReceipt
from kaliv_dev_control.patch import PatchReceipt
from kaliv_dev_control.review import (
    DraftPrGate,
    IndependentPolicyReviewer,
    ReviewDecision,
    ReviewError,
    ReviewRequest,
    ReviewVerdict,
)


def task() -> DevelopmentTask:
    return DevelopmentTask(
        task_id="SD-003",
        repository="Ternedal/ModelRig",
        base_sha="a" * 40,
        goal="Build a review gate.",
        acceptance_criteria=("Required commands pass.",),
        risk=Risk.LOW,
        allowed_paths=("devcontrol/**",),
        protected_paths=(".github/**",),
        allowed_command_ids=("test.unit", "test.contract"),
        required_tests=("unit", "contract"),
        budget=TaskBudget(10, 500, 100, 3, 900, 1_000_000),
        merge_authority=MergeAuthority.HUMAN,
    )


def task_hash(value: DevelopmentTask) -> str:
    return hashlib.sha256(value.canonical_json().encode("utf-8")).hexdigest()


def patch_receipt(value: DevelopmentTask) -> PatchReceipt:
    digest = task_hash(value)
    scope = ScopeReceipt(
        task_id=value.task_id,
        task_sha256=digest,
        base_sha=value.base_sha,
        passed=True,
        changed_paths=("devcontrol/review.py",),
        violations=(),
        details=(),
        added_lines=10,
        deleted_lines=0,
    )
    return PatchReceipt(
        task_id=value.task_id,
        task_sha256=digest,
        base_sha=value.base_sha,
        patch_sha256="b" * 64,
        index_diff_sha256="c" * 64,
        scope=scope,
        applied=True,
    )


def command_receipt(
    value: DevelopmentTask,
    command_id: str,
    *,
    passed: bool,
) -> CommandReceipt:
    digest = task_hash(value)
    return CommandReceipt(
        task_id=value.task_id,
        task_sha256=digest,
        base_sha=value.base_sha,
        command_id=command_id,
        argv_sha256="d" * 64,
        cwd=".",
        returncode=0 if passed else 1,
        stdout_sha256="e" * 64,
        stderr_sha256="f" * 64,
        output_bytes=10,
        duration_ms=5,
        workspace_before_sha256="1" * 64,
        workspace_after_sha256="1" * 64,
        workspace_unchanged=True,
        workspace_reset=False,
        passed=passed,
    )


class CampaignReviewTests(unittest.TestCase):
    def test_campaign_allows_only_ordered_hash_chained_transitions(self) -> None:
        value = task()
        campaign = DevelopmentCampaign.create("SDC-003", value)
        for state, evidence in (
            (CampaignState.WORKSPACE_READY, "2" * 64),
            (CampaignState.PATCH_STAGED, "3" * 64),
            (CampaignState.TESTED, "4" * 64),
            (CampaignState.REVIEWED, "5" * 64),
            (CampaignState.READY_FOR_DRAFT_PR, "6" * 64),
        ):
            campaign = campaign.advance(
                state,
                evidence_sha256=evidence,
                detail=f"entered {state.value}",
            )
        campaign.verify()
        self.assertEqual(campaign.state, CampaignState.READY_FOR_DRAFT_PR)
        self.assertEqual(len(campaign.events), 6)

    def test_campaign_rejects_skipped_or_terminal_transition(self) -> None:
        campaign = DevelopmentCampaign.create("SDC-003", task())
        with self.assertRaises(CampaignError):
            campaign.advance(
                CampaignState.PATCH_STAGED,
                evidence_sha256="2" * 64,
                detail="skip workspace",
            )
        failed = campaign.advance(
            CampaignState.FAILED,
            evidence_sha256="3" * 64,
            detail="failed",
        )
        with self.assertRaises(CampaignError):
            failed.advance(
                CampaignState.WORKSPACE_READY,
                evidence_sha256="4" * 64,
                detail="illegal recovery",
            )

    def test_campaign_detects_tampered_event(self) -> None:
        campaign = DevelopmentCampaign.create("SDC-003", task()).advance(
            CampaignState.WORKSPACE_READY,
            evidence_sha256="2" * 64,
            detail="workspace ready",
        )
        payload = copy.deepcopy(campaign.to_dict())
        payload["events"][1]["detail"] = "tampered"
        with self.assertRaises(CampaignError):
            DevelopmentCampaign.from_mapping(payload)

    def test_review_request_requires_every_required_command(self) -> None:
        value = task()
        with self.assertRaises(ReviewError):
            ReviewRequest.from_evidence(
                task=value,
                developer_actor_id="developer-a",
                patch=patch_receipt(value),
                commands=(command_receipt(value, "test.unit", passed=True),),
            )

    def test_reviewer_must_be_independent(self) -> None:
        value = task()
        request = ReviewRequest.from_evidence(
            task=value,
            developer_actor_id="developer-a",
            patch=patch_receipt(value),
            commands=(
                command_receipt(value, "test.unit", passed=True),
                command_receipt(value, "test.contract", passed=True),
            ),
        )
        with self.assertRaises(ReviewError):
            IndependentPolicyReviewer().review(
                request,
                reviewer_actor_id="developer-a",
            )

    def test_failed_required_command_requests_changes(self) -> None:
        value = task()
        request = ReviewRequest.from_evidence(
            task=value,
            developer_actor_id="developer-a",
            patch=patch_receipt(value),
            commands=(
                command_receipt(value, "test.unit", passed=True),
                command_receipt(value, "test.contract", passed=False),
            ),
        )
        verdict = IndependentPolicyReviewer().review(
            request,
            reviewer_actor_id="reviewer-b",
        )
        self.assertEqual(verdict.decision, ReviewDecision.REQUEST_CHANGES)
        self.assertFalse(DraftPrGate.ready(value, request, verdict))

    def test_green_independent_review_opens_only_draft_pr_gate(self) -> None:
        value = task()
        request = ReviewRequest.from_evidence(
            task=value,
            developer_actor_id="developer-a",
            patch=patch_receipt(value),
            commands=(
                command_receipt(value, "test.unit", passed=True),
                command_receipt(value, "test.contract", passed=True),
            ),
        )
        verdict = IndependentPolicyReviewer().review(
            request,
            reviewer_actor_id="reviewer-b",
        )
        self.assertEqual(verdict.decision, ReviewDecision.APPROVE)
        self.assertTrue(DraftPrGate.ready(value, request, verdict))
        self.assertEqual(value.merge_authority, MergeAuthority.HUMAN)

    def test_verdict_for_another_request_is_rejected(self) -> None:
        value = task()
        request = ReviewRequest.from_evidence(
            task=value,
            developer_actor_id="developer-a",
            patch=patch_receipt(value),
            commands=(
                command_receipt(value, "test.unit", passed=True),
                command_receipt(value, "test.contract", passed=True),
            ),
        )
        verdict = ReviewVerdict(
            review_request_sha256="9" * 64,
            developer_actor_id="developer-a",
            reviewer_actor_id="reviewer-b",
            independent=True,
            decision=ReviewDecision.APPROVE,
            findings=(),
        )
        self.assertFalse(DraftPrGate.ready(value, request, verdict))


if __name__ == "__main__":
    unittest.main()
