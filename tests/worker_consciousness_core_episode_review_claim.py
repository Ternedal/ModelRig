#!/usr/bin/env python3
"""C30-N trusted review claim service tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    EpisodeExperienceReviewError,
    EpisodeExperienceReviewMailbox,
    EpisodeReviewClaimError,
    ExperienceCandidate,
    TrustedEpisodeExperienceReview,
    TrustedEpisodeReviewClaimService,
    anchor_from_clock,
    append_episode_moment,
    build_episode_experience_review_request,
    build_episode_moment,
    close_experience_episode,
    derive_episode_closure_evidence,
    episode_closure_evidence_ref,
    episode_experience_review_request_ref,
    open_experience_episode,
)


SELF = "self-" + "a" * 32
PERSON = "person-" + "b" * 32
PERSON_REV = "person-r0007"
EPOCH = "epoch-" + "1" * 32
CYCLE = "cycle-" + "2" * 32


def anchor(sequence: int, *, event_ref: str):
    sample = ClockSample(
        schema="kaliv-consciousness-core/clock-sample/v1",
        sample_id="clock-" + f"{sequence:032x}",
        wall_time_unix_ms=1_700_000_000_000 + sequence * 1000,
        timezone_name="Europe/Copenhagen",
        utc_offset_minutes=120,
        local_hour=18,
        monotonic_ms=sequence * 1000,
        runtime_epoch_id=EPOCH,
        sampled_sequence=sequence,
        source_ref=f"trusted:c30n:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref=event_ref)


def review_request(marker: str):
    start = int(marker, 16) * 10 + 1
    episode = open_experience_episode(
        self_id=SELF,
        person_revision=PERSON_REV,
        opening_anchor=anchor(
            start,
            event_ref=f"episode-open:c30n:{marker}",
        ),
        reason="SESSION_START",
    )
    episode = append_episode_moment(
        episode,
        build_episode_moment(
            kind="WORLD_EVIDENCE",
            source_ref=f"world:c30n:{marker}",
            anchor=anchor(
                start + 1,
                event_ref=f"world:c30n:{marker}",
            ),
            salience=0.8,
            active_goal_refs=["goal:review"],
            participant_refs=["actor:user"],
        ),
    )
    closed = close_experience_episode(
        episode,
        closing_anchor=anchor(
            start + 2,
            event_ref=f"episode-close:c30n:{marker}",
        ),
        reason="FOCUS_SHIFT",
    )
    evidence = derive_episode_closure_evidence(
        closed,
        boundary_signal_ref=(
            "episode-boundary-signal:" + marker * 64
        ),
    )
    built = build_episode_experience_review_request(evidence)
    if built is None:
        raise AssertionError("non-empty episode must create review request")
    return built


def candidate(request):
    evidence = request.closure_evidence
    return ExperienceCandidate(
        schema="kaliv-consciousness-core/experience-candidate/v1",
        experience_id="exp-" + "3" * 32,
        cycle_id=CYCLE,
        self_id=SELF,
        person_id=PERSON,
        person_revision=PERSON_REV,
        kind="SHARED_EVENT",
        event_ref=evidence.closed_episode_ref,
        participant_refs=["actor:user"],
        self_state_before_ref="self-state:before",
        self_state_after_ref="self-state:after",
        active_goal_refs=["goal:review"],
        intention_ref=None,
        prediction_refs=[],
        outcome_refs=[],
        prediction_error_refs=[],
        personality_state_ref="personality-state:c30n",
        world_state_delta_refs=[],
        significance=0.8,
        provenance_kind="shared_event",
        sensitivity="private",
        source_refs=[
            episode_closure_evidence_ref(evidence),
            evidence.closed_episode_ref,
        ],
        completed_turn_source_ref=None,
        production_activation=False,
    )


def review(request, item=None, *, decision="APPROVE", marker="4"):
    return TrustedEpisodeExperienceReview(
        schema=(
            "kaliv-consciousness-core/"
            "trusted-episode-experience-review/v1"
        ),
        review_id="erev-" + marker * 32,
        closure_evidence_ref=request.review_plan.closure_evidence_ref,
        decision=decision,
        authority="operator_explicit",
        reviewer_source_ref=f"operator-review:c30n:{marker}",
        reviewed_candidate_ref=(
            None if item is None else f"experience:{item.experience_id}"
        ),
        raw_text_asserted_from_closure_evidence=False,
        completed_turn_authority_asserted=False,
        production_activation=False,
    )


class EpisodeReviewClaimServiceTests(unittest.TestCase):
    def test_claim_keeps_request_pending(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("1")
        mailbox.enqueue(request)
        service = TrustedEpisodeReviewClaimService(mailbox=mailbox)
        request_ref = episode_experience_review_request_ref(request)

        claimed_request, claim = service.claim_exact(
            request_id=request.request_id,
            expected_request_ref=request_ref,
        )

        self.assertEqual(claimed_request, request)
        self.assertEqual(claim.request_ref, request_ref)
        self.assertFalse(claim.request_consumed)
        self.assertEqual(mailbox.snapshot.pending_count, 1)
        self.assertEqual(service.snapshot.claimed_count, 1)

    def test_abandon_releases_claim_without_consuming_request(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("2")
        mailbox.enqueue(request)
        service = TrustedEpisodeReviewClaimService(mailbox=mailbox)
        request_ref = episode_experience_review_request_ref(request)
        _, claim = service.claim_exact(
            request_id=request.request_id,
            expected_request_ref=request_ref,
        )

        receipt = service.abandon(
            claim_id=claim.claim_id,
            expected_request_ref=request_ref,
        )

        self.assertTrue(receipt.request_still_pending)
        self.assertTrue(receipt.claim_removed)
        self.assertEqual(mailbox.snapshot.pending_count, 1)
        self.assertEqual(service.snapshot.claimed_count, 0)

        _, reclaimed = service.claim_exact(
            request_id=request.request_id,
            expected_request_ref=request_ref,
        )
        self.assertEqual(reclaimed.claim_id, claim.claim_id)

    def test_invalid_semantic_decision_does_not_consume_claimed_request(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("3")
        mailbox.enqueue(request)
        service = TrustedEpisodeReviewClaimService(mailbox=mailbox)
        request_ref = episode_experience_review_request_ref(request)
        _, claim = service.claim_exact(
            request_id=request.request_id,
            expected_request_ref=request_ref,
        )
        bad_candidate = candidate(request).model_copy(
            update={"event_ref": "experience-episode:" + "f" * 64}
        )
        trusted = review(request, bad_candidate, marker="5")

        with self.assertRaises(EpisodeExperienceReviewError):
            service.commit_decision(
                claim_id=claim.claim_id,
                expected_request_ref=request_ref,
                review=trusted,
                candidate=bad_candidate,
            )

        self.assertEqual(mailbox.snapshot.pending_count, 1)
        self.assertEqual(service.snapshot.claimed_count, 1)

    def test_approve_preflights_then_consumes_and_applies(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("4")
        mailbox.enqueue(request)
        service = TrustedEpisodeReviewClaimService(mailbox=mailbox)
        request_ref = episode_experience_review_request_ref(request)
        _, claim = service.claim_exact(
            request_id=request.request_id,
            expected_request_ref=request_ref,
        )
        item = candidate(request)
        trusted = review(request, item, marker="6")

        receipt = service.commit_decision(
            claim_id=claim.claim_id,
            expected_request_ref=request_ref,
            review=trusted,
            candidate=item,
        )

        self.assertTrue(receipt.semantic_preflight_passed)
        self.assertTrue(receipt.request_consumed_after_preflight)
        self.assertTrue(receipt.claim_removed)
        self.assertEqual(receipt.decision_receipt.decision, "APPROVE")
        self.assertEqual(
            receipt.decision_receipt.evaluation.c7_handoff.status,
            "trusted_review_required",
        )
        self.assertEqual(mailbox.snapshot.pending_count, 0)
        self.assertEqual(service.snapshot.claimed_count, 0)

    def test_reject_consumes_only_when_explicit_reject_is_ready(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("5")
        mailbox.enqueue(request)
        service = TrustedEpisodeReviewClaimService(mailbox=mailbox)
        request_ref = episode_experience_review_request_ref(request)
        _, claim = service.claim_exact(
            request_id=request.request_id,
            expected_request_ref=request_ref,
        )
        trusted = review(
            request,
            decision="REJECT",
            marker="7",
        )

        receipt = service.commit_decision(
            claim_id=claim.claim_id,
            expected_request_ref=request_ref,
            review=trusted,
        )

        self.assertEqual(receipt.decision_receipt.decision, "REJECT")
        self.assertFalse(
            receipt.decision_receipt.evaluation.accepted_for_c7_evaluation
        )
        self.assertEqual(mailbox.snapshot.pending_count, 0)

    def test_double_claim_fails_without_consuming(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("6")
        mailbox.enqueue(request)
        service = TrustedEpisodeReviewClaimService(mailbox=mailbox)
        request_ref = episode_experience_review_request_ref(request)
        service.claim_exact(
            request_id=request.request_id,
            expected_request_ref=request_ref,
        )

        with self.assertRaisesRegex(
            EpisodeReviewClaimError,
            "already claimed",
        ):
            service.claim_exact(
                request_id=request.request_id,
                expected_request_ref=request_ref,
            )

        self.assertEqual(mailbox.snapshot.pending_count, 1)
        self.assertEqual(service.snapshot.claimed_count, 1)

    def test_wrong_claim_ref_does_not_release_or_consume(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("7")
        mailbox.enqueue(request)
        service = TrustedEpisodeReviewClaimService(mailbox=mailbox)
        request_ref = episode_experience_review_request_ref(request)
        _, claim = service.claim_exact(
            request_id=request.request_id,
            expected_request_ref=request_ref,
        )

        with self.assertRaisesRegex(
            EpisodeReviewClaimError,
            "claim request ref mismatch",
        ):
            service.abandon(
                claim_id=claim.claim_id,
                expected_request_ref=(
                    "episode-experience-review-request:" + "f" * 64
                ),
            )

        self.assertEqual(mailbox.snapshot.pending_count, 1)
        self.assertEqual(service.snapshot.claimed_count, 1)

    def test_close_clears_claims_but_does_not_consume_mailbox(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("8")
        mailbox.enqueue(request)
        service = TrustedEpisodeReviewClaimService(mailbox=mailbox)
        request_ref = episode_experience_review_request_ref(request)
        service.claim_exact(
            request_id=request.request_id,
            expected_request_ref=request_ref,
        )

        service.close()

        self.assertTrue(service.snapshot.closed)
        self.assertEqual(service.snapshot.claimed_count, 0)
        self.assertEqual(mailbox.snapshot.pending_count, 1)
        with self.assertRaisesRegex(
            EpisodeReviewClaimError,
            "is closed",
        ):
            service.claim_exact(
                request_id=request.request_id,
                expected_request_ref=request_ref,
            )

    def test_claim_service_adds_no_timer_or_durable_recovery(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("9")
        mailbox.enqueue(request)
        service = TrustedEpisodeReviewClaimService(mailbox=mailbox)
        _, claim = service.claim_exact(
            request_id=request.request_id,
            expected_request_ref=episode_experience_review_request_ref(
                request
            ),
        )

        self.assertFalse(claim.durable)
        self.assertFalse(claim.automatic_expiry)
        self.assertFalse(claim.timer_authority)
        source = (
            ROOT
            / "worker"
            / "app"
            / "consciousness_core"
            / "episode_review_claim.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "APIRouter",
            "import sqlite3",
            "create_task(",
            "threading",
            "asyncio",
            "schedule_service",
            "retry",
            "sleep(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
