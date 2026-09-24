#!/usr/bin/env python3
"""C30-R privacy-safe aggregate episode review observability tests."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    EPISODE_REVIEW_RUNTIME_FLAG,
    MAX_OBSERVABILITY_COUNTER,
    EpisodeExperienceReviewMailbox,
    EpisodeReviewClaimError,
    EpisodeReviewObservability,
    ExperienceCandidate,
    TrustedEpisodeExperienceReview,
    TrustedEpisodeReviewClaimService,
    anchor_from_clock,
    append_episode_moment,
    build_episode_experience_review_request,
    build_episode_moment,
    build_episode_review_status,
    close_experience_episode,
    derive_episode_closure_evidence,
    episode_closure_evidence_ref,
    episode_experience_review_request_ref,
    open_experience_episode,
    production_episode_review_runtime_factory,
    publish_episode_closure_review,
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
        source_ref=f"trusted:c30r:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref=event_ref)


def evidence(marker: str):
    start = int(marker, 16) * 10 + 1
    episode = open_experience_episode(
        self_id=SELF,
        person_revision=PERSON_REV,
        opening_anchor=anchor(
            start,
            event_ref=f"episode-open:c30r:{marker}",
        ),
        reason="SESSION_START",
    )
    episode = append_episode_moment(
        episode,
        build_episode_moment(
            kind="WORLD_EVIDENCE",
            source_ref=f"world:c30r:{marker}",
            anchor=anchor(
                start + 1,
                event_ref=f"world:c30r:{marker}",
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
            event_ref=f"episode-close:c30r:{marker}",
        ),
        reason="FOCUS_SHIFT",
    )
    return derive_episode_closure_evidence(
        closed,
        boundary_signal_ref=(
            "episode-boundary-signal:" + marker * 64
        ),
    )


def candidate(request, *, marker: str):
    value = request.closure_evidence
    return ExperienceCandidate(
        schema="kaliv-consciousness-core/experience-candidate/v1",
        experience_id="exp-" + marker * 32,
        cycle_id=CYCLE,
        self_id=SELF,
        person_id=PERSON,
        person_revision=PERSON_REV,
        kind="SHARED_EVENT",
        event_ref=value.closed_episode_ref,
        participant_refs=["actor:user"],
        self_state_before_ref="self-state:before",
        self_state_after_ref="self-state:after",
        active_goal_refs=["goal:review"],
        intention_ref=None,
        prediction_refs=[],
        outcome_refs=[],
        prediction_error_refs=[],
        personality_state_ref="personality-state:c30r",
        world_state_delta_refs=[],
        significance=0.8,
        provenance_kind="shared_event",
        sensitivity="private",
        source_refs=[
            episode_closure_evidence_ref(value),
            value.closed_episode_ref,
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
        reviewer_source_ref=f"operator-review:c30r:{marker}",
        reviewed_candidate_ref=(
            None if item is None else f"experience:{item.experience_id}"
        ),
        raw_text_asserted_from_closure_evidence=False,
        completed_turn_authority_asserted=False,
        production_activation=False,
    )


class EpisodeReviewObservabilityTests(unittest.TestCase):
    def test_snapshot_is_zeroed_and_stores_no_identifiers_or_history(self):
        observability = EpisodeReviewObservability()

        snapshot = observability.snapshot
        payload = snapshot.model_dump_json()

        self.assertEqual(snapshot.publication_enqueued, 0)
        self.assertEqual(snapshot.claims_succeeded, 0)
        self.assertEqual(snapshot.abandons_succeeded, 0)
        self.assertEqual(snapshot.approvals_succeeded, 0)
        self.assertEqual(snapshot.rejections_succeeded, 0)
        self.assertFalse(snapshot.request_ids_stored)
        self.assertFalse(snapshot.request_refs_stored)
        self.assertFalse(snapshot.claim_ids_stored)
        self.assertFalse(snapshot.closure_evidence_stored)
        self.assertFalse(snapshot.timestamps_stored)
        self.assertFalse(snapshot.event_history_stored)
        self.assertFalse(snapshot.raw_text_stored)
        self.assertFalse(snapshot.raw_chain_of_thought_stored)
        self.assertNotIn("ereq-", payload)
        self.assertNotIn(
            "episode-experience-review-request:",
            payload,
        )
        self.assertNotIn("eclaim-", payload)

    def test_counters_saturate_at_signed_64_bit_max(self):
        observability = EpisodeReviewObservability()
        observability._claims_succeeded = MAX_OBSERVABILITY_COUNTER

        observability.record_claim()

        self.assertEqual(
            observability.snapshot.claims_succeeded,
            MAX_OBSERVABILITY_COUNTER,
        )

    def test_publication_outcomes_are_counted_once_each(self):
        observability = EpisodeReviewObservability()
        mailbox = EpisodeExperienceReviewMailbox(capacity=1)
        first = evidence("1")
        second = evidence("2")

        publish_episode_closure_review(
            None,
            mailbox,
            observability,
        )
        publish_episode_closure_review(
            first,
            mailbox,
            observability,
        )
        publish_episode_closure_review(
            first,
            mailbox,
            observability,
        )
        publish_episode_closure_review(
            second,
            mailbox,
            observability,
        )

        snapshot = observability.snapshot
        self.assertEqual(snapshot.publication_not_applicable, 1)
        self.assertEqual(snapshot.publication_enqueued, 1)
        self.assertEqual(snapshot.publication_duplicate, 1)
        self.assertEqual(snapshot.publication_capacity_reached, 1)

    def test_claim_and_abandon_count_only_successful_transitions(self):
        observability = EpisodeReviewObservability()
        mailbox = EpisodeExperienceReviewMailbox()
        value = build_episode_experience_review_request(evidence("3"))
        mailbox.enqueue(value)
        service = TrustedEpisodeReviewClaimService(
            mailbox=mailbox,
            observability=observability,
        )
        request_ref = episode_experience_review_request_ref(value)

        with self.assertRaises(EpisodeReviewClaimError):
            service.claim_exact(
                request_id=value.request_id,
                expected_request_ref=(
                    "episode-experience-review-request:" + "f" * 64
                ),
            )
        self.assertEqual(observability.snapshot.claims_succeeded, 0)

        _, claim = service.claim_exact(
            request_id=value.request_id,
            expected_request_ref=request_ref,
        )
        self.assertEqual(observability.snapshot.claims_succeeded, 1)

        with self.assertRaises(EpisodeReviewClaimError):
            service.abandon(
                claim_id=claim.claim_id,
                expected_request_ref=(
                    "episode-experience-review-request:" + "e" * 64
                ),
            )
        self.assertEqual(observability.snapshot.abandons_succeeded, 0)

        service.abandon(
            claim_id=claim.claim_id,
            expected_request_ref=request_ref,
        )
        self.assertEqual(observability.snapshot.abandons_succeeded, 1)

    def test_approve_and_reject_count_only_after_successful_commit(self):
        observability = EpisodeReviewObservability()
        mailbox = EpisodeExperienceReviewMailbox(capacity=2)
        approve_request = build_episode_experience_review_request(
            evidence("4")
        )
        reject_request = build_episode_experience_review_request(
            evidence("5")
        )
        mailbox.enqueue(approve_request)
        mailbox.enqueue(reject_request)
        service = TrustedEpisodeReviewClaimService(
            mailbox=mailbox,
            observability=observability,
        )

        approve_ref = episode_experience_review_request_ref(
            approve_request
        )
        _, approve_claim = service.claim_exact(
            request_id=approve_request.request_id,
            expected_request_ref=approve_ref,
        )
        item = candidate(approve_request, marker="6")
        trusted = review(
            approve_request,
            item,
            decision="APPROVE",
            marker="6",
        )

        bad_item = item.model_copy(
            update={"event_ref": "experience-episode:" + "f" * 64}
        )
        with self.assertRaises(Exception):
            service.commit_decision(
                claim_id=approve_claim.claim_id,
                expected_request_ref=approve_ref,
                review=trusted,
                candidate=bad_item,
            )
        self.assertEqual(observability.snapshot.approvals_succeeded, 0)

        service.commit_decision(
            claim_id=approve_claim.claim_id,
            expected_request_ref=approve_ref,
            review=trusted,
            candidate=item,
        )
        self.assertEqual(observability.snapshot.approvals_succeeded, 1)

        reject_ref = episode_experience_review_request_ref(
            reject_request
        )
        _, reject_claim = service.claim_exact(
            request_id=reject_request.request_id,
            expected_request_ref=reject_ref,
        )
        service.commit_decision(
            claim_id=reject_claim.claim_id,
            expected_request_ref=reject_ref,
            review=review(
                reject_request,
                decision="REJECT",
                marker="7",
            ),
        )
        snapshot = observability.snapshot
        self.assertEqual(snapshot.approvals_succeeded, 1)
        self.assertEqual(snapshot.rejections_succeeded, 1)

    def test_production_runtime_shares_one_observability_recorder(self):
        old = os.environ.get(EPISODE_REVIEW_RUNTIME_FLAG)
        try:
            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = "1"
            app = SimpleNamespace(state=SimpleNamespace())
            runtime = production_episode_review_runtime_factory(app)

            self.assertIsNotNone(runtime.observability)
            value = build_episode_experience_review_request(
                evidence("8")
            )
            runtime.mailbox.enqueue(value)
            request_ref = episode_experience_review_request_ref(value)
            runtime.service.claim_exact(
                request_id=value.request_id,
                expected_request_ref=request_ref,
            )
            self.assertEqual(
                runtime.observability.snapshot.claims_succeeded,
                1,
            )
        finally:
            if old is None:
                os.environ.pop(EPISODE_REVIEW_RUNTIME_FLAG, None)
            else:
                os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = old

    def test_status_rejects_mismatched_runtime_observability_binding(self):
        runtime_observability = EpisodeReviewObservability()
        wrong_observability = EpisodeReviewObservability()
        mailbox = EpisodeExperienceReviewMailbox()
        service = TrustedEpisodeReviewClaimService(
            mailbox=mailbox,
            observability=runtime_observability,
        )
        from app.consciousness_core import EpisodeReviewRuntime

        runtime = EpisodeReviewRuntime(
            mailbox=mailbox,
            service=service,
            observability=runtime_observability,
        )
        app = SimpleNamespace(
            state=SimpleNamespace(
                consciousness_episode_review_runtime=runtime,
                consciousness_episode_review_mailbox=mailbox,
                consciousness_episode_review_service=service,
                consciousness_episode_review_observability=(
                    wrong_observability
                ),
            )
        )

        status = build_episode_review_status(app)

        self.assertEqual(status.state, "RUNTIME_UNAVAILABLE")

    def test_status_exposes_aggregate_snapshot_without_identifiers(self):
        observability = EpisodeReviewObservability()
        mailbox = EpisodeExperienceReviewMailbox()
        service = TrustedEpisodeReviewClaimService(
            mailbox=mailbox,
            observability=observability,
        )
        from app.consciousness_core import EpisodeReviewRuntime

        runtime = EpisodeReviewRuntime(
            mailbox=mailbox,
            service=service,
            observability=observability,
        )
        value = build_episode_experience_review_request(evidence("9"))
        mailbox.enqueue(value)
        request_ref = episode_experience_review_request_ref(value)
        _, claim = service.claim_exact(
            request_id=value.request_id,
            expected_request_ref=request_ref,
        )
        app = SimpleNamespace(
            state=SimpleNamespace(
                consciousness_episode_review_runtime=runtime,
                consciousness_episode_review_mailbox=mailbox,
                consciousness_episode_review_service=service,
                consciousness_episode_review_observability=observability,
            )
        )

        status = build_episode_review_status(app)
        payload = status.model_dump_json()

        self.assertTrue(status.observability_present)
        self.assertEqual(
            status.observability.claims_succeeded,
            1,
        )
        self.assertNotIn(value.request_id, payload)
        self.assertNotIn(request_ref, payload)
        self.assertNotIn(claim.claim_id, payload)


if __name__ == "__main__":
    unittest.main()
