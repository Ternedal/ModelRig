#!/usr/bin/env python3
"""C27-G production policy-checkpoint service lifecycle tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_policy_checkpoint_lifecycle.py
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
from app.consciousness_core.policy_checkpoint import (  # noqa: E402
    PolicyDrivenSelfStateCheckpointAdapter,
)
from app.consciousness_core.policy_checkpoint_lifecycle import (  # noqa: E402
    POLICY_CHECKPOINT_SERVICE_FLAG,
    PolicyCheckpointServiceError,
    compose_policy_checkpoint_service_lifespan,
    policy_checkpoint_service_enabled,
    production_policy_checkpoint_service_factory,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
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
        raise AssertionError("C27-G service lifecycle must not call model")


class CountingStore(SelfStateStore):
    def __init__(self, path):
        super().__init__(path)
        self.read_calls = 0
        self.chain_calls = 0

    def read(self):
        self.read_calls += 1
        return super().read()

    def write_chain(self, states):
        self.chain_calls += 1
        return super().write_chain(states)


class PolicyCheckpointLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._old_flag = os.environ.get(POLICY_CHECKPOINT_SERVICE_FLAG)

    def tearDown(self):
        if self._old_flag is None:
            os.environ.pop(POLICY_CHECKPOINT_SERVICE_FLAG, None)
        else:
            os.environ[POLICY_CHECKPOINT_SERVICE_FLAG] = self._old_flag

    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            authority="operator_review",
            authority_ref="operator:test:c27g",
            source_refs=["registry:test:c27g"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c27g",
            world_state_ref="world-state:durable",
            workspace_ref="workspace:durable",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c27g"],
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
            body_source_ref="body:c27g",
            voice_source_ref="voice:c27g",
            registry_source_ref="registry:c27g",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=durable,
            active_person=person,
            bootstrap_source_ref="runtime:c27g",
        )
        return ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(Engine()),
                clock=deterministic_clock(),
            ),
            bootstrap_context=context,
            durable_anchor_state=durable,
        )

    def test_exact_flag_contract(self):
        os.environ.pop(POLICY_CHECKPOINT_SERVICE_FLAG, None)
        self.assertFalse(policy_checkpoint_service_enabled())
        for value in ("0", "true", "yes", "on", "01", " 1 "):
            os.environ[POLICY_CHECKPOINT_SERVICE_FLAG] = value
            self.assertFalse(policy_checkpoint_service_enabled(), value)
        os.environ[POLICY_CHECKPOINT_SERVICE_FLAG] = "1"
        self.assertTrue(policy_checkpoint_service_enabled())

    def test_flag_off_touches_no_session_or_store(self):
        os.environ[POLICY_CHECKPOINT_SERVICE_FLAG] = "0"

        class ExplodingState:
            @property
            def consciousness_session(self):
                raise AssertionError("flag-off touched app session")

        def explode_store():
            raise AssertionError("flag-off touched SelfStateStore")

        app = SimpleNamespace(state=ExplodingState())
        result = production_policy_checkpoint_service_factory(
            app,
            store_factory=explode_store,
        )
        self.assertIsNone(result)

    def test_enabled_without_session_touches_no_store(self):
        def explode_store():
            raise AssertionError("missing-session path touched store")

        app = SimpleNamespace(state=SimpleNamespace())
        result = production_policy_checkpoint_service_factory(
            app,
            enabled_fn=lambda: True,
            store_factory=explode_store,
        )
        self.assertIsNone(result)

    def test_factory_constructs_service_without_store_io(self):
        authority, durable = self.durable()
        session = self.session(durable)
        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, authority)
            store.read_calls = 0
            store.chain_calls = 0
            app = SimpleNamespace(
                state=SimpleNamespace(consciousness_session=session)
            )

            service = production_policy_checkpoint_service_factory(
                app,
                enabled_fn=lambda: True,
                store_factory=lambda: store,
            )

            self.assertIsInstance(
                service,
                PolicyDrivenSelfStateCheckpointAdapter,
            )
            self.assertEqual(store.read_calls, 0)
            self.assertEqual(store.chain_calls, 0)

    def test_lifecycle_exposes_service_only_while_inner_session_is_live(self):
        async def scenario():
            authority, durable = self.durable()
            session = self.session(durable)
            events = []
            app = SimpleNamespace(state=SimpleNamespace())

            with tempfile.TemporaryDirectory() as td:
                store = CountingStore(Path(td) / "self.json")
                store.bootstrap(durable, authority)
                store.read_calls = 0
                store.chain_calls = 0

                @asynccontextmanager
                async def inner(inner_app):
                    inner_app.state.consciousness_session = session
                    events.append("session:open")
                    try:
                        yield
                    finally:
                        self.assertFalse(
                            hasattr(
                                inner_app.state,
                                "consciousness_policy_checkpoint",
                            )
                        )
                        events.append("session:close")
                        session.close()
                        delattr(inner_app.state, "consciousness_session")

                def factory(inner_app):
                    events.append("service:create")
                    return production_policy_checkpoint_service_factory(
                        inner_app,
                        enabled_fn=lambda: True,
                        store_factory=lambda: store,
                    )

                composed = compose_policy_checkpoint_service_lifespan(
                    inner,
                    service_factory=factory,
                )

                async with composed(app):
                    events.append("serve")
                    self.assertTrue(
                        hasattr(
                            app.state,
                            "consciousness_policy_checkpoint",
                        )
                    )
                    self.assertIs(
                        app.state.consciousness_policy_checkpoint,
                        getattr(
                            app.state,
                            "consciousness_policy_checkpoint",
                        ),
                    )
                    self.assertFalse(session.closed)
                    self.assertEqual(store.read_calls, 0)
                    self.assertEqual(store.chain_calls, 0)

                self.assertEqual(
                    events,
                    [
                        "session:open",
                        "service:create",
                        "serve",
                        "session:close",
                    ],
                )
                self.assertTrue(session.closed)
                self.assertEqual(store.read_calls, 0)
                self.assertEqual(store.chain_calls, 0)

        asyncio.run(scenario())

    def test_closed_session_rejected_before_store_construction(self):
        _authority, durable = self.durable()
        session = self.session(durable)
        session.close()
        app = SimpleNamespace(
            state=SimpleNamespace(consciousness_session=session)
        )

        def explode_store():
            raise AssertionError("closed-session path touched store")

        with self.assertRaisesRegex(
            PolicyCheckpointServiceError,
            "closed session",
        ):
            production_policy_checkpoint_service_factory(
                app,
                enabled_fn=lambda: True,
                store_factory=explode_store,
            )


if __name__ == "__main__":
    unittest.main()
