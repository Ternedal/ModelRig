#!/usr/bin/env python3
"""C20-B atomic WorldEvidence admission into live cognitive session.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_world_session.py
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
from app.consciousness_core.supervisor import CognitionEvent  # noqa: E402
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)
from app.consciousness_core.world_reducer import (  # noqa: E402
    WorldEvidenceEvent,
    WorldReducerError,
    world_evidence_event_ref,
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
        payload["proposal_id"] = "thinkprop-" + "7" * 32
        payload["interpretation"] = "Attend to newly admitted world evidence."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class BlockingEngine(Engine):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + "6" * 32
        payload["interpretation"] = "Complete the single-flight cognitive step."
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
        ]
    )
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class WorldSessionTests(unittest.TestCase):
    def profile(self) -> CognitiveProfile:
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "f" * 32,
            engine_instance_id="engine:test:c20b",
            provider="mock",
            model="replaceable-c20b",
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

    def session(self, engine=None):
        state = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=70,
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
            bootstrap_source_ref="runtime:test:c20b",
        )
        actual_engine = engine or Engine()
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(actual_engine),
            clock=deterministic_clock(),
        )
        return (
            ProductionCognitiveSession(
                supervisor_bridge=bridge,
                bootstrap_context=context,
            ),
            actual_engine,
        )

    def evidence(
        self,
        marker="1",
        *,
        proposition="Exact-head qualification completed successfully.",
    ):
        return WorldEvidenceEvent(
            schema="kaliv-consciousness-core/world-evidence-event/v1",
            event_id="wevt-" + marker * 32,
            subject_ref="project:modelrig",
            proposition=proposition,
            confidence=1.0,
            epistemic_status="observed",
            source_refs=["github:exact-head:test"],
            observed_sequence=100,
            production_activation=False,
        )

    def test_new_evidence_updates_world_and_queues_exact_attention_event(self):
        session, engine = self.session()
        before = session.live_state
        evidence = self.evidence()
        result = session.submit_world_evidence(
            evidence,
            attention_salience=0.9,
        )

        self.assertTrue(result.cognition_event_queued)
        self.assertIsNotNone(result.cognition_event)
        self.assertEqual(
            result.cognition_event.source_ref,
            world_evidence_event_ref(evidence),
        )
        self.assertEqual(result.cognition_event.kind, "world_change")
        self.assertEqual(result.cognition_event.summary, evidence.proposition)
        self.assertEqual(engine.calls, 0)
        self.assertEqual(
            session.live_state.state.revision,
            before.state.revision + 1,
        )
        self.assertEqual(
            session.live_state.world.revision,
            before.world.revision + 1,
        )
        self.assertEqual(session.live_state.workspace, before.workspace)
        self.assertEqual(
            session.live_state.personality_snapshot,
            before.personality_snapshot,
        )
        self.assertEqual(
            session.live_state.completed_cycles,
            before.completed_cycles,
        )
        self.assertEqual(len(session.supervisor_state.pending_events), 1)

    def test_identical_replay_updates_nothing_and_queues_nothing(self):
        session, _ = self.session()
        evidence = self.evidence()
        first = session.submit_world_evidence(
            evidence,
            attention_salience=0.9,
        )
        after_first = session.live_state
        pending_after_first = list(session.supervisor_state.pending_events)

        replay = session.submit_world_evidence(
            evidence,
            attention_salience=0.9,
        )
        self.assertTrue(replay.world_transition.idempotent_replay)
        self.assertFalse(replay.cognition_event_queued)
        self.assertIsNone(replay.cognition_event)
        self.assertEqual(session.live_state, after_first)
        self.assertEqual(
            session.supervisor_state.pending_events,
            pending_after_first,
        )
        self.assertTrue(first.cognition_event_queued)

    def test_conflicting_same_id_fails_without_live_change(self):
        session, _ = self.session()
        first = self.evidence()
        session.submit_world_evidence(first, attention_salience=0.9)
        before = session.live_state
        pending = list(session.supervisor_state.pending_events)
        conflict = self.evidence(
            proposition="Conflicting claim under an existing evidence id."
        )
        with self.assertRaises(WorldReducerError):
            session.submit_world_evidence(
                conflict,
                attention_salience=0.9,
            )
        self.assertEqual(session.live_state, before)
        self.assertEqual(session.supervisor_state.pending_events, pending)

    def test_invalid_salience_does_not_adopt_world_transition(self):
        session, _ = self.session()
        before = session.live_state
        with self.assertRaises(Exception):
            session.submit_world_evidence(
                self.evidence(),
                attention_salience=2.0,
            )
        self.assertEqual(session.live_state, before)
        self.assertEqual(session.supervisor_state.pending_events, [])

    def test_next_explicit_step_uses_admitted_world_and_consumes_event(self):
        session, engine = self.session()
        admission = session.submit_world_evidence(
            self.evidence(),
            attention_salience=1.0,
        )
        admitted_world = session.live_state.world
        admitted_state_revision = session.live_state.state.revision
        step = run(session.step(profile=self.profile()))

        self.assertEqual(step.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)
        self.assertTrue(step.context_updated)
        self.assertEqual(session.live_state.world, admitted_world)
        self.assertEqual(
            session.live_state.state.revision,
            admitted_state_revision + 2,
        )
        self.assertEqual(session.supervisor_state.pending_events, [])
        self.assertTrue(admission.cognition_event_queued)

    def test_inflight_step_rejects_evidence_without_half_transition(self):
        async def scenario():
            engine = BlockingEngine()
            session, _ = self.session(engine)
            session.submit(
                CognitionEvent(
                    schema="kaliv-consciousness-core/cognition-event/v1",
                    event_id="cevt-" + "9" * 32,
                    kind="user_turn",
                    source_ref="event:user-turn:blocking",
                    summary="Start an in-flight cognitive cycle.",
                    salience=1.0,
                    observed_sequence=1,
                    production_activation=False,
                )
            )
            task = asyncio.create_task(session.step(profile=self.profile()))
            await engine.entered.wait()
            before = session.live_state
            rejected = False
            try:
                session.submit_world_evidence(
                    self.evidence(marker="8"),
                    attention_salience=0.8,
                )
            except Exception:
                rejected = True
            unchanged = session.live_state == before
            engine.release.set()
            completed = await task
            return rejected, unchanged, completed, engine.calls

        rejected, unchanged, completed, calls = run(scenario())
        self.assertTrue(rejected)
        self.assertTrue(unchanged)
        self.assertTrue(completed.context_updated)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
