#!/usr/bin/env python3
"""C23-B private one-shot response-guidance consume tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_response_guidance_api.py
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
from app.consciousness_core.response_guidance_api import (  # noqa: E402
    CONSCIOUSNESS_GUIDANCE_FLAG,
    CONSCIOUSNESS_GUIDANCE_PREFIX,
    build_consciousness_guidance_router,
    consciousness_guidance_enabled,
    mount_consciousness_guidance,
)
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
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + "7" * 32
        payload["interpretation"] = "PRIVATE-INTERPRETATION-SENTINEL"
        payload["response_intent"] = "Svar roligt og præcist."
        payload["questions"] = ["PRIVATE-QUESTION-SENTINEL"]
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


def deterministic_clock():
    wall = iter([
        1_700_000_000_000_000_000,
        1_700_000_001_000_000_000,
        1_700_000_002_000_000_000,
        1_700_000_003_000_000_000,
    ])
    mono = iter([
        10_000_000_000,
        11_000_000_000,
        12_000_000_000,
        13_000_000_000,
    ])
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class GuidanceApiTests(unittest.TestCase):
    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "f" * 32,
            engine_instance_id="engine:test:c23b",
            provider="mock",
            model="model-c23b",
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

    def session_with_guidance(self):
        state = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=110,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            personality_state_ref="personality-state:test",
            world_state_ref="world-state:prior",
            workspace_ref="workspace:prior",
            active_goal_refs=["goal:test"],
            active_intention_refs=["intent:test"],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.1,
                arousal=0.2,
                confidence=0.9,
                source_refs=["affect:test"],
            ),
            known_uncertainties=[],
            last_experience_ref="memory4:last",
            production_activation=False,
        )
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:test",
            voice_source_ref="voice:test",
            registry_source_ref="registry:test",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=person,
            bootstrap_source_ref="runtime:test:c23b",
        )
        engine = Engine()
        session = ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(engine),
                clock=deterministic_clock(),
            ),
            bootstrap_context=context,
        )
        event = CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + "1" * 32,
            kind="user_turn",
            source_ref="event:user-turn:test",
            summary="Hej",
            salience=1.0,
            observed_sequence=1,
            production_activation=False,
        )
        session.submit(event)
        run(session.step(profile=self.profile()))
        self.assertIsNotNone(session.pending_response_guidance)
        return session, event, engine

    def app(self, session):
        app = FastAPI()
        if session is not None:
            app.state.consciousness_session = session
        app.include_router(
            build_consciousness_guidance_router(
                loopback_allowed=lambda _request: True,
            )
        )
        return app

    def test_exact_guidance_flag_contract(self):
        old = os.environ.get(CONSCIOUSNESS_GUIDANCE_FLAG)
        try:
            os.environ.pop(CONSCIOUSNESS_GUIDANCE_FLAG, None)
            self.assertFalse(consciousness_guidance_enabled())
            for value in ("true", "yes", "on", "01", " 1 "):
                os.environ[CONSCIOUSNESS_GUIDANCE_FLAG] = value
                self.assertFalse(consciousness_guidance_enabled(), value)
            os.environ[CONSCIOUSNESS_GUIDANCE_FLAG] = "1"
            self.assertTrue(consciousness_guidance_enabled())
        finally:
            if old is None:
                os.environ.pop(CONSCIOUSNESS_GUIDANCE_FLAG, None)
            else:
                os.environ[CONSCIOUSNESS_GUIDANCE_FLAG] = old

    def test_flag_off_mounts_no_route(self):
        old = os.environ.get(CONSCIOUSNESS_GUIDANCE_FLAG)
        try:
            os.environ.pop(CONSCIOUSNESS_GUIDANCE_FLAG, None)
            app = FastAPI()
            before = [r.path for r in app.router.routes]
            self.assertFalse(mount_consciousness_guidance(app))
            self.assertEqual([r.path for r in app.router.routes], before)
        finally:
            if old is None:
                os.environ.pop(CONSCIOUSNESS_GUIDANCE_FLAG, None)
            else:
                os.environ[CONSCIOUSNESS_GUIDANCE_FLAG] = old

    def test_loopback_check_happens_before_private_body_parse(self):
        app = FastAPI()
        app.include_router(
            build_consciousness_guidance_router(
                loopback_allowed=lambda _request: False,
            )
        )
        response = TestClient(app).post(
            CONSCIOUSNESS_GUIDANCE_PREFIX + "/response-guidance/consume",
            content=b"{invalid-private-body",
        )
        self.assertEqual(response.status_code, 403)

    def test_missing_session_is_503(self):
        response = TestClient(self.app(None)).post(
            CONSCIOUSNESS_GUIDANCE_PREFIX + "/response-guidance/consume",
            json={"user_turn_event_id": "cevt-" + "1" * 32},
        )
        self.assertEqual(response.status_code, 503)

    def test_no_pending_guidance_is_404(self):
        session, event, _ = self.session_with_guidance()
        session.consume_response_guidance(user_turn_event_id=event.event_id)
        response = TestClient(self.app(session)).post(
            CONSCIOUSNESS_GUIDANCE_PREFIX + "/response-guidance/consume",
            json={"user_turn_event_id": event.event_id},
        )
        self.assertEqual(response.status_code, 404)

    def test_wrong_event_is_409_and_does_not_consume(self):
        session, event, _ = self.session_with_guidance()
        before = session.pending_response_guidance
        response = TestClient(self.app(session)).post(
            CONSCIOUSNESS_GUIDANCE_PREFIX + "/response-guidance/consume",
            json={"user_turn_event_id": "cevt-" + "2" * 32},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(session.pending_response_guidance, before)

        ok = TestClient(self.app(session)).post(
            CONSCIOUSNESS_GUIDANCE_PREFIX + "/response-guidance/consume",
            json={"user_turn_event_id": event.event_id},
        )
        self.assertEqual(ok.status_code, 200)

    def test_success_returns_only_outward_guidance_and_consumes_once(self):
        session, event, engine = self.session_with_guidance()
        client = TestClient(self.app(session))
        response = client.post(
            CONSCIOUSNESS_GUIDANCE_PREFIX + "/response-guidance/consume",
            json={"user_turn_event_id": event.event_id},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["text"], "Svar roligt og præcist.")
        self.assertEqual(body["user_turn_event_id"], event.event_id)
        self.assertTrue(body["contains_only_response_intent"])
        self.assertFalse(body["raw_chain_of_thought_included"])
        self.assertTrue(body["consumed"])
        self.assertEqual(body["model_calls"], 0)
        self.assertFalse(body["execution_authority"])
        self.assertFalse(body["scheduling_authority"])
        self.assertIsNone(session.pending_response_guidance)
        self.assertEqual(engine.calls, 1)

        raw = response.text
        self.assertNotIn("PRIVATE-INTERPRETATION-SENTINEL", raw)
        self.assertNotIn("PRIVATE-QUESTION-SENTINEL", raw)
        self.assertNotIn("interpretation", raw)
        self.assertNotIn("hypotheses", raw)
        self.assertNotIn("candidate_intentions", raw)

        second = client.post(
            CONSCIOUSNESS_GUIDANCE_PREFIX + "/response-guidance/consume",
            json={"user_turn_event_id": event.event_id},
        )
        self.assertEqual(second.status_code, 404)

    def test_invalid_body_is_generic_and_does_not_consume(self):
        session, _, _ = self.session_with_guidance()
        before = session.pending_response_guidance
        response = TestClient(self.app(session)).post(
            CONSCIOUSNESS_GUIDANCE_PREFIX + "/response-guidance/consume",
            json={"user_turn_event_id": "wrong", "extra": "PRIVATE"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "invalid consciousness response-guidance request",
        )
        self.assertNotIn("PRIVATE", response.text)
        self.assertEqual(session.pending_response_guidance, before)


if __name__ == "__main__":
    unittest.main()
