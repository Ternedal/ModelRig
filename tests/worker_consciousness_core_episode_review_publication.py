#!/usr/bin/env python3
"""C30-K non-blocking episode review publication and C19 wiring tests."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ActivePersonBindingSnapshot,
    ClockSample,
    ConsciousnessCoreRuntime,
    EpisodeExperienceReviewMailbox,
    PersistentSelfState,
    ProductionCognitiveSession,
    SelfAffect,
    TrustedRuntimeClock,
    WorldEvidenceEvent,
    anchor_from_clock,
    append_episode_moment,
    bootstrap_runtime_session,
    build_episode_boundary_signal,
    build_episode_moment,
    close_experience_episode,
    derive_episode_closure_evidence,
    open_experience_episode,
    publish_episode_closure_review,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)

FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)

SELF = "self-" + "a" * 32
PERSON = "person-" + "b" * 32
PERSON_REV = "person-r0007"
EPOCH = "epoch-" + "1" * 32
GOAL = "goal-" + "c" * 32


def static_anchor(sequence: int, *, event_ref: str):
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
        source_ref=f"trusted:c30k:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref=event_ref)


def closure_evidence(*, empty: bool = False):
    episode = open_experience_episode(
        self_id=SELF,
        person_revision=PERSON_REV,
        opening_anchor=static_anchor(
            1,
            event_ref="episode-open:c30k",
        ),
        reason="SESSION_START",
    )
    if not empty:
        episode = append_episode_moment(
            episode,
            build_episode_moment(
                kind="WORLD_EVIDENCE",
                source_ref="world:c30k",
                anchor=static_anchor(
                    2,
                    event_ref="world:c30k",
                ),
                salience=0.7,
                active_goal_refs=[GOAL],
                participant_refs=["actor:user"],
            ),
        )
    closed = close_experience_episode(
        episode,
        closing_anchor=static_anchor(
            3,
            event_ref="boundary:c30k",
        ),
        reason="FOCUS_SHIFT",
    )
    return derive_episode_closure_evidence(
        closed,
        boundary_signal_ref="episode-boundary-signal:" + "d" * 64,
    )


class Engine:
    async def think(self, request, cognitive_profile, *, context=None):
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        return payload


class CountingClock(TrustedRuntimeClock):
    def __init__(self):
        self.calls = 0
        wall = iter(
            1_700_000_000_000_000_000 + i * 1_000_000_000
            for i in range(1, 128)
        )
        mono = iter(i * 1_000_000_000 for i in range(1, 128))
        super().__init__(
            wall_time_ns=lambda: next(wall),
            monotonic_ns=lambda: next(mono),
        )

    def sample(self):
        self.calls += 1
        return super().sample()


def self_state():
    return PersistentSelfState(
        schema="kaliv-consciousness-core/self-state/v1",
        self_id=SELF,
        revision=220,
        person_id=PERSON,
        person_revision=PERSON_REV,
        personality_state_ref="personality-state:c30k",
        world_state_ref="world-state:old",
        workspace_ref="workspace:old",
        active_goal_refs=[GOAL],
        active_intention_refs=[],
        affect=SelfAffect(
            labels=["focused"],
            valence=0.0,
            arousal=0.2,
            confidence=1.0,
            source_refs=["affect:c30k"],
        ),
        known_uncertainties=[],
        last_experience_ref=None,
        production_activation=False,
    )


def person_binding(state):
    return ActivePersonBindingSnapshot(
        schema="kaliv-consciousness-core/active-person-binding/v1",
        person_id=state.person_id,
        person_revision=state.person_revision,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
        body_source_ref="body:c30k",
        voice_source_ref="voice:c30k",
        registry_source_ref="registry:c30k",
        production_activation=False,
    )


def session(*, mailbox=None):
    state = self_state()
    context = bootstrap_runtime_session(
        persistent_state=state,
        active_person=person_binding(state),
        bootstrap_source_ref="runtime:c30k",
    )
    clock = CountingClock()
    value = ProductionCognitiveSession(
        supervisor_bridge=ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(Engine()),
            clock=clock,
        ),
        bootstrap_context=context,
        review_mailbox=mailbox,
    )
    return value, clock


def world_evidence(marker: str, sequence: int):
    return WorldEvidenceEvent(
        schema="kaliv-consciousness-core/world-evidence-event/v1",
        event_id="wevt-" + marker * 32,
        subject_ref="world:test",
        proposition=f"C30-K event {marker}.",
        confidence=1.0,
        epistemic_status="observed",
        source_refs=[f"sensor:c30k:{marker}"],
        observed_sequence=sequence,
        production_activation=False,
    )


class EpisodeReviewPublicationTests(unittest.TestCase):
    def test_publisher_is_noop_without_closure_evidence(self):
        receipt = publish_episode_closure_review(
            None,
            EpisodeExperienceReviewMailbox(),
        )
        self.assertEqual(receipt.status, "NOT_APPLICABLE")
        self.assertTrue(receipt.boundary_result_preserved)
        self.assertFalse(receipt.retry_scheduled)

    def test_missing_mailbox_never_blocks_boundary_result(self):
        receipt = publish_episode_closure_review(
            closure_evidence(),
            None,
        )
        self.assertEqual(receipt.status, "MAILBOX_UNAVAILABLE")
        self.assertTrue(receipt.boundary_result_preserved)
        self.assertFalse(receipt.memory4_called)
        self.assertFalse(receipt.retry_scheduled)

    def test_empty_episode_is_not_published_for_review(self):
        mailbox = EpisodeExperienceReviewMailbox()

        receipt = publish_episode_closure_review(
            closure_evidence(empty=True),
            mailbox,
        )

        self.assertEqual(receipt.status, "NO_REVIEW")
        self.assertEqual(mailbox.snapshot.pending_count, 0)

    def test_successful_publication_and_duplicate_are_receipted(self):
        mailbox = EpisodeExperienceReviewMailbox()
        evidence = closure_evidence()

        first = publish_episode_closure_review(evidence, mailbox)
        second = publish_episode_closure_review(evidence, mailbox)

        self.assertEqual(first.status, "ENQUEUED")
        self.assertEqual(second.status, "DUPLICATE")
        self.assertEqual(mailbox.snapshot.pending_count, 1)
        self.assertTrue(second.boundary_result_preserved)
        self.assertFalse(second.retry_scheduled)

    def test_closed_mailbox_is_advisory_failure(self):
        mailbox = EpisodeExperienceReviewMailbox()
        mailbox.close()

        receipt = publish_episode_closure_review(
            closure_evidence(),
            mailbox,
        )

        self.assertEqual(receipt.status, "MAILBOX_CLOSED")
        self.assertTrue(receipt.boundary_result_preserved)

    def test_c19_boundary_rotates_and_enqueues_when_mailbox_available(self):
        mailbox = EpisodeExperienceReviewMailbox(capacity=1)
        value, clock = session(mailbox=mailbox)
        value.submit_world_evidence(
            world_evidence("1", 1),
            attention_salience=0.8,
        )
        original_id = value.experience_episode.episode_id

        sample = clock.sample()
        signal = build_episode_boundary_signal(
            kind="FOCUS_SHIFT",
            authority="core_focus_policy",
            source_ref="focus:c30k:1",
            anchor=anchor_from_clock(
                sample,
                event_ref="focus:c30k:1",
            ),
        )
        result = value.apply_episode_boundary(signal)

        self.assertEqual(result.receipt.decision, "CLOSE_AND_ROTATE")
        self.assertNotEqual(
            value.experience_episode.episode_id,
            original_id,
        )
        self.assertEqual(
            value.last_episode_review_publication.status,
            "ENQUEUED",
        )
        self.assertEqual(
            value.episode_review_mailbox_snapshot.pending_count,
            1,
        )

    def test_full_mailbox_does_not_block_second_episode_rotation(self):
        mailbox = EpisodeExperienceReviewMailbox(capacity=1)
        value, clock = session(mailbox=mailbox)

        value.submit_world_evidence(
            world_evidence("2", 1),
            attention_salience=0.8,
        )
        sample1 = clock.sample()
        signal1 = build_episode_boundary_signal(
            kind="FOCUS_SHIFT",
            authority="core_focus_policy",
            source_ref="focus:c30k:2",
            anchor=anchor_from_clock(
                sample1,
                event_ref="focus:c30k:2",
            ),
        )
        value.apply_episode_boundary(signal1)
        first_successor = value.experience_episode.episode_id
        self.assertEqual(mailbox.snapshot.pending_count, 1)

        value.submit_world_evidence(
            world_evidence("3", 2),
            attention_salience=0.7,
        )
        sample2 = clock.sample()
        signal2 = build_episode_boundary_signal(
            kind="FOCUS_SHIFT",
            authority="core_focus_policy",
            source_ref="focus:c30k:3",
            anchor=anchor_from_clock(
                sample2,
                event_ref="focus:c30k:3",
            ),
        )
        result = value.apply_episode_boundary(signal2)

        self.assertEqual(result.receipt.decision, "CLOSE_AND_ROTATE")
        self.assertNotEqual(
            value.experience_episode.episode_id,
            first_successor,
        )
        self.assertEqual(
            value.last_episode_review_publication.status,
            "CAPACITY_REACHED",
        )
        self.assertTrue(
            value.last_episode_review_publication.boundary_result_preserved
        )
        self.assertEqual(mailbox.snapshot.pending_count, 1)

    def test_session_without_mailbox_still_applies_boundary(self):
        value, clock = session()
        value.submit_world_evidence(
            world_evidence("4", 1),
            attention_salience=0.8,
        )

        sample = clock.sample()
        signal = build_episode_boundary_signal(
            kind="FOCUS_SHIFT",
            authority="core_focus_policy",
            source_ref="focus:c30k:4",
            anchor=anchor_from_clock(
                sample,
                event_ref="focus:c30k:4",
            ),
        )
        result = value.apply_episode_boundary(signal)

        self.assertEqual(result.receipt.decision, "CLOSE_AND_ROTATE")
        self.assertEqual(
            value.last_episode_review_publication.status,
            "MAILBOX_UNAVAILABLE",
        )
        self.assertIsNone(value.episode_review_mailbox_snapshot)

    def test_session_close_clears_and_closes_owned_mailbox(self):
        mailbox = EpisodeExperienceReviewMailbox()
        value, clock = session(mailbox=mailbox)
        value.submit_world_evidence(
            world_evidence("5", 1),
            attention_salience=0.8,
        )
        sample = clock.sample()
        value.apply_episode_boundary(
            build_episode_boundary_signal(
                kind="FOCUS_SHIFT",
                authority="core_focus_policy",
                source_ref="focus:c30k:5",
                anchor=anchor_from_clock(
                    sample,
                    event_ref="focus:c30k:5",
                ),
            )
        )
        self.assertEqual(mailbox.snapshot.pending_count, 1)

        value.close()

        self.assertTrue(mailbox.snapshot.closed)
        self.assertEqual(mailbox.snapshot.pending_count, 0)
        self.assertEqual(mailbox.snapshot.seen_request_count, 0)
        self.assertIsNone(value.last_episode_review_publication)


if __name__ == "__main__":
    unittest.main()
