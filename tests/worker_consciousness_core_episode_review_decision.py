#!/usr/bin/env python3
"""C30-M exact episode review decision application tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    EpisodeExperienceReviewMailbox,
    EpisodeReviewDecisionError,
    ExperienceCandidate,
    TrustedEpisodeExperienceReview,
    TrustedEpisodeReviewAdapter,
    TrustedEpisodeReviewDecisionApplier,
    anchor_from_clock,
    append_episode_moment,
    build_episode_experience_review_request,
    build_episode_moment,
    close_experience_episode,
    derive_episode_closure_evidence,
    episode_closure_evidence_ref,
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
        source_ref=f"trusted:c30m:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref=event_ref)


def request(marker: str = "1"):
    episode = open_experience_episode(
        self_id=SELF,
        person_revision=PERSON_REV,
        opening_anchor=anchor(
            1,
            event_ref=f"episode-open:c30m:{marker}",
        ),
        reason="SESSION_START",
    )
    episode = append_episode_moment(
        episode,
        build_episode_moment(
            kind="WORLD_EVIDENCE",
            source_ref=f"world:c30m:{marker}",
            anchor=anchor(
                2,
                event_ref=f"world:c30m:{marker}",
            ),
            salience=0.8,
            active_goal_refs=["goal:review"],
            participant_refs=["actor:user"],
        ),
    )
    closed = close_experience_episode(
        episode,
        closing_anchor=anchor(
            3,
            event_ref=f"episode-close:c30m:{marker}",
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


def consume(built):
    mailbox = EpisodeExperienceReviewMailbox()
    mailbox.enqueue(built)
    adapter = TrustedEpisodeReviewAdapter(mailbox=mailbox)
    item = adapter.list_pending().items[0]
    consumed, receipt = adapter.consume_exact(
        request_id=item.request_id,
        expected_request_ref=item.request_ref,
    )
    return consumed, receipt


def candidate(built):
    evidence = built.closure_evidence
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
        personality_state_ref="personality-state:c30m",
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


def review(built, item=None, *, decision="APPROVE", marker="4"):
    return TrustedEpisodeExperienceReview(
        schema=(
            "kaliv-consciousness-core/"
            "trusted-episode-experience-review/v1"
        ),
        review_id="erev-" + marker * 32,
        closure_evidence_ref=built.review_plan.closure_evidence_ref,
        decision=decision,
        authority="operator_explicit",
        reviewer_source_ref=f"operator-review:c30m:{marker}",
        reviewed_candidate_ref=(
            None
            if item is None
            else f"experience:{item.experience_id}"
        ),
        raw_text_asserted_from_closure_evidence=False,
        completed_turn_authority_asserted=False,
        production_activation=False,
    )


class EpisodeReviewDecisionTests(unittest.TestCase):
    def test_approve_binds_consumed_request_to_c7_review_required(self):
        built = request("1")
        consumed, consume_receipt = consume(built)
        item = candidate(consumed)
        trusted = review(consumed, item)
        applier = TrustedEpisodeReviewDecisionApplier()

        receipt = applier.apply(
            request=consumed,
            consume_receipt=consume_receipt,
            review=trusted,
            candidate=item,
        )

        self.assertEqual(receipt.decision, "APPROVE")
        self.assertTrue(receipt.exact_consume_binding)
        self.assertTrue(receipt.semantic_review_applied)
        self.assertTrue(
            receipt.evaluation.accepted_for_c7_evaluation
        )
        self.assertEqual(
            receipt.evaluation.c7_handoff.status,
            "trusted_review_required",
        )
        self.assertFalse(receipt.memory4_called)
        self.assertFalse(receipt.durable)
        self.assertFalse(receipt.durable_memory_write_authority)
        self.assertEqual(applier.snapshot.applied_count, 1)

    def test_reject_is_terminal_review_without_candidate(self):
        built = request("2")
        consumed, consume_receipt = consume(built)
        trusted = review(
            consumed,
            decision="REJECT",
            marker="5",
        )
        applier = TrustedEpisodeReviewDecisionApplier()

        receipt = applier.apply(
            request=consumed,
            consume_receipt=consume_receipt,
            review=trusted,
        )

        self.assertEqual(receipt.decision, "REJECT")
        self.assertFalse(
            receipt.evaluation.accepted_for_c7_evaluation
        )
        self.assertIsNone(receipt.evaluation.candidate_ref)
        self.assertIsNone(receipt.evaluation.c7_handoff)
        self.assertEqual(applier.snapshot.applied_count, 1)

    def test_same_consumed_request_cannot_be_applied_twice(self):
        built = request("3")
        consumed, consume_receipt = consume(built)
        item = candidate(consumed)
        trusted = review(consumed, item, marker="6")
        applier = TrustedEpisodeReviewDecisionApplier()

        applier.apply(
            request=consumed,
            consume_receipt=consume_receipt,
            review=trusted,
            candidate=item,
        )
        with self.assertRaisesRegex(
            EpisodeReviewDecisionError,
            "already been applied",
        ):
            applier.apply(
                request=consumed,
                consume_receipt=consume_receipt,
                review=trusted,
                candidate=item,
            )

        self.assertEqual(applier.snapshot.applied_count, 1)

    def test_wrong_consume_binding_fails_without_burning_request(self):
        first = request("4")
        second = request("5")
        consumed_first, receipt_first = consume(first)
        consumed_second, receipt_second = consume(second)
        item = candidate(consumed_first)
        trusted = review(consumed_first, item, marker="7")
        applier = TrustedEpisodeReviewDecisionApplier()

        with self.assertRaisesRegex(
            EpisodeReviewDecisionError,
            "another review request",
        ):
            applier.apply(
                request=consumed_first,
                consume_receipt=receipt_second,
                review=trusted,
                candidate=item,
            )

        self.assertEqual(applier.snapshot.applied_count, 0)
        success = applier.apply(
            request=consumed_first,
            consume_receipt=receipt_first,
            review=trusted,
            candidate=item,
        )
        self.assertEqual(success.decision, "APPROVE")
        self.assertEqual(applier.snapshot.applied_count, 1)
        self.assertNotEqual(
            receipt_first.request_ref,
            receipt_second.request_ref,
        )
        self.assertNotEqual(
            consumed_first.request_id,
            consumed_second.request_id,
        )

    def test_wrong_review_binding_fails_without_burning_request(self):
        built = request("6")
        consumed, consume_receipt = consume(built)
        item = candidate(consumed)
        wrong = TrustedEpisodeExperienceReview(
            schema=(
                "kaliv-consciousness-core/"
                "trusted-episode-experience-review/v1"
            ),
            review_id="erev-" + "8" * 32,
            closure_evidence_ref=(
                "episode-closure-evidence:" + "f" * 64
            ),
            decision="APPROVE",
            authority="operator_explicit",
            reviewer_source_ref="operator-review:c30m:wrong",
            reviewed_candidate_ref=f"experience:{item.experience_id}",
            raw_text_asserted_from_closure_evidence=False,
            completed_turn_authority_asserted=False,
            production_activation=False,
        )
        applier = TrustedEpisodeReviewDecisionApplier()

        with self.assertRaisesRegex(
            EpisodeReviewDecisionError,
            "another closure evidence",
        ):
            applier.apply(
                request=consumed,
                consume_receipt=consume_receipt,
                review=wrong,
                candidate=item,
            )

        self.assertEqual(applier.snapshot.applied_count, 0)

    def test_reject_cannot_smuggle_candidate(self):
        built = request("7")
        consumed, consume_receipt = consume(built)
        item = candidate(consumed)
        trusted = review(
            consumed,
            decision="REJECT",
            marker="9",
        )
        applier = TrustedEpisodeReviewDecisionApplier()

        with self.assertRaisesRegex(
            EpisodeReviewDecisionError,
            "REJECT decision cannot carry",
        ):
            applier.apply(
                request=consumed,
                consume_receipt=consume_receipt,
                review=trusted,
                candidate=item,
            )
        self.assertEqual(applier.snapshot.applied_count, 0)

    def test_close_clears_replay_ledger_and_disables_applier(self):
        built = request("8")
        consumed, consume_receipt = consume(built)
        trusted = review(
            consumed,
            decision="REJECT",
            marker="a",
        )
        applier = TrustedEpisodeReviewDecisionApplier()
        applier.apply(
            request=consumed,
            consume_receipt=consume_receipt,
            review=trusted,
        )
        self.assertEqual(applier.snapshot.applied_count, 1)

        applier.close()

        self.assertTrue(applier.snapshot.closed)
        self.assertEqual(applier.snapshot.applied_count, 0)
        with self.assertRaisesRegex(
            EpisodeReviewDecisionError,
            "is closed",
        ):
            applier.apply(
                request=consumed,
                consume_receipt=consume_receipt,
                review=trusted,
            )

    def test_source_has_no_memory_writer_or_background_runtime(self):
        source = (
            ROOT
            / "worker"
            / "app"
            / "consciousness_core"
            / "episode_review_decision.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "Memory4ExperienceBridge",
            "submit_completed_turn",
            "import sqlite3",
            "create_task(",
            "threading",
            "asyncio",
            "schedule_service",
            "retry",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
