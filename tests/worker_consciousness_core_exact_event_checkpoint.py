#!/usr/bin/env python3
"""C27-I exact-event checkpoint coupling tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_exact_event_checkpoint.py
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
    ProductionCognitiveSession,
    SelfAffect,
    SelfBootstrapAuthority,
    SelfStateStore,
    bootstrap_runtime_session,
    bootstrap_self_state,
)
from app.consciousness_core.exact_event_step_api import (  # noqa: E402
    EVENT_CHECKPOINT_FLAG,
    EVENT_STEP_PREFIX,
    build_consciousness_exact_event_step_router,
    exact_event_checkpoint_enabled,
)
from app.consciousness_core.policy_checkpoint import (  # noqa: E402
    PolicyDrivenSelfStateCheckpointAdapter,
)
from app.consciousness_core.profile_source import (  # noqa: E402
    load_cognitive_profile,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.supervisor import CognitionEvent  # noqa: E402
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + "8" * 32
        payload["interpretation"] = "PRIVATE-C27I-INNER-MONOLOGUE"
        payload["attention_suggestions"] = []
        payload["candidate_intentions"] = []
        payload["predicted_outcomes"] = []
        payload["memory_queries"] = []
        payload["response_intent"] = None
        payload["body_intent"] = None
        payload["uncertainty"] = 0.1
        return payload


class CountingLoader:
    def __init__(self, path):
        self.path = path
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return load_cognitive_profile(
            path=self.path,
            engine_instance_id="thought-engine:test:c27i",
        )


class FailingStore(SelfStateStore):
    def __init__(self, path):
        super().__init__(path)
        self.chain_calls = 0

    def write_chain(self, states):
        self.chain_calls += 1
        raise RuntimeError("simulated C27-I durable write failure")


class ExplodingCheckpointAdapter(PolicyDrivenSelfStateCheckpointAdapter):
    def __init__(self):
        self.calls = 0

    def maybe_checkpoint_once(self):
        self.calls += 1
        raise AssertionError("checkpoint gate-off touched service")


def deterministic_clock():
    wall = iter(
        1_700_000_000_000_000_000 + i * 1_000_000_000
        for i in range(1, 32)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 32))
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class ExactEventCheckpointTests(unittest.TestCase):
    def setUp(self):
        self._old_flag = os.environ.get(EVENT_CHECKPOINT_FLAG)

    def tearDown(self):
        if self._old_flag is None:
            os.environ.pop(EVENT_CHECKPOINT_FLAG, None)
        else:
            os.environ[EVENT_CHECKPOINT_FLAG] = self._old_flag

    def profile_path(self, root):
        path = root / "profile.json"
        path.write_text(
            json.dumps(
                {
                    "schema": (
                        "kaliv-consciousness-core/"
                        "cognitive-profile-config/v1"
                    ),
                    "provider": "mock",
                    "model": "c27i-model",
                    "reasoning_depth": 0.7,
                    "planning_capacity": 0.7,
                    "context_capacity_tokens": 8192,
                    "multimodal_capacity": 0.0,
                    "tool_reasoning": 0.0,
                    "uncertainty_calibration": 0.8,
                    "calibration_refs": ["operator-calibration:c27i"],
                }
            ),
            encoding="utf-8",
        )
        return path

    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            authority="operator_review",
            authority_ref="operator:test:c27i",
            source_refs=["registry:test:c27i"],
            production_activation=False,
        )
        durable = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c27i",
            world_state_ref="world-state:durable",
            workspace_ref="workspace:durable",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c27i"],
            ),
        )
        return authority, durable

    def session(self, durable):
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=durable.person_id,
            person_revision=durable.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c27i",
            voice_source_ref="voice:c27i",
            registry_source_ref="registry:c27i",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=durable,
            active_person=person,
            bootstrap_source_ref="runtime:c27i",
        )
        engine = Engine()
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(engine),
            clock=deterministic_clock(),
        )
        return (
            ProductionCognitiveSession(
                supervisor_bridge=bridge,
                bootstrap_context=context,
                durable_anchor_state=durable,
            ),
            engine,
        )

    def event(self):
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + "7" * 32,
            kind="user_turn",
            source_ref="event:test:c27i",
            summary="C27-I exact required event.",
            salience=1.0,
            observed_sequence=2,
            production_activation=False,
        )

    def app(self, session, loader, checkpoint_service=None):
        app = FastAPI()
        app.state.consciousness_session = session
        if checkpoint_service is not None:
            app.state.consciousness_policy_checkpoint = checkpoint_service
        app.include_router(
            build_consciousness_exact_event_step_router(
                profile_loader=loader,
                loopback_allowed=lambda _request: True,
            )
        )
        return app

    def post(self, client, event_id):
        return client.post(
            EVENT_STEP_PREFIX + "/step-event",
            json={"required_event_id": event_id},
        )

    def test_exact_checkpoint_flag_contract(self):
        os.environ.pop(EVENT_CHECKPOINT_FLAG, None)
        self.assertFalse(exact_event_checkpoint_enabled())
        for value in ("0", "true", "yes", "on", "01", " 1 "):
            os.environ[EVENT_CHECKPOINT_FLAG] = value
            self.assertFalse(exact_event_checkpoint_enabled(), value)
        os.environ[EVENT_CHECKPOINT_FLAG] = "1"
        self.assertTrue(exact_event_checkpoint_enabled())

    def test_gate_off_never_invokes_checkpoint_service(self):
        os.environ[EVENT_CHECKPOINT_FLAG] = "0"
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            _authority, durable = self.durable()
            session, engine = self.session(durable)
            event = self.event()
            session.submit(event)
            checkpoint = ExplodingCheckpointAdapter()
            client = TestClient(self.app(session, loader, checkpoint))

            response = self.post(client, event.event_id)

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["decision"], "RUN")
            self.assertFalse(body["checkpoint_enabled"])
            self.assertEqual(body["checkpoint_evaluation_count"], 0)
            self.assertEqual(body["checkpoint_commit_count"], 0)
            self.assertFalse(body["self_state_store_write_applied"])
            self.assertEqual(checkpoint.calls, 0)
            self.assertEqual(engine.calls, 1)

    def test_gate_on_requires_service_before_profile_or_model(self):
        os.environ[EVENT_CHECKPOINT_FLAG] = "1"
        with tempfile.TemporaryDirectory() as td:
            loader = CountingLoader(self.profile_path(Path(td)))
            _authority, durable = self.durable()
            session, engine = self.session(durable)
            event = self.event()
            session.submit(event)
            client = TestClient(self.app(session, loader))

            response = self.post(client, event.event_id)

            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.json()["detail"],
                "consciousness checkpoint service unavailable",
            )
            self.assertEqual(loader.calls, 0)
            self.assertEqual(engine.calls, 0)
            self.assertEqual(
                [item.event_id for item in session.supervisor_state.pending_events],
                [event.event_id],
            )

    def test_successful_run_holds_preflight_then_commits_post_run(self):
        os.environ[EVENT_CHECKPOINT_FLAG] = "1"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            loader = CountingLoader(self.profile_path(root))
            authority, durable = self.durable()
            session, engine = self.session(durable)
            store = SelfStateStore(root / "self.json")
            store.bootstrap(durable, authority)
            checkpoint = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
            )
            event = self.event()
            session.submit(event)
            client = TestClient(self.app(session, loader, checkpoint))

            response = self.post(client, event.event_id)

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["decision"], "RUN")
            self.assertTrue(body["checkpoint_enabled"])
            self.assertEqual(body["checkpoint_evaluation_count"], 2)
            self.assertEqual(body["checkpoint_commit_count"], 1)
            self.assertEqual(body["checkpoint_last_outcome"], "COMMITTED")
            self.assertEqual(body["checkpoint_last_pressure"], "CHECKPOINT")
            self.assertTrue(body["self_state_store_write_applied"])
            self.assertEqual(engine.calls, 1)
            self.assertEqual(store.read(), session.live_state.state)
            self.assertIsNone(session.self_state_checkpoint_plan)
            self.assertNotIn("PRIVATE-C27I-INNER-MONOLOGUE", response.text)

    def test_post_run_checkpoint_failure_never_replays_cognition(self):
        os.environ[EVENT_CHECKPOINT_FLAG] = "1"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            loader = CountingLoader(self.profile_path(root))
            authority, durable = self.durable()
            session, engine = self.session(durable)
            store = FailingStore(root / "self.json")
            store.bootstrap(durable, authority)
            store.chain_calls = 0
            checkpoint = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
            )
            event = self.event()
            session.submit(event)
            client = TestClient(self.app(session, loader, checkpoint))

            first = self.post(client, event.event_id)

            self.assertEqual(first.status_code, 503)
            self.assertEqual(
                first.json()["detail"],
                "consciousness cognition completed but checkpoint failed",
            )
            self.assertEqual(engine.calls, 1)
            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(session.supervisor_state.pending_events, [])
            self.assertIsNotNone(session.self_state_checkpoint_plan)

            retry = self.post(client, event.event_id)

            self.assertEqual(retry.status_code, 503)
            self.assertEqual(
                retry.json()["detail"],
                "consciousness checkpoint preflight failed",
            )
            self.assertEqual(engine.calls, 1)
            self.assertEqual(store.chain_calls, 2)

    def test_preflight_store_failure_blocks_model_call(self):
        os.environ[EVENT_CHECKPOINT_FLAG] = "1"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            loader = CountingLoader(self.profile_path(root))
            authority, durable = self.durable()
            session, engine = self.session(durable)
            # Force policy CHECKPOINT before the route by lowering threshold
            # through a real adapter is unnecessary: one prior successful RUN
            # creates post-cycle pressure. We create that RUN with checkpoint
            # gate off, then enable the failing checkpoint before the next event.
            event = self.event()
            session.submit(event)

            loaded = loader()
            self.assertIsNotNone(loaded)
            import asyncio

            result = asyncio.run(
                session.step(
                    profile=loaded.profile,
                    required_event_id=event.event_id,
                )
            )
            self.assertEqual(result.supervisor_step.plan.decision, "RUN")
            self.assertEqual(engine.calls, 1)

            next_event = CognitionEvent(
                schema="kaliv-consciousness-core/cognition-event/v1",
                event_id="cevt-" + "8" * 32,
                kind="user_turn",
                source_ref="event:test:c27i:next",
                summary="C27-I second required event.",
                salience=1.0,
                observed_sequence=3,
                production_activation=False,
            )
            session.submit(next_event)

            store = FailingStore(root / "self.json")
            store.bootstrap(durable, authority)
            store.chain_calls = 0
            checkpoint = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
            )
            client = TestClient(self.app(session, loader, checkpoint))
            loader_before = loader.calls

            response = self.post(client, next_event.event_id)

            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.json()["detail"],
                "consciousness checkpoint preflight failed",
            )
            self.assertEqual(loader.calls, loader_before)
            self.assertEqual(engine.calls, 1)
            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(
                [item.event_id for item in session.supervisor_state.pending_events],
                [next_event.event_id],
            )


if __name__ == "__main__":
    unittest.main()
