#!/usr/bin/env python3
"""C27-D graceful-shutdown SelfState checkpoint lifecycle tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_checkpoint_lifecycle.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

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
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.self_state_checkpoint_lifecycle import (  # noqa: E402
    SELF_STATE_CHECKPOINT_FLAG,
    ShutdownSelfStateCheckpointError,
    compose_shutdown_self_state_checkpoint_lifespan,
    production_shutdown_checkpoint_factory,
    shutdown_self_state_checkpoint_enabled,
)
from app.consciousness_core.self_state_checkpoint_runtime import (  # noqa: E402
    ExplicitSelfStateCheckpointCoordinator,
    RuntimeSelfStateCheckpointResult,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)


def deterministic_clock():
    wall = iter(
        1_700_000_000_000_000_000 + i * 1_000_000_000
        for i in range(1, 24)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 24))
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class Engine:
    async def think(self, request, cognitive_profile, *, context=None):
        raise AssertionError("C27-D shutdown checkpoint must not call model")


class FakeCoordinator(ExplicitSelfStateCheckpointCoordinator):
    def __init__(self, events, *, fail=False):
        self.events = events
        self.fail = fail
        self.calls = 0

    def checkpoint_once(self):
        self.calls += 1
        self.events.append("checkpoint")
        if self.fail:
            raise RuntimeError("simulated checkpoint failure")
        return RuntimeSelfStateCheckpointResult(
            schema=(
                "kaliv-consciousness-core/"
                "runtime-self-state-checkpoint-result/v1"
            ),
            outcome="IDLE",
            plan_ref=None,
            store_receipt_ref=None,
            transition_count=0,
            revision_before=None,
            revision_after=None,
            self_state_store_write_applied=False,
            ledger_reanchored=False,
            intermediate_history_persisted=False,
            model_calls=0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )


class ShutdownCheckpointLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._old_flag = os.environ.get(SELF_STATE_CHECKPOINT_FLAG)

    def tearDown(self):
        if self._old_flag is None:
            os.environ.pop(SELF_STATE_CHECKPOINT_FLAG, None)
        else:
            os.environ[SELF_STATE_CHECKPOINT_FLAG] = self._old_flag

    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            authority="operator_review",
            authority_ref="operator:test:c27d",
            source_refs=["registry:test:c27d"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c27d",
            world_state_ref="world-state:durable",
            workspace_ref="workspace:durable",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c27d"],
            ),
        )
        return authority, state

    def session(self, durable):
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=durable.person_id,
            person_revision=durable.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c27d",
            voice_source_ref="voice:c27d",
            registry_source_ref="registry:c27d",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=durable,
            active_person=person,
            bootstrap_source_ref="runtime:c27d",
        )
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(Engine()),
            clock=deterministic_clock(),
        )
        return ProductionCognitiveSession(
            supervisor_bridge=bridge,
            bootstrap_context=context,
            durable_anchor_state=durable,
        )

    def test_exact_flag_contract(self):
        os.environ.pop(SELF_STATE_CHECKPOINT_FLAG, None)
        self.assertFalse(shutdown_self_state_checkpoint_enabled())
        for value in ("0", "true", "yes", "on", "01", " 1 "):
            os.environ[SELF_STATE_CHECKPOINT_FLAG] = value
            self.assertFalse(
                shutdown_self_state_checkpoint_enabled(),
                value,
            )
        os.environ[SELF_STATE_CHECKPOINT_FLAG] = "1"
        self.assertTrue(shutdown_self_state_checkpoint_enabled())

    def test_flag_off_touches_no_session_or_store(self):
        os.environ[SELF_STATE_CHECKPOINT_FLAG] = "0"

        class ExplodingState:
            @property
            def consciousness_session(self):
                raise AssertionError("flag-off touched app session")

        def explode_store():
            raise AssertionError("flag-off touched SelfStateStore")

        app = SimpleNamespace(state=ExplodingState())
        result = production_shutdown_checkpoint_factory(
            app,
            store_factory=explode_store,
        )
        self.assertIsNone(result)

    def test_enabled_without_session_touches_no_store(self):
        def explode_store():
            raise AssertionError("missing-session path touched store")

        app = SimpleNamespace(state=SimpleNamespace())
        result = production_shutdown_checkpoint_factory(
            app,
            enabled_fn=lambda: True,
            store_factory=explode_store,
        )
        self.assertIsNone(result)

    def test_lifecycle_checkpoints_before_inner_session_exit(self):
        async def scenario():
            events = []
            app = SimpleNamespace(state=SimpleNamespace())
            coordinator = FakeCoordinator(events)

            @asynccontextmanager
            async def inner(_app):
                events.append("inner:enter")
                try:
                    yield
                finally:
                    events.append("inner:exit")

            composed = compose_shutdown_self_state_checkpoint_lifespan(
                inner,
                coordinator_factory=lambda _app: coordinator,
            )
            async with composed(app):
                events.append("serve")

            self.assertEqual(
                events,
                [
                    "inner:enter",
                    "serve",
                    "checkpoint",
                    "inner:exit",
                ],
            )
            self.assertEqual(coordinator.calls, 1)

        asyncio.run(scenario())

    def test_checkpoint_failure_propagates_and_inner_teardown_still_runs(self):
        async def scenario():
            events = []
            app = SimpleNamespace(state=SimpleNamespace())
            coordinator = FakeCoordinator(events, fail=True)

            @asynccontextmanager
            async def inner(_app):
                events.append("inner:enter")
                try:
                    yield
                finally:
                    events.append("inner:exit")

            composed = compose_shutdown_self_state_checkpoint_lifespan(
                inner,
                coordinator_factory=lambda _app: coordinator,
            )
            with self.assertRaisesRegex(
                ShutdownSelfStateCheckpointError,
                "graceful-shutdown SelfState checkpoint failed",
            ):
                async with composed(app):
                    events.append("serve")

            self.assertEqual(
                events,
                [
                    "inner:enter",
                    "serve",
                    "checkpoint",
                    "inner:exit",
                ],
            )
            self.assertEqual(coordinator.calls, 1)

        asyncio.run(scenario())

    def test_real_shutdown_persists_bootstrap_transition_before_close(self):
        async def scenario():
            authority, durable = self.durable()
            session = self.session(durable)
            app = SimpleNamespace(state=SimpleNamespace())
            with tempfile.TemporaryDirectory() as td:
                store = SelfStateStore(Path(td) / "self.json")
                store.bootstrap(durable, authority)

                @asynccontextmanager
                async def inner(inner_app):
                    inner_app.state.consciousness_session = session
                    try:
                        yield
                    finally:
                        self.assertEqual(store.read(), session.live_state.state)
                        session.close()
                        delattr(inner_app.state, "consciousness_session")

                def factory(inner_app):
                    return production_shutdown_checkpoint_factory(
                        inner_app,
                        enabled_fn=lambda: True,
                        store_factory=lambda: store,
                    )

                composed = compose_shutdown_self_state_checkpoint_lifespan(
                    inner,
                    coordinator_factory=factory,
                )
                async with composed(app):
                    self.assertEqual(store.read(), durable)
                    self.assertFalse(session.closed)
                    self.assertIsNotNone(session.self_state_checkpoint_plan)

                self.assertTrue(session.closed)
                self.assertEqual(store.read(), session.live_state.state)
                self.assertIsNone(session.self_state_checkpoint_plan)

        asyncio.run(scenario())

    def test_factory_rejects_closed_session_before_store(self):
        _authority, durable = self.durable()
        session = self.session(durable)
        session.close()
        app = SimpleNamespace(
            state=SimpleNamespace(consciousness_session=session)
        )

        def explode_store():
            raise AssertionError("closed-session path touched store")

        with self.assertRaisesRegex(
            ShutdownSelfStateCheckpointError,
            "closed cognitive session",
        ):
            production_shutdown_checkpoint_factory(
                app,
                enabled_fn=lambda: True,
                store_factory=explode_store,
            )


if __name__ == "__main__":
    unittest.main()
