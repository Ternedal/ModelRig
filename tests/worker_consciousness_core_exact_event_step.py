#!/usr/bin/env python3
"""C22-C exact-event profile-backed one-shot cognition tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_exact_event_step.py
"""
from __future__ import annotations

import copy
import importlib.util
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
from app.consciousness_core.exact_event_step_api import (  # noqa: E402
    EVENT_STEP_FLAG,
    EVENT_STEP_PREFIX,
    build_consciousness_exact_event_step_router,
    exact_event_step_enabled,
    mount_consciousness_exact_event_step,
)
from app.consciousness_core.profile_source import load_cognitive_profile  # noqa: E402
from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402
from app.consciousness_core.supervisor import (  # noqa: E402
    CognitionEvent,
    SupervisorPolicy,
)
from app.consciousness_core.supervisor_lifecycle import ProductionSupervisorBridge  # noqa: E402


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
        payload["proposal_id"] = "thinkprop-" + "5" * 32
        payload["interpretation"] = "PRIVATE-EXACT-EVENT-INNER-MONOLOGUE"
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
        raise RuntimeError("PRIVATE-EXACT-EVENT-PROVIDER-FAILURE")


class CountingLoader:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return load_cognitive_profile(
            path=self.path,
            engine_instance_id="thought-engine:test:exact-event",
        )


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


class ExactEventStepTests(unittest.TestCase):
    def profile_path(self, root: Path) -> Path:
        path = root / "profile.json"
        path.write_text(
            json.dumps(
                {
                    "schema": (
                        "kaliv-consciousness-core/"
                        "cognitive-profile-config/v1"
                    ),
                    "provider": "mock",
                    "model": "exact-event-test-model",
                    "reasoning_depth": 0.7,
                    "planning_capacity": 0.7,
                    "context_capacity_tokens": 8192,
                    "multimodal_capacity": 0.0,
                    "tool_reasoning": 0.0,
                    "uncertainty_calibration": 0.8,
                    "calibration_refs": ["operator-calibration:c22c-test"],
                }
            ),
            encoding="utf-8",
        )
        return path

    def session(self, *, engine=None, policy=None):
        state = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=110,
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

    def event(
        self,
        marker: str,
        *,
        salience: float = 1.0,
        sequence: int = 1,
    ):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind="user_turn",
            source_ref=f"event:test:{marker}",
            summary=f"C22-C required event {marker}",
            salience=salience,
            observed_sequence=sequence,
            production_activation=False,
        )

    def app(self, session, loader, *, loopback=True):
        app = FastAPI()
        if session is not None:
            app.state.consciousness_session = session
        app.include_router(
            build_consciousness_exact_event_step_router(
                profile_loader=loader,
                loopback_allowed=lambda _request: loopback,
            )
        )
        return app

    def post(self, client, event_id):
        return client.post(
            EVENT_STEP_PREFIX + "/step-event",
            json={"required_event_id": event_id},
        )

    def test_exact_flag_contract_and_flag_off_mounts_no_route(self):
        old = os.environ.get(EVENT_STEP_FLAG)
        try:
            os.environ.pop(EVENT_STEP_FLAG, None)
            self.assertFalse(exact_event_step_enabled())
            for value in ("true", "yes", "on", "01", " 1 "):
                os.environ[EVENT_STEP_FLAG] = value
                self.assertFalse(exact_event_step_enabled(), value)

            app = FastAPI()
            before_count = len(app.router.routes)
            os.environ.pop(EVENT_STEP_FLAG, None)
            self.assertFalse(mount_consciousness_exact_event_step(app))
            self.assertEqual(len(app.router.routes), before_count)

            os.environ[EVENT_STEP_FLAG] = "1"
            self.assertTrue(exact_event_step_enabled())
            self.assertTrue(
                mount_consciousness_exact_event_step(
                    app,
                    profile_loader=lambda: None,
                    loopback_allowed=lambda _request: True,
                )
            )
            mounted_count = len(app.router.routes)
            self.assertGreater(mounted_count, before_count)

            response = TestClient(app).post(
                EVENT_STEP_PREFIX + "/step-event",
                json={"required_event_id": "cevt-" + "1" * 32},
            )
            self.assertEqual(response.status_code, 503)

            self.assertTrue(mount_consciousness_exact_event_step(app))
            self.assertEqual(len(app.router.routes), mounted_count)
        finally:
            if old is None:
                os.environ.pop(EVENT_STEP_FLAG, None)
            else:
                os.environ[EVENT_STEP_FLAG] = old

    def test_loopback_rejection_precedes_body_and_profile_io(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session()
            client = TestClient(self.app(session, loader, loopback=False))
            response = client.post(
                EVENT_STEP_PREFIX + "/step-event",
                content=b'{"prompt":"private"}',
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(loader.calls, 0)
            self.assertEqual(engine.calls, 0)

    def test_body_accepts_only_required_event_id(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session()
            client = TestClient(self.app(session, loader))
            for body in (
                {},
                {"required_event_id": "not-an-event"},
                {
                    "required_event_id": "cevt-" + "1" * 32,
                    "model": "caller-selected",
                },
                {
                    "required_event_id": "cevt-" + "1" * 32,
                    "prompt": "caller-selected",
                },
            ):
                response = client.post(
                    EVENT_STEP_PREFIX + "/step-event",
                    json=body,
                )
                self.assertEqual(response.status_code, 422)
            self.assertEqual(loader.calls, 0)
            self.assertEqual(engine.calls, 0)

    def test_absent_required_event_fails_before_model(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session()
            before = session.live_state
            client = TestClient(self.app(session, loader))
            response = self.post(client, "cevt-" + "9" * 32)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(engine.calls, 0)
            self.assertEqual(session.live_state, before)
            self.assertEqual(session.supervisor_state.pending_events, [])

    def test_pending_but_unselected_required_event_fails_before_model(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session()
            required = self.event("f", salience=0.1, sequence=99)
            session.submit(required)
            for i, marker in enumerate(("1", "2", "3", "4"), start=1):
                session.submit(
                    self.event(marker, salience=1.0, sequence=i)
                )
            pending_before = list(session.supervisor_state.pending_events)
            before = session.live_state
            client = TestClient(self.app(session, loader))
            response = self.post(client, required.event_id)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(engine.calls, 0)
            self.assertEqual(session.live_state, before)
            self.assertEqual(
                session.supervisor_state.pending_events,
                pending_before,
            )

    def test_required_event_runs_exactly_one_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session()
            required = self.event("1")
            session.submit(required)
            client = TestClient(self.app(session, loader))
            response = self.post(client, required.event_id)
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["decision"], "RUN")
            self.assertTrue(body["required_event_selected"])
            self.assertIn(required.event_id, body["selected_event_ids"])
            self.assertEqual(body["model_calls"], 1)
            self.assertTrue(body["thought_engine_invoked"])
            self.assertTrue(body["context_updated"])
            self.assertEqual(engine.calls, 1)
            self.assertEqual(session.supervisor_state.pending_events, [])
            self.assertNotIn(
                "PRIVATE-EXACT-EVENT-INNER-MONOLOGUE",
                response.text,
            )
            self.assertFalse(body["execution_authority"])
            self.assertFalse(body["scheduling_authority"])
            self.assertFalse(body["durable_memory_write_authority"])

    def test_required_event_waits_without_model_call_or_consumption(self):
        # session.step() samples the trusted clock once for temporal/present
        # context and the supervisor samples it again for pacing. The deterministic
        # test clock advances 1000 ms per sample, so keep the interval above the
        # two-sample 2000 ms gap to exercise WAIT semantics rather than coupling
        # this regression to the internal number of clock consumers.
        policy = SupervisorPolicy(
            schema="kaliv-consciousness-core/supervisor-policy/v1",
            min_cycle_interval_ms=2500,
            max_events_per_cycle=4,
            production_activation=False,
        )
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session(policy=policy)
            first = self.event("1", sequence=1)
            session.submit(first)
            client = TestClient(self.app(session, loader))
            first_response = self.post(client, first.event_id)
            self.assertEqual(first_response.json()["decision"], "RUN")
            self.assertEqual(engine.calls, 1)

            required = self.event("2", sequence=2)
            session.submit(required)
            before = session.live_state
            wait = self.post(client, required.event_id)
            self.assertEqual(wait.status_code, 200)
            body = wait.json()
            self.assertEqual(body["decision"], "WAIT")
            self.assertFalse(body["required_event_selected"])
            self.assertEqual(body["selected_event_ids"], [])
            self.assertEqual(body["model_calls"], 0)
            self.assertFalse(body["thought_engine_invoked"])
            self.assertFalse(body["context_updated"])
            self.assertEqual(engine.calls, 1)
            self.assertEqual(session.live_state, before)
            self.assertEqual(
                [event.event_id for event in session.supervisor_state.pending_events],
                [required.event_id],
            )

    def test_profile_is_freshly_loaded_for_each_exact_event_step(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.profile_path(Path(td))
            loader = CountingLoader(path)
            session, engine = self.session()
            client = TestClient(self.app(session, loader))

            first = self.event("1", sequence=1)
            session.submit(first)
            self.assertEqual(self.post(client, first.event_id).status_code, 200)

            second = self.event("2", sequence=2)
            session.submit(second)
            response = self.post(client, second.event_id)
            # Depending on pacing this may be WAIT, but profile resolution must
            # still be fresh and no extra model call can occur on WAIT.
            self.assertEqual(response.status_code, 200)
            self.assertEqual(loader.calls, 2)
            self.assertLessEqual(engine.calls, 2)

    def test_provider_failure_is_generic_and_private(self):
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            session, engine = self.session(engine=FailingEngine())
            required = self.event("1")
            session.submit(required)
            client = TestClient(self.app(session, loader))
            response = self.post(client, required.event_id)
            self.assertEqual(response.status_code, 502)
            self.assertEqual(
                response.json()["detail"],
                "consciousness cognition step failed",
            )
            self.assertNotIn(
                "PRIVATE-EXACT-EVENT-PROVIDER-FAILURE",
                response.text,
            )
            self.assertEqual(engine.calls, 1)

    def test_generic_session_step_remains_backward_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            loaded = load_cognitive_profile(
                path=self.profile_path(Path(td)),
                engine_instance_id="thought-engine:test:generic",
            )
            self.assertIsNotNone(loaded)
            session, engine = self.session()
            session.submit(self.event("3"))
            import asyncio

            result = asyncio.run(session.step(profile=loaded.profile))
            self.assertEqual(result.supervisor_step.plan.decision, "RUN")
            self.assertTrue(result.context_updated)
            self.assertEqual(engine.calls, 1)



LIVE_PROBE_SPEC = importlib.util.spec_from_file_location(
    "consciousness_live_cycle_probe_test",
    ROOT / "scripts" / "consciousness_live_cycle_probe.py",
)
assert LIVE_PROBE_SPEC and LIVE_PROBE_SPEC.loader
live_probe = importlib.util.module_from_spec(LIVE_PROBE_SPEC)
sys.modules[LIVE_PROBE_SPEC.name] = live_probe
LIVE_PROBE_SPEC.loader.exec_module(live_probe)


class LiveCycleProbeContractTests(unittest.TestCase):
    def identity(self):
        return {
            "git_sha": "a" * 40,
            "branch": "qualification",
            "working_tree_clean": True,
        }

    def admission(self):
        return {
            "schema": "kaliv-consciousness-core/user-turn-admission/v1",
            "turn_ref": "chat-turn:" + "1" * 64,
            "evidence_ref": "world-evidence:" + "2" * 64,
            "cognition_event_id": "cevt-" + "3" * 32,
            "world_changed": True,
            "replayed": False,
            "cognition_event_queued": True,
            "epistemic_status": "reported",
            "confidence": 1.0,
            "observed_sequence": 7,
            "model_calls": 0,
            "checkpoint_enabled": False,
            "checkpoint_evaluation_count": 0,
            "checkpoint_commit_count": 0,
            "checkpoint_last_outcome": None,
            "checkpoint_last_pressure": None,
            "self_state_store_write_applied": False,
            "durable_memory_write_authority": False,
            "execution_authority": False,
            "scheduling_authority": False,
            "production_activation": False,
        }

    def step(self, decision="RUN"):
        event_id = "cevt-" + "3" * 32
        base = {
            "schema": "kaliv-consciousness-core/exact-event-step-receipt/v1",
            "required_event_id": event_id,
            "profile_ref": "cognitive-profile:" + "4" * 64,
            "profile_id": "cog-" + "5" * 32,
            "profile_config_sha256": "6" * 64,
            "self_state_ref": "self-state:" + "7" * 64,
            "world_state_ref": "world-state:" + "8" * 64,
            "workspace_ref": "workspace:" + "9" * 64,
            "completed_cycles": 1,
            "automatic_repeat": False,
            "internal_thread_created": False,
            "internal_timer_created": False,
            "checkpoint_enabled": False,
            "checkpoint_evaluation_count": 0,
            "checkpoint_commit_count": 0,
            "checkpoint_last_outcome": None,
            "checkpoint_last_pressure": None,
            "self_state_store_write_applied": False,
            "durable_memory_write_authority": False,
            "execution_authority": False,
            "scheduling_authority": False,
            "production_activation": False,
        }
        if decision == "WAIT":
            base.update(
                {
                    "decision": "WAIT",
                    "selected_event_ids": [],
                    "required_event_selected": False,
                    "thought_engine_invoked": False,
                    "model_calls": 0,
                    "transition_receipt_ref": None,
                    "context_updated": False,
                }
            )
        else:
            base.update(
                {
                    "decision": "RUN",
                    "selected_event_ids": [event_id],
                    "required_event_selected": True,
                    "thought_engine_invoked": True,
                    "model_calls": 1,
                    "transition_receipt_ref": "transition:" + "a" * 64,
                    "context_updated": True,
                }
            )
        return base

    def clock(self):
        values = iter([1.0, 1.01, 2.0, 2.02, 3.0, 3.03])
        return lambda: next(values)

    def test_live_probe_accepts_one_exact_run(self):
        calls = []

        def http_json(method, url, body, *, timeout):
            calls.append((method, url, body, timeout))
            if url.endswith("/healthz"):
                return 200, {"ok": True}
            if url.endswith("/user-turn"):
                return 200, self.admission()
            if url.endswith("/step-event"):
                return 200, self.step("RUN")
            raise AssertionError(url)

        report = live_probe.run_live_cycle(
            "http://127.0.0.1:8099",
            root=ROOT,
            http_json=http_json,
            sleep_fn=lambda _seconds: None,
            clock=self.clock(),
            identity=self.identity(),
            probe_nonce="b" * 32,
        )
        self.assertTrue(report["gate"]["passed"])
        self.assertTrue(report["gate"]["live_cycle_proven"])
        self.assertFalse(report["gate"]["full_lifecycle_qualified"])
        self.assertFalse(report["gate"]["release_gate_satisfied"])
        self.assertEqual(report["cycle"]["model_calls"], 1)
        self.assertEqual(report["cycle"]["wait_count"], 0)
        self.assertFalse(report["authority"]["production_activation"])
        self.assertEqual(len(calls), 3)

    def test_live_probe_allows_bounded_wait_then_run(self):
        steps = iter([self.step("WAIT"), self.step("RUN")])
        sleeps = []

        def http_json(method, url, body, *, timeout):
            if url.endswith("/healthz"):
                return 200, {"ok": True}
            if url.endswith("/user-turn"):
                return 200, self.admission()
            if url.endswith("/step-event"):
                return 200, next(steps)
            raise AssertionError(url)

        report = live_probe.run_live_cycle(
            "http://localhost:8099",
            root=ROOT,
            http_json=http_json,
            sleep_fn=sleeps.append,
            clock=self.clock(),
            identity=self.identity(),
            probe_nonce="c" * 32,
        )
        self.assertEqual(report["cycle"]["attempts"], 2)
        self.assertEqual(report["cycle"]["wait_count"], 1)
        self.assertEqual(sleeps, [live_probe.WAIT_DELAY_SECONDS])

    def test_live_probe_rejects_authority_overclaim(self):
        bad = self.step("RUN")
        bad["production_activation"] = True

        def http_json(method, url, body, *, timeout):
            if url.endswith("/healthz"):
                return 200, {"ok": True}
            if url.endswith("/user-turn"):
                return 200, self.admission()
            return 200, bad

        with self.assertRaisesRegex(
            live_probe.LiveCycleProbeError,
            "overclaimed production_activation",
        ):
            live_probe.run_live_cycle(
                "http://127.0.0.1:8099",
                root=ROOT,
                http_json=http_json,
                sleep_fn=lambda _seconds: None,
                clock=self.clock(),
                identity=self.identity(),
                probe_nonce="d" * 32,
            )

    def test_live_probe_rejects_non_loopback_worker(self):
        with self.assertRaisesRegex(
            live_probe.LiveCycleProbeError,
            "must be loopback",
        ):
            live_probe.run_live_cycle(
                "http://192.168.1.50:8099",
                root=ROOT,
                identity=self.identity(),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
