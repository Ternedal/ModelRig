#!/usr/bin/env python3
"""C30-G atomic process-local episode boundary application tests."""
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
    WorldEvidenceEvent,
    anchor_from_clock,
    append_episode_moment,
    apply_episode_boundary_decision,
    bootstrap_runtime_session,
    build_episode_boundary_signal,
    build_episode_moment,
    evaluate_episode_boundary,
    experience_episode_ref,
    open_experience_episode,
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
GOAL_A = "goal-" + "a" * 32
GOAL_B = "goal-" + "b" * 32


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
        source_ref=f"trusted:c30g:{sequence}",
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


class EpisodeBoundaryApplicationTests(unittest.TestCase):
    def episode(self):
        episode = open_experience_episode(
            self_id=SELF,
            person_revision=PERSON_REV,
            opening_anchor=anchor(
                1,
                event_ref="episode-open:c30g",
            ),
            reason="SESSION_START",
        )
        return append_episode_moment(
            episode,
            build_episode_moment(
                kind="WORLD_EVIDENCE",
                source_ref="world-evidence:" + "c" * 64,
                anchor=anchor(
                    2,
                    event_ref="world-evidence:" + "c" * 64,
                ),
                salience=0.7,
                active_goal_refs=[GOAL_A],
            ),
        )

    def state(self):
        return PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id=SELF,
            revision=220,
            person_id=PERSON,
            person_revision=PERSON_REV,
            personality_state_ref="personality-state:c30g",
            world_state_ref="world-state:old",
            workspace_ref="workspace:old",
            active_goal_refs=[GOAL_A],
            active_intention_refs=[],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c30g"],
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
            body_source_ref="body:c30g",
            voice_source_ref="voice:c30g",
            registry_source_ref="registry:c30g",
            production_activation=False,
        )

    def session(self):
        state = self.state()
        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c30g",
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

    def evidence(self, marker="7", sequence=1):
        return WorldEvidenceEvent(
            schema="kaliv-consciousness-core/world-evidence-event/v1",
            event_id="wevt-" + marker * 32,
            subject_ref="world:test",
            proposition="C30-G world event.",
            confidence=1.0,
            epistemic_status="observed",
            source_refs=["sensor:c30g:" + marker],
            observed_sequence=sequence,
            production_activation=False,
        )

    def test_keep_returns_same_active_episode_without_mutation(self):
        episode = self.episode()
        decision = evaluate_episode_boundary(episode)

        result = apply_episode_boundary_decision(
            episode,
            decision,
        )

        self.assertEqual(result.active_episode, episode)
        self.assertEqual(result.receipt.decision, "KEEP")
        self.assertFalse(result.receipt.mutation_applied)
        self.assertIsNone(result.receipt.closed_episode_ref)
        self.assertFalse(
            result.receipt.closed_episode_contents_retained
        )
        self.assertEqual(result.receipt.model_calls, 0)

    def test_rotate_closes_exact_episode_and_opens_empty_successor(self):
        episode = self.episode()
        signal = build_episode_boundary_signal(
            kind="ACTIVE_GOAL_SET_CHANGED",
            authority="goal_transition",
            source_ref="goal-transition:c30g",
            anchor=anchor(
                3,
                event_ref="goal-transition:c30g",
            ),
            previous_active_goal_refs=[GOAL_A],
            next_active_goal_refs=[GOAL_B],
        )
        decision = evaluate_episode_boundary(
            episode,
            signal,
        )

        result = apply_episode_boundary_decision(
            episode,
            decision,
        )

        self.assertEqual(
            result.receipt.decision,
            "CLOSE_AND_ROTATE",
        )
        self.assertTrue(result.receipt.mutation_applied)
        self.assertIsNotNone(result.receipt.closed_episode_ref)
        self.assertIsNotNone(result.receipt.next_episode_ref)
        self.assertFalse(
            result.receipt.closed_episode_contents_retained
        )
        next_episode = result.active_episode
        self.assertIsNotNone(next_episode)
        self.assertEqual(next_episode.phase, "ACTIVE")
        self.assertEqual(
            next_episode.open_reason,
            "GOAL_TRANSITION",
        )
        self.assertEqual(next_episode.moment_count, 0)
        self.assertEqual(next_episode.moments, [])
        self.assertEqual(
            next_episode.opened_anchor,
            signal.anchor,
        )
        self.assertEqual(
            experience_episode_ref(next_episode),
            result.receipt.next_episode_ref,
        )
        self.assertNotEqual(
            result.receipt.previous_episode_ref,
            result.receipt.next_episode_ref,
        )

    def test_close_only_leaves_no_active_episode(self):
        episode = self.episode()
        signal = build_episode_boundary_signal(
            kind="DORMANCY",
            authority="core_lifecycle",
            source_ref="lifecycle:dormancy:c30g",
            anchor=anchor(
                3,
                event_ref="lifecycle:dormancy:c30g",
            ),
        )
        decision = evaluate_episode_boundary(
            episode,
            signal,
        )

        result = apply_episode_boundary_decision(
            episode,
            decision,
        )

        self.assertEqual(
            result.receipt.decision,
            "CLOSE_ONLY",
        )
        self.assertIsNone(result.active_episode)
        self.assertIsNotNone(result.receipt.closed_episode_ref)
        self.assertIsNone(result.receipt.next_episode_ref)
        self.assertEqual(
            result.receipt.boundary_anchor_id,
            signal.anchor.anchor_id,
        )

    def test_session_rotation_takes_no_additional_clock_sample(self):
        session, engine, clock = self.session()
        session.submit_world_evidence(
            self.evidence(),
            attention_salience=0.7,
        )
        original = session.experience_episode
        self.assertIsNotNone(original)
        self.assertEqual(engine.calls, 0)

        boundary_clock = clock.sample()
        signal = build_episode_boundary_signal(
            kind="EXPLICIT_BOUNDARY",
            authority="operator_explicit",
            source_ref="operator-boundary:c30g",
            anchor=anchor_from_clock(
                boundary_clock,
                event_ref="operator-boundary:c30g",
            ),
        )
        calls_before_apply = clock.calls

        result = session.apply_episode_boundary(signal)

        self.assertEqual(clock.calls, calls_before_apply)
        self.assertEqual(
            result.receipt.decision,
            "CLOSE_AND_ROTATE",
        )
        self.assertEqual(
            session.last_episode_boundary_receipt,
            result.receipt,
        )
        self.assertEqual(
            session.experience_episode.open_reason,
            "EXPLICIT_BOUNDARY",
        )
        self.assertEqual(
            session.experience_episode.moment_count,
            0,
        )
        self.assertNotEqual(
            session.experience_episode.episode_id,
            original.episode_id,
        )

        session.submit_world_evidence(
            self.evidence(marker="8", sequence=2),
            attention_salience=0.6,
        )
        self.assertEqual(
            session.experience_episode.moment_count,
            1,
        )
        self.assertEqual(
            session.experience_episode.open_reason,
            "EXPLICIT_BOUNDARY",
        )

    def test_session_keep_is_clock_free_and_receipted(self):
        session, _engine, clock = self.session()
        session.submit_world_evidence(
            self.evidence(),
            attention_salience=0.7,
        )
        before = session.experience_episode
        calls_before = clock.calls

        result = session.apply_episode_boundary()

        self.assertEqual(clock.calls, calls_before)
        self.assertEqual(result.receipt.decision, "KEEP")
        self.assertEqual(session.experience_episode, before)
        self.assertEqual(
            session.last_episode_boundary_receipt,
            result.receipt,
        )

    def test_close_clears_latest_boundary_receipt(self):
        session, _engine, clock = self.session()
        session.submit_world_evidence(
            self.evidence(),
            attention_salience=0.7,
        )
        boundary_clock = clock.sample()
        signal = build_episode_boundary_signal(
            kind="EXPLICIT_BOUNDARY",
            authority="operator_explicit",
            source_ref="operator-boundary:c30g",
            anchor=anchor_from_clock(
                boundary_clock,
                event_ref="operator-boundary:c30g",
            ),
        )
        session.apply_episode_boundary(signal)
        self.assertIsNotNone(
            session.last_episode_boundary_receipt
        )

        session.close()

        self.assertIsNone(session.experience_episode)
        self.assertIsNone(
            session.last_episode_boundary_receipt
        )


if __name__ == "__main__":
    unittest.main()
