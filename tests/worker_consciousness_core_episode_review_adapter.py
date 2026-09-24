#!/usr/bin/env python3
"""C30-L trusted review adapter tests."""
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
    EpisodeReviewAdapterError,
    TrustedEpisodeReviewAdapter,
    anchor_from_clock,
    append_episode_moment,
    build_episode_experience_review_request,
    build_episode_moment,
    close_experience_episode,
    derive_episode_closure_evidence,
    episode_experience_review_request_ref,
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
        source_ref=f"trusted:c30l:{sequence}",
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
            event_ref=f"episode-open:c30l:{marker}",
        ),
        reason="SESSION_START",
    )
    episode = append_episode_moment(
        episode,
        build_episode_moment(
            kind="WORLD_EVIDENCE",
            source_ref=f"world:c30l:{marker}",
            anchor=anchor(
                start + 1,
                event_ref=f"world:c30l:{marker}",
            ),
            salience=0.6,
            active_goal_refs=["goal:review"],
            participant_refs=["actor:user"],
        ),
    )
    closed = close_experience_episode(
        episode,
        closing_anchor=anchor(
            start + 2,
            event_ref=f"episode-close:c30l:{marker}",
        ),
        reason="FOCUS_SHIFT",
    )
    evidence = derive_episode_closure_evidence(
        closed,
        boundary_signal_ref=(
            "episode-boundary-signal:" + marker * 64
        ),
    )
    request = build_episode_experience_review_request(evidence)
    if request is None:
        raise AssertionError("non-empty episode must create review request")
    return request


class EpisodeReviewAdapterTests(unittest.TestCase):
    def test_list_pending_returns_bounded_reference_only_items(self):
        mailbox = EpisodeExperienceReviewMailbox(capacity=3)
        first = review_request("1")
        second = review_request("2")
        mailbox.enqueue(first)
        mailbox.enqueue(second)

        adapter = TrustedEpisodeReviewAdapter(mailbox=mailbox)
        snapshot = adapter.list_pending(limit=1)

        self.assertEqual(snapshot.pending_count, 2)
        self.assertEqual(snapshot.returned_count, 1)
        self.assertTrue(snapshot.truncated)
        item = snapshot.items[0]
        self.assertEqual(item.request_id, first.request_id)
        self.assertEqual(
            item.request_ref,
            episode_experience_review_request_ref(first),
        )
        self.assertTrue(item.semantic_review_required)
        self.assertFalse(item.raw_text_included)
        self.assertFalse(item.raw_chain_of_thought_included)
        self.assertFalse(item.memory4_called)
        self.assertFalse(item.durable)

    def test_exact_ref_consume_is_one_shot(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("3")
        mailbox.enqueue(request)
        adapter = TrustedEpisodeReviewAdapter(mailbox=mailbox)
        request_ref = episode_experience_review_request_ref(request)

        consumed, receipt = adapter.consume_exact(
            request_id=request.request_id,
            expected_request_ref=request_ref,
        )

        self.assertEqual(consumed, request)
        self.assertEqual(receipt.request_ref, request_ref)
        self.assertTrue(receipt.exact_ref_match)
        self.assertTrue(receipt.one_shot_consumed)
        self.assertFalse(receipt.reviewer_decision_applied)
        self.assertFalse(receipt.candidate_created)
        self.assertFalse(receipt.memory4_called)
        self.assertEqual(mailbox.snapshot.pending_count, 0)

        with self.assertRaisesRegex(
            EpisodeReviewAdapterError,
            "not pending",
        ):
            adapter.consume_exact(
                request_id=request.request_id,
                expected_request_ref=request_ref,
            )

    def test_ref_mismatch_does_not_consume(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("4")
        mailbox.enqueue(request)
        adapter = TrustedEpisodeReviewAdapter(mailbox=mailbox)

        with self.assertRaisesRegex(
            EpisodeReviewAdapterError,
            "ref mismatch",
        ):
            adapter.consume_exact(
                request_id=request.request_id,
                expected_request_ref=(
                    "episode-experience-review-request:" + "f" * 64
                ),
            )

        self.assertEqual(mailbox.snapshot.pending_count, 1)
        self.assertEqual(
            mailbox.pending_requests(),
            (request,),
        )

    def test_wrong_request_id_does_not_consume_other_request(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("5")
        mailbox.enqueue(request)
        adapter = TrustedEpisodeReviewAdapter(mailbox=mailbox)

        with self.assertRaisesRegex(
            EpisodeReviewAdapterError,
            "not pending",
        ):
            adapter.consume_exact(
                request_id="ereq-" + "f" * 32,
                expected_request_ref=episode_experience_review_request_ref(
                    request
                ),
            )

        self.assertEqual(mailbox.snapshot.pending_count, 1)

    def test_listing_does_not_mutate_mailbox(self):
        mailbox = EpisodeExperienceReviewMailbox(capacity=2)
        first = review_request("6")
        second = review_request("7")
        mailbox.enqueue(first)
        mailbox.enqueue(second)
        adapter = TrustedEpisodeReviewAdapter(mailbox=mailbox)

        before = mailbox.snapshot
        one = adapter.list_pending(limit=2)
        two = adapter.list_pending(limit=2)
        after = mailbox.snapshot

        self.assertEqual(before, after)
        self.assertEqual(one, two)
        self.assertFalse(one.truncated)

    def test_invalid_limit_fails_without_touching_mailbox(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("8")
        mailbox.enqueue(request)
        adapter = TrustedEpisodeReviewAdapter(mailbox=mailbox)
        before = mailbox.snapshot

        for value in (0, 33):
            with self.subTest(value=value):
                with self.assertRaises(EpisodeReviewAdapterError):
                    adapter.list_pending(limit=value)

        self.assertEqual(mailbox.snapshot, before)

    def test_adapter_adds_no_review_or_execution_authority(self):
        mailbox = EpisodeExperienceReviewMailbox()
        request = review_request("9")
        mailbox.enqueue(request)
        adapter = TrustedEpisodeReviewAdapter(mailbox=mailbox)

        _, receipt = adapter.consume_exact(
            request_id=request.request_id,
            expected_request_ref=episode_experience_review_request_ref(
                request
            ),
        )

        self.assertFalse(receipt.reviewer_decision_applied)
        self.assertFalse(receipt.candidate_created)
        self.assertFalse(receipt.durable_store_write_applied)
        self.assertFalse(receipt.memory4_called)
        self.assertEqual(receipt.model_calls, 0)
        self.assertFalse(receipt.execution_authority)
        self.assertFalse(receipt.scheduling_authority)
        self.assertFalse(receipt.timer_authority)
        self.assertFalse(receipt.production_activation)

    def test_source_contains_no_route_storage_or_background_runtime(self):
        source = (
            ROOT
            / "worker"
            / "app"
            / "consciousness_core"
            / "episode_review_adapter.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            "APIRouter",
            "@app.",
            "@router.",
            "import sqlite3",
            "MemoryStore",
            "create_task(",
            "threading",
            "asyncio",
            "schedule_service",
            "retry",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
