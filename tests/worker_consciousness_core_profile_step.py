#!/usr/bin/env python3
"""C22-B profile-backed private one-shot cognition step tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_profile_step.py
"""
from __future__ import annotations

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
from app.consciousness_core.profile_source import (  # noqa: E402
    load_cognitive_profile,
)
from app.consciousness_core.profile_step_api import (  # noqa: E402
    COGNITION_STEP_PREFIX,
    CONSCIOUSNESS_STEP_FLAG,
    build_consciousness_profile_step_router,
    mount_consciousness_profile_step,
    profile_step_enabled,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.supervisor import (  # noqa: E402
    CognitionEvent,
    SupervisorPolicy,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


class Engine:
    def __init__(self) -> None:
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + "4" * 32
        payload["interpretation"] = "PRIVATE-INNER-MONOLOGUE-SENTINEL"
        payload["attention_suggestions"] = []
        payload["candidate_intentions"] = []
        payload["predicted_outcomes"] = []
        payload["memory_queries"] = []
        payload["response_intent"] = None
        payload["body_intent"] = None
        payload["uncertainty"] = 0.1
        return payload


class FailingEngine(Engine):
    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        raise RuntimeError("PRIVATE-PROVIDER-FAILURE-SENTINEL")


class CountingLoader:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return load_cognitive_profile(
            path=self.path,
            engine_instance_id="thought-engine:test:v1",
        )


def deterministic_clock():
    wall = [1_700_000_000_000_000_000]
    mono = [10_000_000_000]

    def next_wall():
        value = wall[0]
        wall[0] += 100_000_000
        return value

    def next_mono():
        value = mono[0]
        mono[0] += 100_000_000
        return value

    return TrustedRuntimeClock(
        wall_time_ns=next_wall,
        monotonic_ns=next_mono,
    )


class ProfileBackedStepTests(unittest.TestCase):
    def profile_path(self, root: Path, *, model: str = "test-model") -> Path:
        path = root / "profile.json"
        payload = {
            "schema": "kaliv-consciousness-core/cognitive-profile-config/v1",
            "provider": "mock",
            "model": model,
            "reasoning_depth": 0.7,
            "planning_capacity": 0.65,
            "context_capacity_tokens": 8192,
            "multimodal_capacity": 0.0,
            "tool_reasoning": 0.0,
            "uncertainty_calibration": 0.8,
            "calibration_refs": [
                "operator-calibration:test:v1",
                "evaluation:test:bounded",
            ],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def session(self, *, engine=None, min_interval_ms: int = 500):
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
            bootstrap_source_ref="runtime:test:c22b",
        )
        actual_engine = engine or Engine()
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(actual_engine),
            clock=deterministic_clock(),
            policy=SupervisorPolicy(
                schema="kaliv-consciousness-core/supervisor-policy/v1",
                min_cycle_interval_ms=min_interval_ms,
                max_events_per_cycle=4,
                production_activation=False,
            ),
        )
        return (
            ProductionCognitiveSession(
                supervisor_bridge=bridge,
                bootstrap_context=context,
            ),
            actual_engine,
        )

    def event(self, marker: str, *, sequence: int = 1):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind="user_turn",
            source_ref=f"event:test:{marker}",
            summary=f"C22-B event {marker}",
            salience=1.0,
            observed_sequence=sequence,
            production_activation=False,
        )

    def app(self, session, loader, *, loopback=True):
        app = FastAPI()
        if session is not None:
            app.state.consciousness_session = session
        app.include_router(
            build_consciousness_profile_step_router(
                profile_loader=loader,
                loopback_allowed=lambda _request: loopback,
            )
        )
        return app

    def test_exact_flag_contract_and_flag_off_mounts_no_route(self):
        old = os.environ.get(CONSCIOUSNESS_STEP_FLAG)
        try:
            os.environ.pop(CONSCIOUSNESS_STEP_FLAG, None)
            self.assertFalse(profile_step_enabled())
            for value in ("true", "yes", "on", "01", " 1 "):
                os.environ[CONSCIOUSNESS_STEP_FLAG] = value
                self.assertFalse(profile_step_enabled(), value)

            app = FastAPI()
            before_count = len(app.router.routes)
            os.environ.pop(CONSCIOUSNESS_STEP_FLAG, None)
            self.assertFalse(mount_consciousness_profile_step(app))
            self.assertEqual(len(app.router.routes), before_count)

            os.environ[CONSCIOUSNESS_STEP_FLAG] = "1"
            self.assertTrue(profile_step_enabled())
            self.assertTrue(
                mount_consciousness_profile_step(
                    app,
                    profile_loader=lambda: None,
                    loopback_allowed=lambda _request: True,
                )
            )
            mounted_count = len(app.router.routes)
            self.assertGreater(mounted_count, before_count)

            response = TestClient(app).post(COGNITION_STEP_PREFIX + "/step")
            self.assertEqual(response.status_code, 503)

            self.assertTrue(mount_consciousness_profile_step(app))
            self.assertEqual(len(app.router.routes), mounted_count)
        finally:
            if old is None:
                os.environ.pop(CONSCIOUSNESS_STEP_FLAG, None)
            else:
                os.environ[CONSCIOUSNESS_STEP_FLAG] = old

    def test_loopback_rejection_precedes_body_and_profile_io(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session()
            client = TestClient(self.app(session, loader, loopback=False))
            response = client.post(
                COGNITION_STEP_PREFIX + "/step",
                content=b'{"model":"caller-selected"}',
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(loader.calls, 0)
            self.assertEqual(engine.calls, 0)

    def test_request_body_must_be_empty_and_cannot_select_model_prompt_or_event(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session()
            client = TestClient(self.app(session, loader))
            for payload in (
                b'{"model":"evil"}',
                b'{"prompt":"evil"}',
                b'{"required_event_id":"cevt-' + b"9" * 32 + b'"}',
            ):
                response = client.post(
                    COGNITION_STEP_PREFIX + "/step",
                    content=payload,
                )
                self.assertEqual(response.status_code, 422)
            self.assertEqual(loader.calls, 0)
            self.assertEqual(engine.calls, 0)

    def test_missing_session_returns_503_before_profile_io(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            client = TestClient(self.app(None, loader))
            response = client.post(COGNITION_STEP_PREFIX + "/step")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(loader.calls, 0)

    def test_missing_profile_returns_generic_503_without_model_call(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.json"
            loader = CountingLoader(missing)
            session, engine = self.session()
            client = TestClient(self.app(session, loader))
            response = client.post(COGNITION_STEP_PREFIX + "/step")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(loader.calls, 1)
            self.assertEqual(engine.calls, 0)
            self.assertEqual(
                response.json()["detail"],
                "consciousness cognitive profile unavailable",
            )

    def test_idle_is_zero_call_and_context_is_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session()
            before = session.live_state
            client = TestClient(self.app(session, loader))
            response = client.post(COGNITION_STEP_PREFIX + "/step")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["decision"], "IDLE")
            self.assertEqual(body["model_calls"], 0)
            self.assertFalse(body["thought_engine_invoked"])
            self.assertFalse(body["context_updated"])
            self.assertEqual(body["completed_cycles"], 0)
            self.assertEqual(engine.calls, 0)
            self.assertEqual(session.live_state, before)

    def test_run_invokes_exactly_one_model_call_and_returns_no_inner_monologue(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session()
            event = self.event("1")
            session.submit(event)
            client = TestClient(self.app(session, loader))
            response = client.post(COGNITION_STEP_PREFIX + "/step")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["decision"], "RUN")
            self.assertEqual(body["selected_event_ids"], [event.event_id])
            self.assertEqual(body["model_calls"], 1)
            self.assertTrue(body["thought_engine_invoked"])
            self.assertTrue(body["context_updated"])
            self.assertEqual(body["completed_cycles"], 1)
            self.assertIsNotNone(body["transition_receipt_ref"])
            self.assertEqual(engine.calls, 1)
            raw = response.text
            self.assertNotIn("PRIVATE-INNER-MONOLOGUE-SENTINEL", raw)
            self.assertNotIn("interpretation", raw)
            self.assertNotIn("hypotheses", raw)
            self.assertFalse(body["execution_authority"])
            self.assertFalse(body["scheduling_authority"])
            self.assertFalse(body["durable_memory_write_authority"])
            self.assertFalse(body["production_activation"])

    def test_wait_after_run_is_zero_call_and_does_not_consume_pending_event(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session(min_interval_ms=500)
            session.submit(self.event("1", sequence=1))
            client = TestClient(self.app(session, loader))
            first = client.post(COGNITION_STEP_PREFIX + "/step")
            self.assertEqual(first.json()["decision"], "RUN")
            self.assertEqual(engine.calls, 1)

            second_event = self.event("2", sequence=2)
            session.submit(second_event)
            second = client.post(COGNITION_STEP_PREFIX + "/step")
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json()["decision"], "WAIT")
            self.assertEqual(second.json()["model_calls"], 0)
            self.assertEqual(engine.calls, 1)
            self.assertEqual(
                [e.event_id for e in session.supervisor_state.pending_events],
                [second_event.event_id],
            )

    def test_profile_is_freshly_loaded_on_each_explicit_request(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self.profile_path(root, model="model-a")
            loader = CountingLoader(path)
            session, engine = self.session()
            client = TestClient(self.app(session, loader))

            first = client.post(COGNITION_STEP_PREFIX + "/step")
            self.assertEqual(first.status_code, 200)
            first_id = first.json()["profile_id"]

            self.profile_path(root, model="model-b")
            second = client.post(COGNITION_STEP_PREFIX + "/step")
            self.assertEqual(second.status_code, 200)
            second_id = second.json()["profile_id"]

            self.assertEqual(loader.calls, 2)
            self.assertNotEqual(first_id, second_id)
            self.assertEqual(engine.calls, 0)

    def test_provider_failure_is_generic_and_private(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session(engine=FailingEngine())
            session.submit(self.event("1"))
            client = TestClient(self.app(session, loader))
            response = client.post(COGNITION_STEP_PREFIX + "/step")
            self.assertEqual(response.status_code, 502)
            self.assertEqual(
                response.json()["detail"],
                "consciousness cognition step failed",
            )
            self.assertNotIn("PRIVATE-PROVIDER-FAILURE-SENTINEL", response.text)
            self.assertEqual(engine.calls, 1)

    def test_one_http_request_never_repeats_cognition(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session(min_interval_ms=0)
            session.submit(self.event("1", sequence=1))
            session.submit(self.event("2", sequence=2))
            client = TestClient(self.app(session, loader))
            response = client.post(COGNITION_STEP_PREFIX + "/step")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["decision"], "RUN")
            self.assertEqual(engine.calls, 1)
            self.assertFalse(response.json()["automatic_repeat"])
            self.assertFalse(response.json()["internal_thread_created"])
            self.assertFalse(response.json()["internal_timer_created"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
