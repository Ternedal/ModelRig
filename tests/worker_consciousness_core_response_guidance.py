#!/usr/bin/env python3
"""C23-A one-shot outward response-guidance mailbox tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_response_guidance.py
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
from app.consciousness_core.cycle import cognitive_profile_ref  # noqa: E402
from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402
from app.consciousness_core.response_guidance import (  # noqa: E402
    build_response_guidance,
    response_guidance_ref,
)
from app.consciousness_core.session_lifecycle import CognitiveSessionLifecycleError  # noqa: E402
from app.consciousness_core.supervisor import CognitionEvent  # noqa: E402
from app.consciousness_core.supervisor_lifecycle import ProductionSupervisorBridge  # noqa: E402


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


class Engine:
    def __init__(self, response_intents):
        self.calls = 0
        self._response_intents = list(response_intents)

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + f"{self.calls:x}"[-1] * 32
        payload["interpretation"] = "PRIVATE-INNER-MONOLOGUE-SENTINEL"
        payload["response_intent"] = self._response_intents[self.calls - 1]
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
            1_700_000_008_000_000_000,
            1_700_000_009_000_000_000,
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
            18_000_000_000,
            19_000_000_000,
        ]
    )
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class ResponseGuidanceTests(unittest.TestCase):
    def profile(self) -> CognitiveProfile:
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "f" * 32,
            engine_instance_id="engine:test:c23a",
            provider="mock",
            model="model-c23a",
            reasoning_depth=0.8,
            planning_capacity=0.8,
            context_capacity_tokens=8192,
            multimodal_capacity=0.0,
            tool_reasoning=0.0,
            uncertainty_calibration=0.9,
            ephemeral=True,
            identity_authority=False,
            persistent_state_authority=False,
            action_authority=False,
            production_activation=False,
        )

    def session(self, response_intents):
        state = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=100,
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
            bootstrap_source_ref="runtime:test:c23a",
        )
        engine = Engine(response_intents)
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(engine),
            clock=deterministic_clock(),
        )
        session = ProductionCognitiveSession(
            supervisor_bridge=bridge,
            bootstrap_context=context,
        )
        return session, engine

    def event(self, marker: str, kind: str = "user_turn", sequence: int = 1):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind=kind,
            source_ref=f"event:test:{marker}",
            summary=f"Event {marker}",
            salience=1.0,
            observed_sequence=sequence,
            production_activation=False,
        )

    def test_single_user_turn_creates_only_response_intent_guidance(self):
        session, engine = self.session(["Svar kort, varmt og konkret."])
        event = self.event("1")
        session.submit(event)

        result = run(session.step(profile=self.profile()))
        self.assertTrue(result.context_updated)
        self.assertEqual(engine.calls, 1)

        guidance = session.pending_response_guidance
        self.assertIsNotNone(guidance)
        self.assertEqual(guidance.user_turn_event_id, event.event_id)
        self.assertEqual(guidance.text, "Svar kort, varmt og konkret.")
        self.assertEqual(
            guidance.cognitive_profile_ref,
            cognitive_profile_ref(self.profile()),
        )
        self.assertEqual(guidance.person_revision, "person-r0007")
        self.assertEqual(guidance.self_revision, session.live_state.state.revision)
        self.assertTrue(guidance.contains_only_response_intent)
        self.assertFalse(guidance.raw_chain_of_thought_included)
        self.assertNotIn("PRIVATE-INNER-MONOLOGUE-SENTINEL", guidance.text)
        self.assertTrue(response_guidance_ref(guidance).startswith("response-guidance:"))

    def test_consume_is_one_shot_for_exact_user_turn(self):
        session, _ = self.session(["Brug et roligt svar."])
        event = self.event("2", sequence=2)
        session.submit(event)
        run(session.step(profile=self.profile()))

        first = session.consume_response_guidance(
            user_turn_event_id=event.event_id,
        )
        self.assertIsNotNone(first)
        self.assertIsNone(session.pending_response_guidance)
        second = session.consume_response_guidance(
            user_turn_event_id=event.event_id,
        )
        self.assertIsNone(second)

    def test_wrong_event_id_fails_closed_without_consuming(self):
        session, _ = self.session(["Svar præcist."])
        event = self.event("3", sequence=3)
        session.submit(event)
        run(session.step(profile=self.profile()))
        before = session.pending_response_guidance

        with self.assertRaises(CognitiveSessionLifecycleError):
            session.consume_response_guidance(
                user_turn_event_id="cevt-" + "4" * 32,
            )
        self.assertEqual(session.pending_response_guidance, before)

    def test_multiple_selected_user_turns_create_no_guidance(self):
        session, _ = self.session(["Ambiguous outward guidance."])
        session.submit(self.event("5", sequence=5))
        session.submit(self.event("6", sequence=6))
        result = run(session.step(profile=self.profile()))
        self.assertTrue(result.context_updated)
        self.assertIsNone(session.pending_response_guidance)

    def test_non_user_cycle_creates_no_guidance(self):
        session, _ = self.session(["Should not be handed to a user response."])
        session.submit(self.event("7", kind="world_change", sequence=7))
        run(session.step(profile=self.profile()))
        self.assertIsNone(session.pending_response_guidance)

    def test_blank_or_none_response_intent_creates_no_guidance(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                session, _ = self.session([value])
                session.submit(self.event("8", sequence=8))
                run(session.step(profile=self.profile()))
                self.assertIsNone(session.pending_response_guidance)

    def test_new_successful_run_replaces_old_guidance_even_with_none(self):
        session, _ = self.session(
            [
                "First outward guidance.",
                None,
            ]
        )
        first_event = self.event("9", sequence=9)
        session.submit(first_event)
        run(session.step(profile=self.profile()))
        self.assertIsNotNone(session.pending_response_guidance)

        session.submit(
            self.event("a", kind="world_change", sequence=10)
        )
        run(session.step(profile=self.profile()))
        self.assertIsNone(session.pending_response_guidance)

    def test_idle_step_does_not_clear_pending_guidance(self):
        session, _ = self.session(["Keep until consumed."])
        event = self.event("b", sequence=11)
        session.submit(event)
        run(session.step(profile=self.profile()))
        before = session.pending_response_guidance
        self.assertIsNotNone(before)

        idle = run(session.step(profile=self.profile()))
        self.assertEqual(idle.supervisor_step.plan.decision, "IDLE")
        self.assertEqual(session.pending_response_guidance, before)

    def test_close_clears_guidance(self):
        session, _ = self.session(["Transient only."])
        event = self.event("c", sequence=12)
        session.submit(event)
        run(session.step(profile=self.profile()))
        self.assertIsNotNone(session.pending_response_guidance)
        session.close()
        self.assertIsNone(session.pending_response_guidance)
        with self.assertRaises(CognitiveSessionLifecycleError):
            session.consume_response_guidance(
                user_turn_event_id=event.event_id,
            )

    def test_builder_is_none_for_ambiguous_or_non_user_selection(self):
        proposal = copy.deepcopy(FIXTURES["thought_proposal"])
        proposal["response_intent"] = "Outward guidance"
        from app.consciousness_core.contracts import ThoughtProposal

        parsed = ThoughtProposal.model_validate(proposal)
        p = self.profile()
        world = self.event("d", kind="world_change", sequence=13)
        self.assertIsNone(
            build_response_guidance(
                proposal=parsed,
                selected_events=[world],
                cycle_id="cycle-" + "1" * 32,
                cognitive_profile_ref=cognitive_profile_ref(p),
                person_revision="person-r0007",
                self_revision=1,
            )
        )
        u1 = self.event("e", sequence=14)
        u2 = self.event("f", sequence=15)
        self.assertIsNone(
            build_response_guidance(
                proposal=parsed,
                selected_events=[u1, u2],
                cycle_id="cycle-" + "2" * 32,
                cognitive_profile_ref=cognitive_profile_ref(p),
                person_revision="person-r0007",
                self_revision=2,
            )
        )


if __name__ == "__main__":
    unittest.main()
