from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kaliv_dev_control.campaign import CampaignState, DevelopmentCampaign
from kaliv_dev_control.proposal import DraftProposalBuilder, ProposalError
from kaliv_dev_control.review import IndependentPolicyReviewer, ReviewRequest
from kaliv_dev_control.store import CampaignStore, CampaignStoreError
from test_campaign_review import command_receipt, patch_receipt, task


class StoreProposalTests(unittest.TestCase):
    def test_store_create_load_and_single_append_cas(self) -> None:
        value = task()
        campaign = DevelopmentCampaign.create("SDC-004", value)
        with tempfile.TemporaryDirectory() as temporary:
            store = CampaignStore(Path(temporary) / "campaigns")
            store.create(campaign)
            self.assertEqual(
                store.load("SDC-004").canonical_json(),
                campaign.canonical_json(),
            )

            previous = campaign.events[-1].event_sha256
            updated = campaign.advance(
                CampaignState.WORKSPACE_READY,
                evidence_sha256="2" * 64,
                detail="workspace ready",
            )
            store.save(updated, expected_previous_event_sha256=previous)
            self.assertEqual(
                store.load("SDC-004").state,
                CampaignState.WORKSPACE_READY,
            )

            with self.assertRaises(CampaignStoreError):
                store.save(updated, expected_previous_event_sha256=previous)

    def test_store_rejects_tampered_record(self) -> None:
        value = task()
        campaign = DevelopmentCampaign.create("SDC-004", value)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaigns"
            store = CampaignStore(root)
            path = store.create(campaign)
            path.write_text('{"schema":"tampered"}\n', encoding="utf-8")
            with self.assertRaises(CampaignStoreError):
                store.load("SDC-004")

    def test_store_rejects_existing_lock(self) -> None:
        value = task()
        campaign = DevelopmentCampaign.create("SDC-004", value)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaigns"
            root.mkdir()
            (root / ".SDC-004.lock").write_text("held\n", encoding="utf-8")
            with self.assertRaises(CampaignStoreError):
                CampaignStore(root).create(campaign)

    def _reviewed(self):
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
        campaign = DevelopmentCampaign.create("SDC-004", value)
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
        return value, campaign, request, verdict

    def test_proposal_is_deterministic_and_draft_only(self) -> None:
        value, campaign, request, verdict = self._reviewed()
        first = DraftProposalBuilder.build(
            task=value,
            campaign=campaign,
            request=request,
            verdict=verdict,
        )
        second = DraftProposalBuilder.build(
            task=value,
            campaign=campaign,
            request=request,
            verdict=verdict,
        )
        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertTrue(first.draft)
        self.assertEqual(first.merge_authority, "human")
        self.assertTrue(first.head_branch.startswith("kaliv-dev/"))
        self.assertIn("Semantic human review", first.body)

    def test_proposal_rejects_unreviewed_campaign(self) -> None:
        value, _, request, verdict = self._reviewed()
        unreviewed = DevelopmentCampaign.create("SDC-004", value)
        with self.assertRaises(ProposalError):
            DraftProposalBuilder.build(
                task=value,
                campaign=unreviewed,
                request=request,
                verdict=verdict,
            )


if __name__ == "__main__":
    unittest.main()
