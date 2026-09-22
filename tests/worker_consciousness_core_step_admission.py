#!/usr/bin/env python3
"""C22-B explicit loopback single cognitive step tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_step_admission.py
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
from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402
from app.consciousness_core.profile_source import load_cognitive_profile  # noqa: E402
from app.consciousness_core.step_admission import (  # noqa: E402
    CONSCIOUSNESS_STEP_FLAG,
    CONSCIOUSNESS_STEP_PREFIX,
    build_consciousness_step_router,
    consciousness_step_enabled,
    mount_consciousness_step,
)
from app.consciousness_core.supervisor import CognitionEvent  # noqa: E402
from app.consciousness_core.supervisor_lifecycle import ProductionSupervisorBridge  # noqa: E402
from app.consciousness_core.thought_engine import ThoughtEngineContractError  # noqa: E402


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


class Engine:
    def __init__(self):
        self.calls = 0
        self.models: list[str] = []

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        self.models.append(cognitive_profile.model)
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + f"{self.calls:x}"[-1] * 32
        payload["interpretation"] = "PRIVATE-INNER-MONOLOGUE-SENTINEL"
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class InvalidEngine(Engine):
    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        raise ThoughtEngineContractError("PRIVATE-ENGINE-ERROR-SENTINEL")


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


class StepAdmissionTests(unittest.TestCase):
    def session(self, engine=None):
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
            bootstrap_source_ref="runtime:test:c22b",
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

    def profile_result(self, root: Path, *, model: str = "model-a"):
        path = root / f"{model}.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "kaliv-consciousness-core/cognitive-profile-config/v1",
                    "provider": "mock",
                    "model": model,
                    "reasoning_depth": 0.8,
                    "planning_capacity": 0.8,
                    "context_capacity_tokens": 8192,
                    "multimodal_capacity": 0.0,
                    "tool_reasoning": 0.0,
                    "uncertainty_calibration": 0.9,
                    "calibration_refs": ["test:c22b"],
                }
            ),
            encoding="utf-8",
        )
        loaded = load_cognitive_profile(path=path)
        self.assertIsNotNone(loaded)
        return loaded

    def app(self, session, loader):
        app = FastAPI()
        if session is not None:
            app.state.consciousness_session = session
        app.include_router(
            build_consciousness_step_router(
                loopback_allowed=lambda _request: True,
                profile_loader=loader,
            )
        )
        return app

    def submit_event(self, session, marker="1", sequence=1):
        session.submit(
            CognitionEvent(
                schema="kaliv-consciousness-core/cognition-event/v1",
                event_id="cevt-" + marker * 32,
                kind="user_turn",
                source_ref=f"event:test:{marker}",
                summary="One bounded user turn.",
                salience=1.0,
                observed_sequence=sequence,
                production_activation=False,
            )
        )

    def test_exact_step_flag_contract(self):
        old = os.environ.get(CONSCIOUSNESS_STEP_FLAG)
        try:
            os.environ.pop(CONSCIOUSNESS_STEP_FLAG, None)
            self.assertFalse(consciousness_step_enabled())
            for value in ("true", "on", "yes", "01", " 1 "):
                os.environ[CONSCIOUSNESS_STEP_FLAG] = value
                self.assertFalse(consciousness_step_enabled(), value)
            os.environ[CONSCIOUSNESS_STEP_FLAG] = "1"
            self.assertTrue(consciousness_step_enabled())
        finally:
            if old is None:
                os.environ.pop(CONSCIOUSNESS_STEP_FLAG, None)
            else:
                os.environ[CONSCIOUSNESS_STEP_FLAG] = old

    def test_flag_off_mounts_no_route(self):
        old = os.environ.get(CONSCIOUSNESS_STEP_FLAG)
        try:
            os.environ.pop(CONSCIOUSNESS_STEP_FLAG, None)
            app = FastAPI()
            before = [route.path for route in app.router.routes]
            self.assertFalse(mount_consciousness_step(app))
            self.assertEqual([route.path for route in app.router.routes], before)
        finally:
            if old is None:
                os.environ.pop(CONSCIOUSNESS_STEP_FLAG, None)
            else:
                os.environ[CONSCIOUSNESS_STEP_FLAG] = old

    def test_loopback_policy_runs_before_body_inspection_or_profile_load(self):
        calls = {"loader": 0}

        def loader():
            calls["loader"] += 1
            raise AssertionError("remote request must not load profile")

        app = FastAPI()
        app.include_router(
            build_consciousness_step_router(
                loopback_allowed=lambda _request: False,
                profile_loader=loader,
            )
        )
        response = TestClient(app).post(
            CONSCIOUSNESS_STEP_PREFIX + "/step",
            content=b"private-nonempty-body",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(calls["loader"], 0)

    def test_step_rejects_every_nonempty_body_before_profile_load(self):
        calls = {"loader": 0}

        def loader():
            calls["loader"] += 1
            return None

        app = FastAPI()
        app.include_router(
            build_consciousness_step_router(
                loopback_allowed=lambda _request: True,
                profile_loader=loader,
            )
        )
        response = TestClient(app).post(
            CONSCIOUSNESS_STEP_PREFIX + "/step",
            content=b"{}",
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(calls["loader"], 0)

    def test_missing_session_is_503_before_profile_load(self):
        calls = {"loader": 0}

        def loader():
            calls["loader"] += 1
            return None

        app = self.app(None, loader)
        response = TestClient(app).post(CONSCIOUSNESS_STEP_PREFIX + "/step")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "consciousness session unavailable",
        )
        self.assertEqual(calls["loader"], 0)

    def test_missing_profile_is_503_without_model_call(self):
        session, engine = self.session()
        response = TestClient(self.app(session, lambda: None)).post(
            CONSCIOUSNESS_STEP_PREFIX + "/step"
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "consciousness cognitive profile unavailable",
        )
        self.assertEqual(engine.calls, 0)

    def test_idle_step_calls_no_model_and_updates_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            loaded = self.profile_result(Path(td))
            session, engine = self.session()
            before = session.live_state

            response = TestClient(self.app(session, lambda: loaded)).post(
                CONSCIOUSNESS_STEP_PREFIX + "/step"
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["decision"], "IDLE")
            self.assertFalse(body["thought_engine_invoked"])
            self.assertEqual(body["thought_engine_calls"], 0)
            self.assertFalse(body["context_updated"])
            self.assertIsNone(body["transition_receipt_ref"])
            self.assertEqual(body["self_revision_before"], body["self_revision_after"])
            self.assertEqual(
                body["completed_cycles_before"],
                body["completed_cycles_after"],
            )
            self.assertFalse(body["model_output_exposed"])
            self.assertFalse(body["raw_chain_of_thought_exposed"])
            self.assertEqual(engine.calls, 0)
            self.assertEqual(session.live_state, before)

    def test_run_invokes_exactly_one_model_call_and_returns_only_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            loaded = self.profile_result(Path(td))
            session, engine = self.session()
            self.submit_event(session)

            response = TestClient(self.app(session, lambda: loaded)).post(
                CONSCIOUSNESS_STEP_PREFIX + "/step"
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["decision"], "RUN")
            self.assertTrue(body["thought_engine_invoked"])
            self.assertEqual(body["thought_engine_calls"], 1)
            self.assertTrue(body["context_updated"])
            self.assertIsNotNone(body["transition_receipt_ref"])
            self.assertEqual(
                body["completed_cycles_after"],
                body["completed_cycles_before"] + 1,
            )
            self.assertGreater(
                body["self_revision_after"],
                body["self_revision_before"],
            )
            self.assertEqual(engine.calls, 1)
            self.assertEqual(engine.models, ["model-a"])

            raw = response.text
            self.assertNotIn("PRIVATE-INNER-MONOLOGUE-SENTINEL", raw)
            self.assertNotIn("interpretation", raw)
            self.assertNotIn("hypotheses", raw)
            self.assertNotIn("candidate_intentions", raw)
            self.assertNotIn("response_intent", raw)

    def test_profile_is_loaded_fresh_for_each_explicit_step(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = self.profile_result(root, model="model-a")
            b = self.profile_result(root, model="model-b")
            loads = iter([a, b])
            session, engine = self.session()
            app = self.app(session, lambda: next(loads))
            client = TestClient(app)

            self.submit_event(session, marker="2", sequence=2)
            first = client.post(CONSCIOUSNESS_STEP_PREFIX + "/step")
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["decision"], "RUN")

            self.submit_event(session, marker="3", sequence=3)
            second = client.post(CONSCIOUSNESS_STEP_PREFIX + "/step")
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json()["decision"], "RUN")
            self.assertEqual(engine.models, ["model-a", "model-b"])
            self.assertNotEqual(
                first.json()["profile_id"],
                second.json()["profile_id"],
            )

    def test_closed_session_is_generic_conflict_without_model_call(self):
        with tempfile.TemporaryDirectory() as td:
            loaded = self.profile_result(Path(td))
            session, engine = self.session()
            self.submit_event(session)
            session.close()
            response = TestClient(self.app(session, lambda: loaded)).post(
                CONSCIOUSNESS_STEP_PREFIX + "/step"
            )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json()["detail"],
                "consciousness cognitive step already in progress or unavailable",
            )
            self.assertEqual(engine.calls, 0)

    def test_invalid_engine_error_is_generic_and_does_not_leak_exception(self):
        with tempfile.TemporaryDirectory() as td:
            loaded = self.profile_result(Path(td))
            session, engine = self.session(InvalidEngine())
            self.submit_event(session, marker="4", sequence=4)
            response = TestClient(self.app(session, lambda: loaded)).post(
                CONSCIOUSNESS_STEP_PREFIX + "/step"
            )
            self.assertEqual(response.status_code, 502)
            self.assertEqual(
                response.json()["detail"],
                "consciousness thought engine returned an invalid proposal",
            )
            self.assertNotIn("PRIVATE-ENGINE-ERROR-SENTINEL", response.text)
            self.assertEqual(engine.calls, 1)

    def test_receipt_pins_all_external_authority_false(self):
        with tempfile.TemporaryDirectory() as td:
            loaded = self.profile_result(Path(td))
            session, _ = self.session()
            response = TestClient(self.app(session, lambda: loaded)).post(
                CONSCIOUSNESS_STEP_PREFIX + "/step"
            )
            body = response.json()
            for key in (
                "self_state_store_write_applied",
                "durable_memory_write_authority",
                "execution_authority",
                "scheduling_authority",
                "automatic_repeat",
                "production_activation",
            ):
                self.assertFalse(body[key], key)


if __name__ == "__main__":
    unittest.main()
