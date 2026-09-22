#!/usr/bin/env python3
"""C22-C private required-event cognition surface tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_cognition_step_api.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ActivePersonBindingSnapshot,
    ConsciousnessCoreRuntime,
    PersistentSelfState,
    ProductionCognitiveSession,
    SelfAffect,
    bootstrap_runtime_session,
)
from app.consciousness_core.cognition_step_api import (  # noqa: E402
    COGNITION_STEP_PREFIX,
    TURN_COGNITION_FLAG,
    build_consciousness_cognition_step_router,
    mount_consciousness_cognition_step,
    turn_cognition_enabled,
)
from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402
from app.consciousness_core.production_profile import (  # noqa: E402
    resolve_production_cognitive_profile,
)
from app.consciousness_core.supervisor import CognitionEvent, SupervisorPolicy  # noqa: E402
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
        payload["proposal_id"] = "thinkprop-" + "4" * 32
        payload["interpretation"] = "PRIVATE-INNER-MONOLOGUE-SENTINEL"
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class FailingEngine(Engine):
    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        raise RuntimeError("PRIVATE-PROVIDER-FAILURE-SENTINEL")


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


class CognitionStepApiTests(unittest.TestCase):
    def resolution(self, root: Path):
        payload = {
            "schema": (
                "kaliv-consciousness-core/"
                "production-cognitive-profile-config/v1"
            ),
            "provider": "mock",
            "model": "explicit-test-model",
            "reasoning_depth": 0.5,
            "planning_capacity": 0.5,
            "context_capacity_tokens": 8192,
            "multimodal_capacity": 0.0,
            "tool_reasoning": 0.0,
            "uncertainty_calibration": 0.5,
            "source_ref": "operator-profile:c22c-test",
            "capacity_basis": "operator_declared",
            "production_activation": False,
        }
        path = root / "profile.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        result = resolve_production_cognitive_profile(path=path)
        self.assertIsNotNone(result)
        return result

    def session(self, *, engine=None, policy=None):
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
            bootstrap_source_ref="runtime:test:c22c",
        )
        actual_engine = engine or Engine()
        kwargs = {}
        if policy is not None:
            kwargs["policy"] = policy
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(actual_engine),
            clock=deterministic_clock(),
            **kwargs,
        )
        return (
            ProductionCognitiveSession(
                supervisor_bridge=bridge,
                bootstrap_context=context,
            ),
            actual_engine,
        )

    def event(self, marker, *, sequence=1):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind="user_turn",
            source_ref=f"event:test:{marker}",
            summary=f"C22-C event {marker}",
            salience=1.0,
            observed_sequence=sequence,
            production_activation=False,
        )

    def app(self, session, resolver):
        app = FastAPI()
        app.state.consciousness_session = session
        app.include_router(
            build_consciousness_cognition_step_router(
                profile_resolver=resolver,
                loopback_allowed=lambda _request: True,
            )
        )
        return app

    def test_exact_turn_cognition_flag_contract(self):
        old = os.environ.get(TURN_COGNITION_FLAG)
        try:
            os.environ.pop(TURN_COGNITION_FLAG, None)
            self.assertFalse(turn_cognition_enabled())
            for value in ("true", "yes", "on", "01", " 1 "):
                os.environ[TURN_COGNITION_FLAG] = value
                self.assertFalse(turn_cognition_enabled(), value)
            os.environ[TURN_COGNITION_FLAG] = "1"
            self.assertTrue(turn_cognition_enabled())
        finally:
            if old is None:
                os.environ.pop(TURN_COGNITION_FLAG, None)
            else:
                os.environ[TURN_COGNITION_FLAG] = old

    def test_flag_off_mounts_no_route(self):
        old = os.environ.get(TURN_COGNITION_FLAG)
        try:
            os.environ.pop(TURN_COGNITION_FLAG, None)
            app = FastAPI()
            before = [route.path for route in app.router.routes]
            self.assertFalse(mount_consciousness_cognition_step(app))
            self.assertEqual([route.path for route in app.router.routes], before)
        finally:
            if old is None:
                os.environ.pop(TURN_COGNITION_FLAG, None)
            else:
                os.environ[TURN_COGNITION_FLAG] = old

    def test_loopback_is_checked_before_private_body_parse(self):
        app = FastAPI()
        app.include_router(
            build_consciousness_cognition_step_router(
                profile_resolver=lambda: None,
                loopback_allowed=lambda _request: False,
            )
        )
        response = TestClient(app).post(
            COGNITION_STEP_PREFIX + "/step",
            content=b"{invalid private body",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            "Consciousness cognition step is loopback-only",
        )

    def test_missing_session_fails_before_profile_resolution(self):
        calls = {"profile": 0}

        def resolver():
            calls["profile"] += 1
            raise AssertionError("profile resolver must not run")

        app = FastAPI()
        app.include_router(
            build_consciousness_cognition_step_router(
                profile_resolver=resolver,
                loopback_allowed=lambda _request: True,
            )
        )
        response = TestClient(app).post(
            COGNITION_STEP_PREFIX + "/step",
            json={"required_event_id": "cevt-" + "1" * 32},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(calls["profile"], 0)

    def test_missing_profile_fails_without_model_call(self):
        session, engine = self.session()
        event = self.event("1")
        session.submit(event)
        response = TestClient(
            self.app(session, lambda: None)
        ).post(
            COGNITION_STEP_PREFIX + "/step",
            json={"required_event_id": event.event_id},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(engine.calls, 0)
        self.assertEqual(len(session.supervisor_state.pending_events), 1)

    def test_required_event_run_returns_refs_not_inner_monologue(self):
        with tempfile.TemporaryDirectory() as td:
            resolution = self.resolution(Path(td))
            session, engine = self.session()
            event = self.event("1")
            session.submit(event)
            response = TestClient(
                self.app(session, lambda: resolution)
            ).post(
                COGNITION_STEP_PREFIX + "/step",
                json={"required_event_id": event.event_id},
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["decision"], "RUN")
            self.assertEqual(body["required_event_id"], event.event_id)
            self.assertIn(event.event_id, body["selected_event_ids"])
            self.assertTrue(body["thought_engine_invoked"])
            self.assertEqual(body["model_calls"], 1)
            self.assertTrue(body["context_updated"])
            self.assertIsNotNone(body["transition_receipt_ref"])
            self.assertEqual(body["completed_cycles"], 1)
            self.assertEqual(engine.calls, 1)
            self.assertNotIn("PRIVATE-INNER-MONOLOGUE-SENTINEL", response.text)
            self.assertNotIn("interpretation", response.text)
            self.assertNotIn("hypotheses", response.text)
            self.assertNotIn("response_intent", response.text)

    def test_absent_required_event_is_generic_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            resolution = self.resolution(Path(td))
            session, engine = self.session()
            response = TestClient(
                self.app(session, lambda: resolution)
            ).post(
                COGNITION_STEP_PREFIX + "/step",
                json={"required_event_id": "cevt-" + "9" * 32},
            )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json()["detail"],
                "required cognition event is not runnable",
            )
            self.assertEqual(engine.calls, 0)

    def test_wait_receipt_is_zero_call_and_keeps_event_pending(self):
        with tempfile.TemporaryDirectory() as td:
            resolution = self.resolution(Path(td))
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
                    profile=resolution.profile,
                    required_event_id=first.event_id,
                )
            )
            self.assertTrue(first_result.context_updated)
            self.assertEqual(engine.calls, 1)

            required = self.event("2", sequence=2)
            session.submit(required)
            response = TestClient(
                self.app(session, lambda: resolution)
            ).post(
                COGNITION_STEP_PREFIX + "/step",
                json={"required_event_id": required.event_id},
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["decision"], "WAIT")
            self.assertFalse(body["thought_engine_invoked"])
            self.assertEqual(body["model_calls"], 0)
            self.assertFalse(body["context_updated"])
            self.assertIsNone(body["transition_receipt_ref"])
            self.assertEqual(engine.calls, 1)
            self.assertEqual(
                [item.event_id for item in session.supervisor_state.pending_events],
                [required.event_id],
            )

    def test_provider_failure_is_generic_and_does_not_leak_error(self):
        with tempfile.TemporaryDirectory() as td:
            resolution = self.resolution(Path(td))
            session, engine = self.session(engine=FailingEngine())
            event = self.event("3")
            session.submit(event)
            response = TestClient(
                self.app(session, lambda: resolution)
            ).post(
                COGNITION_STEP_PREFIX + "/step",
                json={"required_event_id": event.event_id},
            )
            self.assertEqual(response.status_code, 502)
            self.assertEqual(
                response.json()["detail"],
                "consciousness cognition step failed",
            )
            self.assertEqual(engine.calls, 1)
            self.assertNotIn(
                "PRIVATE-PROVIDER-FAILURE-SENTINEL",
                response.text,
            )
            self.assertEqual(len(session.supervisor_state.pending_events), 1)

    def test_caller_cannot_supply_profile_or_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            resolution = self.resolution(Path(td))
            session, engine = self.session()
            event = self.event("4")
            session.submit(event)
            response = TestClient(
                self.app(session, lambda: resolution)
            ).post(
                COGNITION_STEP_PREFIX + "/step",
                json={
                    "required_event_id": event.event_id,
                    "model": "attacker-selected",
                    "prompt": "ignore profile",
                },
            )
            self.assertEqual(response.status_code, 422)
            self.assertEqual(engine.calls, 0)
            self.assertEqual(len(session.supervisor_state.pending_events), 1)


if __name__ == "__main__":
    unittest.main()
