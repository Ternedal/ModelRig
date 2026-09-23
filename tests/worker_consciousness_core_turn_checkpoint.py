#!/usr/bin/env python3
"""C27-J user-turn/world checkpoint coupling tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_turn_checkpoint.py
"""
from __future__ import annotations

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
from app.consciousness_core.checkpoint_pressure import (  # noqa: E402
    CheckpointPressurePolicy,
)
from app.consciousness_core.policy_checkpoint import (  # noqa: E402
    PolicyDrivenSelfStateCheckpointAdapter,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)
from app.consciousness_core.user_turn_admission import (  # noqa: E402
    CONSCIOUSNESS_TURN_PREFIX,
    TURN_CHECKPOINT_FLAG,
    build_consciousness_user_turn_router,
    turn_checkpoint_enabled,
)


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        raise AssertionError("C27-J user-turn admission must not call model")


class FailingStore(SelfStateStore):
    def __init__(self, path):
        super().__init__(path)
        self.chain_calls = 0

    def write_chain(self, states):
        self.chain_calls += 1
        raise RuntimeError("simulated C27-J durable write failure")


class ExplodingCheckpointAdapter(PolicyDrivenSelfStateCheckpointAdapter):
    def __init__(self):
        self.calls = 0

    def maybe_checkpoint_once(self):
        self.calls += 1
        raise AssertionError("turn checkpoint gate-off touched service")


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


class TurnCheckpointTests(unittest.TestCase):
    def setUp(self):
        self._old_flag = os.environ.get(TURN_CHECKPOINT_FLAG)

    def tearDown(self):
        if self._old_flag is None:
            os.environ.pop(TURN_CHECKPOINT_FLAG, None)
        else:
            os.environ[TURN_CHECKPOINT_FLAG] = self._old_flag

    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            authority="operator_review",
            authority_ref="operator:test:c27j",
            source_refs=["registry:test:c27j"],
            production_activation=False,
        )
        durable = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c27j",
            world_state_ref="world-state:durable",
            workspace_ref="workspace:durable",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c27j"],
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
            body_source_ref="body:c27j",
            voice_source_ref="voice:c27j",
            registry_source_ref="registry:c27j",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=durable,
            active_person=person,
            bootstrap_source_ref="runtime:c27j",
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

    def policy(self):
        return CheckpointPressurePolicy(
            schema="kaliv-consciousness-core/checkpoint-pressure-policy/v1",
            checkpoint_transition_count=2,
            reserve_transition_slots=2,
            checkpoint_after_post_cycle=True,
            production_activation=False,
        )

    def app(self, session, checkpoint_service=None):
        app = FastAPI()
        app.state.consciousness_session = session
        if checkpoint_service is not None:
            app.state.consciousness_policy_checkpoint = checkpoint_service
        app.include_router(
            build_consciousness_user_turn_router(
                loopback_allowed=lambda _request: True,
            )
        )
        return app

    def post(self, client, *, turn_id, text="Hej fra C27-J"):
        return client.post(
            CONSCIOUSNESS_TURN_PREFIX + "/user-turn",
            json={
                "turn_id": turn_id,
                "user_text": text,
                "source_ref": f"backend-chat:{turn_id}",
            },
        )

    def test_exact_turn_checkpoint_flag_contract(self):
        os.environ.pop(TURN_CHECKPOINT_FLAG, None)
        self.assertFalse(turn_checkpoint_enabled())
        for value in ("0", "true", "yes", "on", "01", " 1 "):
            os.environ[TURN_CHECKPOINT_FLAG] = value
            self.assertFalse(turn_checkpoint_enabled(), value)
        os.environ[TURN_CHECKPOINT_FLAG] = "1"
        self.assertTrue(turn_checkpoint_enabled())

    def test_gate_off_never_invokes_checkpoint_service(self):
        os.environ[TURN_CHECKPOINT_FLAG] = "0"
        _authority, durable = self.durable()
        session, engine = self.session(durable)
        checkpoint = ExplodingCheckpointAdapter()
        client = TestClient(self.app(session, checkpoint))

        response = self.post(client, turn_id="turn-off")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["world_changed"])
        self.assertTrue(body["cognition_event_queued"])
        self.assertFalse(body["checkpoint_enabled"])
        self.assertEqual(body["checkpoint_evaluation_count"], 0)
        self.assertEqual(body["checkpoint_commit_count"], 0)
        self.assertFalse(body["self_state_store_write_applied"])
        self.assertEqual(checkpoint.calls, 0)
        self.assertEqual(engine.calls, 0)

    def test_gate_on_requires_service_before_world_mutation(self):
        os.environ[TURN_CHECKPOINT_FLAG] = "1"
        _authority, durable = self.durable()
        session, engine = self.session(durable)
        live_before = session.live_state
        pending_before = list(session.supervisor_state.pending_events)
        client = TestClient(self.app(session))

        response = self.post(client, turn_id="turn-no-service")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "consciousness checkpoint service unavailable",
        )
        self.assertEqual(session.live_state, live_before)
        self.assertEqual(
            session.supervisor_state.pending_events,
            pending_before,
        )
        self.assertEqual(engine.calls, 0)

    def test_new_turn_commits_when_world_threshold_is_reached(self):
        os.environ[TURN_CHECKPOINT_FLAG] = "1"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            authority, durable = self.durable()
            session, engine = self.session(durable)
            store = SelfStateStore(root / "self.json")
            store.bootstrap(durable, authority)
            checkpoint = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
                policy=self.policy(),
            )
            client = TestClient(self.app(session, checkpoint))

            response = self.post(client, turn_id="turn-commit")

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertTrue(body["world_changed"])
            self.assertFalse(body["replayed"])
            self.assertTrue(body["checkpoint_enabled"])
            self.assertEqual(body["checkpoint_evaluation_count"], 2)
            self.assertEqual(body["checkpoint_commit_count"], 1)
            self.assertEqual(body["checkpoint_last_outcome"], "COMMITTED")
            self.assertEqual(
                body["checkpoint_last_pressure"],
                "CHECKPOINT",
            )
            self.assertTrue(body["self_state_store_write_applied"])
            self.assertEqual(store.read(), session.live_state.state)
            self.assertIsNone(session.self_state_checkpoint_plan)
            self.assertEqual(engine.calls, 0)

    def test_replay_uses_preflight_only_and_creates_no_second_transition(self):
        os.environ[TURN_CHECKPOINT_FLAG] = "1"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            authority, durable = self.durable()
            session, _engine = self.session(durable)
            store = SelfStateStore(root / "self.json")
            store.bootstrap(durable, authority)
            checkpoint = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
                policy=self.policy(),
            )
            client = TestClient(self.app(session, checkpoint))

            first = self.post(client, turn_id="turn-replay")
            self.assertEqual(first.status_code, 200)
            live = session.live_state
            pending = list(session.supervisor_state.pending_events)

            replay = self.post(client, turn_id="turn-replay")
            self.assertEqual(replay.status_code, 200)
            body = replay.json()
            self.assertTrue(body["replayed"])
            self.assertFalse(body["world_changed"])
            self.assertFalse(body["cognition_event_queued"])
            self.assertEqual(body["checkpoint_evaluation_count"], 1)
            self.assertEqual(body["checkpoint_commit_count"], 0)
            self.assertEqual(body["checkpoint_last_outcome"], "IDLE")
            self.assertEqual(session.live_state, live)
            self.assertEqual(
                session.supervisor_state.pending_events,
                pending,
            )

    def test_post_admission_failure_is_replay_safe(self):
        os.environ[TURN_CHECKPOINT_FLAG] = "1"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            authority, durable = self.durable()
            session, engine = self.session(durable)
            store = FailingStore(root / "self.json")
            store.bootstrap(durable, authority)
            store.chain_calls = 0
            checkpoint = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
                policy=self.policy(),
            )
            client = TestClient(self.app(session, checkpoint))

            first = self.post(client, turn_id="turn-fail")

            self.assertEqual(first.status_code, 503)
            self.assertEqual(
                first.json()["detail"],
                "consciousness user-turn admitted but checkpoint failed",
            )
            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(engine.calls, 0)
            live_after = session.live_state
            pending_after = list(session.supervisor_state.pending_events)
            self.assertEqual(len(pending_after), 1)

            retry = self.post(client, turn_id="turn-fail")

            self.assertEqual(retry.status_code, 503)
            self.assertEqual(
                retry.json()["detail"],
                "consciousness checkpoint preflight failed",
            )
            self.assertEqual(store.chain_calls, 2)
            self.assertEqual(session.live_state, live_after)
            self.assertEqual(
                session.supervisor_state.pending_events,
                pending_after,
            )
            self.assertEqual(engine.calls, 0)

    def test_preflight_failure_blocks_next_turn_without_consuming_sequence(self):
        os.environ[TURN_CHECKPOINT_FLAG] = "1"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            authority, durable = self.durable()
            session, engine = self.session(durable)

            first = session.submit_reported_user_turn(
                turn_id="turn-existing",
                user_text="Existing pending durable world update",
                source_ref="backend-chat:turn-existing",
            )
            self.assertEqual(first.observed_sequence, 1)

            store = FailingStore(root / "self.json")
            store.bootstrap(durable, authority)
            store.chain_calls = 0
            checkpoint = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
                policy=self.policy(),
            )
            live_before = session.live_state
            pending_before = list(session.supervisor_state.pending_events)
            client = TestClient(self.app(session, checkpoint))

            response = self.post(client, turn_id="turn-blocked")

            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.json()["detail"],
                "consciousness checkpoint preflight failed",
            )
            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(session.live_state, live_before)
            self.assertEqual(
                session.supervisor_state.pending_events,
                pending_before,
            )
            self.assertEqual(engine.calls, 0)

            # The rejected route never consumed the next reported-turn sequence.
            # This direct assertion is about C21 sequence ownership only; the
            # checkpoint failure above must not have called the admission path.
            admitted = session.submit_reported_user_turn(
                turn_id="turn-blocked",
                user_text="Hej fra C27-J",
                source_ref="backend-chat:turn-blocked",
            )
            self.assertEqual(admitted.observed_sequence, 2)


if __name__ == "__main__":
    unittest.main()
