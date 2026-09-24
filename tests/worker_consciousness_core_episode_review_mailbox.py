#!/usr/bin/env python3
"""C30-J bounded process-local review mailbox tests."""
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
    EpisodeReviewMailboxError,
    anchor_from_clock,
    append_episode_moment,
    build_episode_experience_review_request,
    build_episode_moment,
    close_experience_episode,
    derive_episode_closure_evidence,
    open_experience_episode,
)


SELF = "self-" + "a" * 32
PERSON_REV = "person-r0007"
EPOCH = "epoch-" + "1" * 32


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
        source_ref=f"trusted:c30j:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref=event_ref)


def closure_evidence(marker: str, *, empty: bool = False):
    open_sequence = int(marker, 16) * 10 + 1
    episode = open_experience_episode(
        self_id=SELF,
        person_revision=PERSON_REV,
        opening_anchor=anchor(
            open_sequence,
            event_ref=f"episode-open:c30j:{marker}",
        ),
        reason="SESSION_START",
    )
    if not empty:
        episode = append_episode_moment(
            episode,
            build_episode_moment(
                kind="WORLD_EVIDENCE",
                source_ref=f"world-evidence:c30j:{marker}",
                anchor=anchor(
                    open_sequence + 1,
                    event_ref=f"world-evidence:c30j:{marker}",
                ),
                salience=0.8,
                active_goal_refs=["goal:review"],
                participant_refs=["actor:user"],
            ),
        )
    closed = close_experience_episode(
        episode,
        closing_anchor=anchor(
            open_sequence + 2,
            event_ref=f"episode-close:c30j:{marker}",
        ),
        reason="FOCUS_SHIFT",
    )
    return derive_episode_closure_evidence(
        closed,
        boundary_signal_ref=(
            "episode-boundary-signal:" + marker * 64
        ),
    )


class EpisodeReviewMailboxTests(unittest.TestCase):
    def test_empty_episode_does_not_create_review_request(self):
        evidence = closure_evidence("1", empty=True)

        request = build_episode_experience_review_request(evidence)

        self.assertIsNone(request)

    def test_non_empty_episode_builds_reference_only_request(self):
        evidence = closure_evidence("2")

        request = build_episode_experience_review_request(evidence)

        self.assertIsNotNone(request)
        self.assertEqual(
            request.review_plan.disposition,
            "TRUSTED_REVIEW_REQUIRED",
        )
        self.assertEqual(
            request.enqueued_sequence,
            evidence.closed_sequence,
        )
        self.assertFalse(request.raw_text_included)
        self.assertFalse(request.raw_chain_of_thought_included)
        self.assertFalse(request.durable)
        self.assertFalse(request.memory4_called)
        self.assertFalse(request.background_work_started)

    def test_enqueue_then_consume_exactly_once(self):
        mailbox = EpisodeExperienceReviewMailbox(capacity=2)
        request = build_episode_experience_review_request(
            closure_evidence("3")
        )

        enqueued = mailbox.enqueue(request)
        self.assertEqual(enqueued.operation, "ENQUEUE")
        self.assertEqual(mailbox.snapshot.pending_count, 1)
        self.assertEqual(mailbox.snapshot.seen_request_count, 1)

        consumed, receipt = mailbox.consume(request.request_id)
        self.assertEqual(consumed, request)
        self.assertEqual(receipt.operation, "CONSUME")
        self.assertEqual(mailbox.snapshot.pending_count, 0)
        self.assertEqual(mailbox.snapshot.seen_request_count, 1)

        with self.assertRaisesRegex(
            EpisodeReviewMailboxError,
            "not pending",
        ):
            mailbox.consume(request.request_id)

        with self.assertRaisesRegex(
            EpisodeReviewMailboxError,
            "already been admitted",
        ):
            mailbox.enqueue(request)

    def test_capacity_is_bounded_and_never_drops_pending_request(self):
        mailbox = EpisodeExperienceReviewMailbox(capacity=1)
        first = build_episode_experience_review_request(
            closure_evidence("4")
        )
        second = build_episode_experience_review_request(
            closure_evidence("5")
        )

        mailbox.enqueue(first)
        with self.assertRaisesRegex(
            EpisodeReviewMailboxError,
            "capacity reached",
        ):
            mailbox.enqueue(second)

        pending = mailbox.pending_requests()
        self.assertEqual(pending, (first,))
        self.assertEqual(mailbox.snapshot.pending_count, 1)
        self.assertEqual(mailbox.snapshot.seen_request_count, 1)

    def test_duplicate_is_rejected_while_still_pending(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = build_episode_experience_review_request(
            closure_evidence("6")
        )

        mailbox.enqueue(request)

        with self.assertRaisesRegex(
            EpisodeReviewMailboxError,
            "already been admitted",
        ):
            mailbox.enqueue(request)
        self.assertEqual(mailbox.snapshot.pending_count, 1)

    def test_close_clears_all_process_local_state_and_disables_mailbox(self):
        mailbox = EpisodeExperienceReviewMailbox(capacity=2)
        first = build_episode_experience_review_request(
            closure_evidence("7")
        )
        second = build_episode_experience_review_request(
            closure_evidence("8")
        )
        mailbox.enqueue(first)
        mailbox.enqueue(second)

        receipt = mailbox.close()

        self.assertEqual(receipt.operation, "CLOSE")
        self.assertEqual(receipt.pending_before, 2)
        self.assertEqual(receipt.pending_after, 0)
        self.assertTrue(receipt.mutation_applied)
        self.assertEqual(mailbox.snapshot.pending_count, 0)
        self.assertEqual(mailbox.snapshot.seen_request_count, 0)
        self.assertTrue(mailbox.snapshot.closed)

        with self.assertRaisesRegex(
            EpisodeReviewMailboxError,
            "is closed",
        ):
            mailbox.enqueue(first)
        with self.assertRaisesRegex(
            EpisodeReviewMailboxError,
            "is closed",
        ):
            mailbox.consume(first.request_id)

    def test_receipts_have_no_hidden_authority(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = build_episode_experience_review_request(
            closure_evidence("9")
        )
        receipt = mailbox.enqueue(request)

        self.assertFalse(receipt.durable_store_write_applied)
        self.assertFalse(receipt.memory4_called)
        self.assertEqual(receipt.model_calls, 0)
        self.assertFalse(receipt.background_work_started)
        self.assertFalse(receipt.execution_authority)
        self.assertFalse(receipt.scheduling_authority)
        self.assertFalse(receipt.timer_authority)
        self.assertFalse(receipt.production_activation)

    def test_source_has_no_storage_or_background_runtime(self):
        source = (
            ROOT
            / "worker"
            / "app"
            / "consciousness_core"
            / "episode_review_mailbox.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "import sqlite3",
            "MemoryStore",
            "create_task(",
            "threading",
            "schedule_service",
            "asyncio",
            "retry",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
