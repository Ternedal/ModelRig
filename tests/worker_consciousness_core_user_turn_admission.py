#!/usr/bin/env python3
"""C21-A loopback reported user-turn admission regression tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_user_turn_admission.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

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
from app.consciousness_core.session_lifecycle import CognitiveSessionLifecycleError  # noqa: E402
from app.consciousness_core.supervisor import CognitionEvent  # noqa: E402
from app.consciousness_core.supervisor_lifecycle import ProductionSupervisorBridge  # noqa: E402
from app.consciousness_core.user_turn_admission import (  # noqa: E402
    CONSCIOUSNESS_CHAT_FLAG,
    CONSCIOUSNESS_TURN_PREFIX,
    build_consciousness_user_turn_router,
    consciousness_chat_enabled,
    mount_consciousness_user_turn,
)
from app.consciousness_core.world_reducer import WorldReducerError  # noqa: E402


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
        payload["interpretation"] = "Process one admitted user turn."
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
        payload["interpretation"] = "Finish in-flight cognition."
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


class UserTurnAdmissionTests(unittest.TestCase):
    def profile(self) -> CognitiveProfile:
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "f" * 32,
            engine_instance_id="engine:test:c21a",
            provider="mock",
            model="replaceable-c21a",
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
            revision=80,
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
            bootstrap_source_ref="runtime:test:c21a",
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

    def test_exact_chat_flag_contract(self):
        old = os.environ.get(CONSCIOUSNESS_CHAT_FLAG)
        try:
            os.environ.pop(CONSCIOUSNESS_CHAT_FLAG, None)
            self.assertFalse(consciousness_chat_enabled())
            for value in ("true", "on", "yes", "01", " 1 "):
                os.environ[CONSCIOUSNESS_CHAT_FLAG] = value
                self.assertFalse(consciousness_chat_enabled(), value)
            os.environ[CONSCIOUSNESS_CHAT_FLAG] = "1"
            self.assertTrue(consciousness_chat_enabled())
        finally:
            if old is None:
                os.environ.pop(CONSCIOUSNESS_CHAT_FLAG, None)
            else:
                os.environ[CONSCIOUSNESS_CHAT_FLAG] = old

    def test_flag_off_mounts_no_route(self):
        old = os.environ.get(CONSCIOUSNESS_CHAT_FLAG)
        try:
            os.environ.pop(CONSCIOUSNESS_CHAT_FLAG, None)
            app = FastAPI()
            before = [route.path for route in app.router.routes]
            self.assertFalse(mount_consciousness_user_turn(app))
            self.assertEqual([route.path for route in app.router.routes], before)
        finally:
            if old is None:
                os.environ.pop(CONSCIOUSNESS_CHAT_FLAG, None)
            else:
                os.environ[CONSCIOUSNESS_CHAT_FLAG] = old

    def test_reported_user_turn_updates_world_and_queues_user_turn(self):
        session, engine = self.session()
        before = session.live_state
        result = session.submit_reported_user_turn(
            turn_id="req-001",
            user_text="Jeg arbejder hjemme i dag.",
            source_ref="backend-chat:req-001",
        )

        self.assertEqual(engine.calls, 0)
        self.assertTrue(result.world_transition.world_changed)
        self.assertTrue(result.cognition_event_queued)
        self.assertEqual(result.observed_sequence, 1)
        self.assertIsNotNone(result.cognition_event)
        self.assertEqual(result.cognition_event.kind, "user_turn")
        self.assertEqual(result.cognition_event.salience, 1.0)
        self.assertEqual(result.cognition_event.observed_sequence, 1)
        self.assertEqual(
            session.live_state.state.revision,
            before.state.revision + 1,
        )

        observation = session.live_state.world.observations[-1]
        self.assertEqual(observation.proposition, "Jeg arbejder hjemme i dag.")
        self.assertEqual(observation.epistemic_status, "reported")
        self.assertEqual(observation.confidence, 1.0)
        self.assertIn("backend-chat:req-001", observation.source_refs)

    def test_two_new_user_turns_get_monotonic_source_sequence(self):
        session, _ = self.session()
        first = session.submit_reported_user_turn(
            turn_id="req-001",
            user_text="Første besked",
            source_ref="backend-chat:req-001",
        )
        second = session.submit_reported_user_turn(
            turn_id="req-002",
            user_text="Anden besked",
            source_ref="backend-chat:req-002",
        )
        self.assertEqual(first.observed_sequence, 1)
        self.assertEqual(second.observed_sequence, 2)
        self.assertEqual(
            [event.observed_sequence for event in session.supervisor_state.pending_events],
            [1, 2],
        )

    def test_exact_replay_is_idempotent_and_reuses_sequence(self):
        session, _ = self.session()
        first = session.submit_reported_user_turn(
            turn_id="req-replay",
            user_text="Samme besked",
            source_ref="backend-chat:req-replay",
        )
        pending = list(session.supervisor_state.pending_events)
        live = session.live_state
        replay = session.submit_reported_user_turn(
            turn_id="req-replay",
            user_text="Samme besked",
            source_ref="backend-chat:req-replay",
        )
        self.assertEqual(first.observed_sequence, replay.observed_sequence)
        self.assertTrue(replay.world_transition.idempotent_replay)
        self.assertFalse(replay.cognition_event_queued)
        self.assertIsNone(replay.cognition_event)
        self.assertEqual(session.live_state, live)
        self.assertEqual(session.supervisor_state.pending_events, pending)

    def test_same_turn_id_changed_text_fails_closed(self):
        session, _ = self.session()
        session.submit_reported_user_turn(
            turn_id="req-conflict",
            user_text="Original besked",
            source_ref="backend-chat:req-conflict",
        )
        live = session.live_state
        pending = list(session.supervisor_state.pending_events)
        with self.assertRaises(WorldReducerError):
            session.submit_reported_user_turn(
                turn_id="req-conflict",
                user_text="Ændret besked",
                source_ref="backend-chat:req-conflict",
            )
        self.assertEqual(session.live_state, live)
        self.assertEqual(session.supervisor_state.pending_events, pending)

    def test_same_turn_id_changed_source_fails_closed(self):
        session, _ = self.session()
        session.submit_reported_user_turn(
            turn_id="req-source",
            user_text="Samme tekst",
            source_ref="backend-chat:source-a",
        )
        with self.assertRaises(WorldReducerError):
            session.submit_reported_user_turn(
                turn_id="req-source",
                user_text="Samme tekst",
                source_ref="backend-chat:source-b",
            )

    def test_failed_inflight_admission_does_not_consume_sequence(self):
        async def scenario():
            engine = BlockingEngine()
            session, _ = self.session(engine)
            session.submit(
                CognitionEvent(
                    schema="kaliv-consciousness-core/cognition-event/v1",
                    event_id="cevt-" + "9" * 32,
                    kind="operator_signal",
                    source_ref="test:blocking",
                    summary="Hold one cycle open.",
                    salience=0.5,
                    observed_sequence=0,
                    production_activation=False,
                )
            )
            task = asyncio.create_task(session.step(profile=self.profile()))
            await engine.entered.wait()

            rejected = False
            try:
                session.submit_reported_user_turn(
                    turn_id="req-late",
                    user_text="Ventende besked",
                    source_ref="backend-chat:req-late",
                )
            except Exception:
                rejected = True

            engine.release.set()
            await task
            admitted = session.submit_reported_user_turn(
                turn_id="req-late",
                user_text="Ventende besked",
                source_ref="backend-chat:req-late",
            )
            return rejected, admitted

        rejected, admitted = run(scenario())
        self.assertTrue(rejected)
        self.assertEqual(admitted.observed_sequence, 1)

    def test_loopback_policy_runs_before_private_body_parse(self):
        app = FastAPI()
        app.include_router(
            build_consciousness_user_turn_router(
                loopback_allowed=lambda _request: False,
            )
        )
        client = TestClient(app)
        response = client.post(
            CONSCIOUSNESS_TURN_PREFIX + "/user-turn",
            content=b"{this is invalid json and private text",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            "Consciousness user-turn admission is loopback-only",
        )

    def test_route_requires_live_session(self):
        app = FastAPI()
        app.include_router(
            build_consciousness_user_turn_router(
                loopback_allowed=lambda _request: True,
            )
        )
        client = TestClient(app)
        response = client.post(
            CONSCIOUSNESS_TURN_PREFIX + "/user-turn",
            json={
                "turn_id": "req-no-session",
                "user_text": "Hej",
                "source_ref": "backend-chat:req-no-session",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "consciousness session unavailable",
        )

    def test_route_receipt_never_echoes_user_text(self):
        session, engine = self.session()
        app = FastAPI()
        app.state.consciousness_session = session
        app.include_router(
            build_consciousness_user_turn_router(
                loopback_allowed=lambda _request: True,
            )
        )
        client = TestClient(app)
        private_text = "Privat user-turn sentinel c21a"
        response = client.post(
            CONSCIOUSNESS_TURN_PREFIX + "/user-turn",
            json={
                "turn_id": "req-private",
                "user_text": private_text,
                "source_ref": "backend-chat:req-private",
            },
        )
        self.assertEqual(response.status_code, 200)
        raw = response.text
        self.assertNotIn(private_text, raw)
        body = response.json()
        self.assertEqual(body["epistemic_status"], "reported")
        self.assertEqual(body["confidence"], 1.0)
        self.assertEqual(body["observed_sequence"], 1)
        self.assertTrue(body["world_changed"])
        self.assertTrue(body["cognition_event_queued"])
        self.assertEqual(engine.calls, 0)

        replay = client.post(
            CONSCIOUSNESS_TURN_PREFIX + "/user-turn",
            json={
                "turn_id": "req-private",
                "user_text": private_text,
                "source_ref": "backend-chat:req-private",
            },
        )
        self.assertEqual(replay.status_code, 200)
        replay_body = replay.json()
        self.assertTrue(replay_body["replayed"])
        self.assertFalse(replay_body["world_changed"])
        self.assertFalse(replay_body["cognition_event_queued"])
        self.assertEqual(replay_body["observed_sequence"], 1)

    def test_route_conflict_is_generic_and_does_not_echo_text(self):
        session, _ = self.session()
        app = FastAPI()
        app.state.consciousness_session = session
        app.include_router(
            build_consciousness_user_turn_router(
                loopback_allowed=lambda _request: True,
            )
        )
        client = TestClient(app)
        first = {
            "turn_id": "req-conflict-http",
            "user_text": "Original hemmelig tekst",
            "source_ref": "backend-chat:req-conflict-http",
        }
        self.assertEqual(
            client.post(
                CONSCIOUSNESS_TURN_PREFIX + "/user-turn",
                json=first,
            ).status_code,
            200,
        )
        changed = dict(first)
        changed["user_text"] = "Ændret hemmelig tekst"
        response = client.post(
            CONSCIOUSNESS_TURN_PREFIX + "/user-turn",
            json=changed,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"],
            "consciousness user-turn admission conflict",
        )
        self.assertNotIn(changed["user_text"], response.text)


if __name__ == "__main__":
    unittest.main()
