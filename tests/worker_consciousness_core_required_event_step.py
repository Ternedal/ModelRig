#!/usr/bin/env python3
"""C22-A required-event one-shot cognition regression tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_required_event_step.py
"""
from __future__ import annotations

import asyncio
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
    CognitiveProfile,
    ConsciousnessCoreRuntime,
    PersistentSelfState,
    ProductionCognitiveSession,
    SelfAffect,
    bootstrap_runtime_session,
)
from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402
from app.consciousness_core.supervisor import CognitionEvent, SupervisorPolicy  # noqa: E402
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
    SupervisorLifecycleError,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + "5" * 32
        payload["interpretation"] = "Process the explicitly required event."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


def deterministic_clock():
    wall = iter(
        [
            1_700_000_000_000_000_000,
            1_700_000_001_000_000_000,
            1_700_000_002_000_000_000,
            1_700_000_003_000_000_000,
            1_700_000_004_000_000_000,
            1_700_000_005_000_000_000,
            1_700_000_006_000_000_000,
            1_700_000_007_000_000_000,
        ]
    )
    mono = iter(
        [
            10_000_000_000,
            11_000_000_000,
            12_000_000_000,
            13_000_000_000,
            14_000_000_000,
            15_000_000_000,
            16_000_000_000,
            17_000_000_000,
        ]
    )
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class RequiredEventStepTests(unittest.TestCase):
    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "f" * 32,
            engine_instance_id="engine:test:c22a",
            provider="mock",
            model="explicit-profile-model",
            reasoning_depth=0.5,
            planning_capacity=0.5,
            context_capacity_tokens=8192,
            multimodal_capacity=0.0,
            tool_reasoning=0.0,
            uncertainty_calibration=0.5,
            ephemeral=True,
            identity_authority=False,
            persistent_state_authority=False,
            action_authority=False,
            production_activation=False,
        )

    def session(self, *, policy=None):
        state = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=90,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            personality_state_ref="personality-state:test",
            world_state_ref="world-state:prior",
            workspace_ref="workspace:prior",
            active_goal_refs=["goal:consciousness-core"],
            active_intention_refs=["intent:continue"],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.2,
                arousal=0.3,
                confidence=0.9,
                source_refs=["affect:test"],
            ),
            known_uncertainties=[],
            last_experience_ref="memory4:experience:last",
            production_activation=False,
        )
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="bodyrig:test",
            voice_source_ref="voicerig:test",
            registry_source_ref="person-registry:test",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=person,
            bootstrap_source_ref="runtime:test:c22a",
        )
        engine = Engine()
        kwargs = {}
        if policy is not None:
            kwargs["policy"] = policy
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(engine),
            clock=deterministic_clock(),
            **kwargs,
        )
        session = ProductionCognitiveSession(
            supervisor_bridge=bridge,
            bootstrap_context=context,
        )
        return session, engine

    def event(self, marker, *, salience=1.0, sequence=1):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind="user_turn",
            source_ref=f"event:test:{marker}",
            summary=f"Required-event test {marker}.",
            salience=salience,
            observed_sequence=sequence,
            production_activation=False,
        )

    def test_required_selected_event_runs_exactly_one_cycle(self):
        session, engine = self.session()
        event = self.event("1")
        session.submit(event)

        result = run(
            session.step(
                profile=self.profile(),
                required_event_id=event.event_id,
            )
        )

        self.assertTrue(result.context_updated)
        self.assertEqual(result.supervisor_step.plan.decision, "RUN")
        self.assertIn(
            event.event_id,
            result.supervisor_step.plan.selected_event_ids,
        )
        self.assertEqual(engine.calls, 1)
        self.assertEqual(session.supervisor_state.pending_events, [])

    def test_absent_required_event_fails_before_model(self):
        session, engine = self.session()
        before = session.live_state
        with self.assertRaises(SupervisorLifecycleError):
            run(
                session.step(
                    profile=self.profile(),
                    required_event_id="cevt-" + "9" * 32,
                )
            )
        self.assertEqual(engine.calls, 0)
        self.assertEqual(session.live_state, before)
        self.assertEqual(session.supervisor_state.pending_events, [])

    def test_invalid_required_event_id_fails_before_model(self):
        session, engine = self.session()
        session.submit(self.event("1"))
        with self.assertRaises(SupervisorLifecycleError):
            run(
                session.step(
                    profile=self.profile(),
                    required_event_id="not-an-event-id",
                )
            )
        self.assertEqual(engine.calls, 0)
        self.assertEqual(len(session.supervisor_state.pending_events), 1)

    def test_pending_but_unselected_required_event_fails_closed(self):
        session, engine = self.session()
        required = self.event("f", salience=0.1, sequence=99)
        session.submit(required)
        for i, marker in enumerate(("1", "2", "3", "4"), start=1):
            session.submit(
                self.event(
                    marker,
                    salience=1.0,
                    sequence=i,
                )
            )

        before = session.live_state
        pending_before = list(session.supervisor_state.pending_events)
        with self.assertRaises(SupervisorLifecycleError):
            run(
                session.step(
                    profile=self.profile(),
                    required_event_id=required.event_id,
                )
            )

        self.assertEqual(engine.calls, 0)
        self.assertEqual(session.live_state, before)
        self.assertEqual(
            session.supervisor_state.pending_events,
            pending_before,
        )

    def test_required_event_waits_without_additional_model_call(self):
        policy = SupervisorPolicy(
            schema="kaliv-consciousness-core/supervisor-policy/v1",
            min_cycle_interval_ms=1500,
            max_events_per_cycle=4,
            production_activation=False,
        )
        session, engine = self.session(policy=policy)

        first = self.event("1", sequence=1)
        session.submit(first)
        first_result = run(
            session.step(
                profile=self.profile(),
                required_event_id=first.event_id,
            )
        )
        self.assertTrue(first_result.context_updated)
        self.assertEqual(engine.calls, 1)

        required = self.event("2", sequence=2)
        session.submit(required)
        before = session.live_state
        wait = run(
            session.step(
                profile=self.profile(),
                required_event_id=required.event_id,
            )
        )
        self.assertEqual(wait.supervisor_step.plan.decision, "WAIT")
        self.assertFalse(wait.context_updated)
        self.assertFalse(wait.supervisor_step.thought_engine_invoked)
        self.assertEqual(engine.calls, 1)
        self.assertEqual(session.live_state, before)
        self.assertEqual(
            [event.event_id for event in session.supervisor_state.pending_events],
            [required.event_id],
        )

    def test_generic_step_behavior_remains_available(self):
        session, engine = self.session()
        event = self.event("3")
        session.submit(event)
        result = run(session.step(profile=self.profile()))
        self.assertTrue(result.context_updated)
        self.assertEqual(engine.calls, 1)
        self.assertEqual(result.supervisor_step.plan.decision, "RUN")


if __name__ == "__main__":
    unittest.main()
