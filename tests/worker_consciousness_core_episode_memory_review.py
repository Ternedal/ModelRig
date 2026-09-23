#!/usr/bin/env python3
"""C30-H episode closure projection into existing C7 Memory 4 review seam."""
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
    PersistentSelfState,
    ProductionCognitiveSession,
    SelfAffect,
    TrustedRuntimeClock,
    anchor_from_clock,
    append_episode_moment,
    apply_episode_boundary_decision,
    bootstrap_runtime_session,
    build_episode_boundary_signal,
    build_episode_experience_candidate,
    build_episode_moment,
    episode_boundary_application_receipt_ref,
    evaluate_episode_boundary,
    open_experience_episode,
    plan_memory_handoff,
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
GOAL = "goal-" + "c" * 32
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
        source_ref=f"trusted:c30h:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref=event_ref)


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
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


class EpisodeMemoryReviewTests(unittest.TestCase):
    def state(self):
        return PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id=SELF,
            revision=230,
            person_id=PERSON,
            person_revision=PERSON_REV,
            personality_state_ref="personality-state:c30h",
            world_state_ref="world-state:old",
            workspace_ref="workspace:old",
            active_goal_refs=[GOAL],
            active_intention_refs=[],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c30h"],
            ),
            known_uncertainties=[],
            last_experience_ref=None,
            production_activation=False,
        )

    def person(self, state):
        return ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c30h",
            voice_source_ref="voice:c30h",
            registry_source_ref="registry:c30h",
            production_activation=False,
        )

    def episode(self):
        episode = open_experience_episode(
            self_id=SELF,
            person_revision=PERSON_REV,
            opening_anchor=anchor(
                1,
                event_ref="episode-open:c30h",
            ),
            reason="SESSION_START",
        )
        episode = append_episode_moment(
            episode,
            build_episode_moment(
                kind="USER_TURN",
                source_ref="world-evidence:" + "d" * 64,
                anchor=anchor(
                    2,
                    event_ref="world-evidence:" + "d" * 64,
                ),
                salience=0.8,
                active_goal_refs=[GOAL],
                participant_refs=["actor:user"],
            ),
        )
        return append_episode_moment(
            episode,
            build_episode_moment(
                kind="PREDICTION_RESOLUTION",
                source_ref="prediction-attention:" + "e" * 64,
                anchor=anchor(
                    3,
                    event_ref="prediction-attention:" + "e" * 64,
                ),
                salience=1.0,
                active_goal_refs=[GOAL],
            ),
        )

    def boundary_result(self, episode):
        signal = build_episode_boundary_signal(
            kind="EXPLICIT_BOUNDARY",
            authority="operator_explicit",
            source_ref="operator-boundary:c30h",
            anchor=anchor(
                4,
                event_ref="operator-boundary:c30h",
            ),
        )
        decision = evaluate_episode_boundary(
            episode,
            signal,
        )
        return apply_episode_boundary_decision(
            episode,
            decision,
        )

    def session(self):
        state = self.state()
        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c30h",
        )
        engine = Engine()
        clock = CountingClock()
        session = ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(engine),
                clock=clock,
            ),
            bootstrap_context=context,
        )
        return session, engine, clock

    def test_candidate_uses_existing_c7_review_contract(self):
        state = self.state()
        episode = self.episode()
        application = self.boundary_result(episode)

        candidate = build_episode_experience_candidate(
            episode=episode,
            application_receipt=application.receipt,
            state=state,
            cycle_id="cycle-" + "7" * 32,
        )

        self.assertEqual(
            candidate.kind,
            "EXPERIENTIAL_EPISODE",
        )
        self.assertEqual(
            candidate.provenance_kind,
            "core_episode",
        )
        self.assertEqual(candidate.sensitivity, "private")
        self.assertEqual(
            candidate.event_ref,
            application.receipt.closed_episode_ref,
        )
        self.assertEqual(
            candidate.participant_refs,
            ["actor:user"],
        )
        self.assertEqual(candidate.active_goal_refs, [GOAL])
        self.assertEqual(candidate.significance, 1.0)
        self.assertEqual(
            candidate.world_state_delta_refs,
            ["world-evidence:" + "d" * 64],
        )
        self.assertEqual(
            candidate.prediction_error_refs,
            ["prediction-attention:" + "e" * 64],
        )
        self.assertIn(
            episode_boundary_application_receipt_ref(
                application.receipt
            ),
            candidate.source_refs,
        )

        handoff = plan_memory_handoff(candidate)
        self.assertEqual(
            handoff.status,
            "trusted_review_required",
        )
        self.assertNotEqual(
            handoff.status,
            "completed_turn_authority",
        )

    def test_candidate_contains_refs_not_raw_episode_text(self):
        state = self.state()
        episode = self.episode()
        application = self.boundary_result(episode)
        candidate = build_episode_experience_candidate(
            episode=episode,
            application_receipt=application.receipt,
            state=state,
            cycle_id="cycle-" + "7" * 32,
        )

        payload = candidate.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True)
        self.assertNotIn("proposition", encoded)
        self.assertNotIn("user_text", encoded)
        self.assertNotIn("interpretation", encoded)
        self.assertNotIn("chain_of_thought", encoded)
        self.assertIsNone(candidate.completed_turn_source_ref)

    def test_keep_does_not_create_session_review_candidate(self):
        session, engine, clock = self.session()
        session.submit_reported_user_turn(
            turn_id="turn-c30h-keep",
            user_text="Private text remains outside candidate.",
            source_ref="chat-turn:c30h:keep",
        )
        calls_before = clock.calls

        result = session.apply_episode_boundary()

        self.assertEqual(result.receipt.decision, "KEEP")
        self.assertEqual(clock.calls, calls_before)
        self.assertEqual(engine.calls, 0)
        self.assertIsNone(
            session.pending_episode_experience_candidate
        )

    def test_mutating_boundary_publishes_one_review_candidate(self):
        session, engine, clock = self.session()
        sentinel = "PRIVATE-C30H-USER-TEXT"
        session.submit_reported_user_turn(
            turn_id="turn-c30h-1",
            user_text=sentinel,
            source_ref="chat-turn:c30h:1",
        )
        episode_before = session.experience_episode

        boundary_clock = clock.sample()
        signal = build_episode_boundary_signal(
            kind="EXPLICIT_BOUNDARY",
            authority="operator_explicit",
            source_ref="operator-boundary:c30h:1",
            anchor=anchor_from_clock(
                boundary_clock,
                event_ref="operator-boundary:c30h:1",
            ),
        )
        calls_before = clock.calls

        result = session.apply_episode_boundary(signal)

        self.assertEqual(clock.calls, calls_before)
        self.assertEqual(engine.calls, 0)
        candidate = session.pending_episode_experience_candidate
        self.assertIsNotNone(candidate)
        self.assertEqual(
            candidate.event_ref,
            result.receipt.closed_episode_ref,
        )
        self.assertEqual(
            candidate.participant_refs,
            ["actor:user"],
        )
        self.assertNotIn(
            sentinel,
            candidate.model_dump_json(),
        )
        self.assertNotEqual(
            session.experience_episode.episode_id,
            episode_before.episode_id,
        )
        self.assertEqual(
            plan_memory_handoff(candidate).status,
            "trusted_review_required",
        )

    def test_next_closure_replaces_candidate_instead_of_accumulating(self):
        session, _engine, clock = self.session()
        session.submit_reported_user_turn(
            turn_id="turn-c30h-1",
            user_text="First episode.",
            source_ref="chat-turn:c30h:1",
        )
        signal1 = build_episode_boundary_signal(
            kind="EXPLICIT_BOUNDARY",
            authority="operator_explicit",
            source_ref="operator-boundary:c30h:1",
            anchor=anchor_from_clock(
                clock.sample(),
                event_ref="operator-boundary:c30h:1",
            ),
        )
        session.apply_episode_boundary(signal1)
        first = session.pending_episode_experience_candidate

        session.submit_reported_user_turn(
            turn_id="turn-c30h-2",
            user_text="Second episode.",
            source_ref="chat-turn:c30h:2",
        )
        signal2 = build_episode_boundary_signal(
            kind="EXPLICIT_BOUNDARY",
            authority="operator_explicit",
            source_ref="operator-boundary:c30h:2",
            anchor=anchor_from_clock(
                clock.sample(),
                event_ref="operator-boundary:c30h:2",
            ),
        )
        session.apply_episode_boundary(signal2)
        second = session.pending_episode_experience_candidate

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(
            first.experience_id,
            second.experience_id,
        )
        self.assertEqual(
            session.pending_episode_experience_candidate,
            second,
        )

    def test_close_clears_pending_review_candidate(self):
        session, _engine, clock = self.session()
        session.submit_reported_user_turn(
            turn_id="turn-c30h-close",
            user_text="Close candidate.",
            source_ref="chat-turn:c30h:close",
        )
        signal = build_episode_boundary_signal(
            kind="EXPLICIT_BOUNDARY",
            authority="operator_explicit",
            source_ref="operator-boundary:c30h:close",
            anchor=anchor_from_clock(
                clock.sample(),
                event_ref="operator-boundary:c30h:close",
            ),
        )
        session.apply_episode_boundary(signal)
        self.assertIsNotNone(
            session.pending_episode_experience_candidate
        )

        session.close()

        self.assertIsNone(
            session.pending_episode_experience_candidate
        )


if __name__ == "__main__":
    unittest.main()
