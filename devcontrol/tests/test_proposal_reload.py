from __future__ import annotations

import unittest

from kaliv_dev_control.campaign import CampaignState, DevelopmentCampaign
from kaliv_dev_control.proposal import (
    DraftProposalBuilder,
    DraftPullRequestProposal,
    ProposalError,
)
from kaliv_dev_control.review import IndependentPolicyReviewer, ReviewRequest
from test_campaign_review import command_receipt, patch_receipt, task


class ProposalReloadTests(unittest.TestCase):
    def _proposal(self) -> DraftPullRequestProposal:
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
        campaign = DevelopmentCampaign.create("SDC-005", value)
        for state, evidence in (
            (CampaignState.WORKSPACE_READY, "2" * 64),
            (CampaignState.PATCH_STAGED, "3" * 64),
            (CampaignState.TESTED, "4" * 64),
            (CampaignState.REVIEWED, "5" * 64),
        ):
            campaign = campaign.advance(
                state,
                evidence_sha256=evidence,
                detail=state.value,
            )
        return DraftProposalBuilder.build(
            task=value,
            campaign=campaign,
            request=request,
            verdict=verdict,
        )

    def test_proposal_roundtrip_preserves_canonical_hash(self) -> None:
        proposal = self._proposal()
        restored = DraftPullRequestProposal.from_mapping(proposal.to_dict())
        self.assertEqual(restored.canonical_json(), proposal.canonical_json())
        self.assertEqual(restored.proposal_sha256, proposal.proposal_sha256)

    def test_proposal_reload_rejects_authority_tampering(self) -> None:
        payload = self._proposal().to_dict()
        payload["draft"] = False
        with self.assertRaises(ProposalError):
            DraftPullRequestProposal.from_mapping(payload)


if __name__ == "__main__":
    unittest.main()
