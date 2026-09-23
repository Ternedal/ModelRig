#!/usr/bin/env python3
"""C29-C policy-checkpoint liveness coupling tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_policy_checkpoint_liveness.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
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
from app.consciousness_core.checkpoint_pressure import (  # noqa: E402
    CheckpointPressurePolicy,
)
from app.consciousness_core.liveness import (  # noqa: E402
    RuntimeLivenessStore,
)
from app.consciousness_core.policy_checkpoint import (  # noqa: E402
    PolicyDrivenSelfStateCheckpointAdapter,
)
from app.consciousness_core.policy_checkpoint_lifecycle import (  # noqa: E402
    CHECKPOINT_LIVENESS_FLAG,
    checkpoint_liveness_enabled,
    production_policy_checkpoint_service_factory,
)
from app.consciousness_core.policy_checkpoint_liveness import (  # noqa: E402
    LivenessCoupledPolicyCheckpointAdapter,
    PolicyCheckpointLivenessError,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        raise AssertionError("C29-C must not call model")


def deterministic_clock():
    wall = iter(
        1_700_000_000_000_000_000 + i * 1_000_000_000
        for i in range(1, 64)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 64))
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class CountingLivenessStore(RuntimeLivenessStore):
    def __init__(self, path):
        super().__init__(path)
        self.read_calls = 0
        self.write_calls = 0

    def read(self):
        self.read_calls += 1
        return super().read()

    def write_next(self, witness):
        self.write_calls += 1
        return super().write_next(witness)


class FailingLivenessStore(RuntimeLivenessStore):
    def __init__(self, path):
        super().__init__(path)
        self.write_calls = 0

    def write_next(self, witness):
        self.write_calls += 1
        raise RuntimeError("simulated C29-C liveness write failure")


class PolicyCheckpointLivenessTests(unittest.TestCase):
    def setUp(self):
        self._old_flag = os.environ.get(CHECKPOINT_LIVENESS_FLAG)

    def tearDown(self):
        if self._old_flag is None:
            os.environ.pop(CHECKPOINT_LIVENESS_FLAG, None)
        else:
            os.environ[CHECKPOINT_LIVENESS_FLAG] = self._old_flag

    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            authority="operator_review",
            authority_ref="operator:test:c29c",
            source_refs=["registry:test:c29c"],
            production_activation=False,
        )
        durable = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c29c",
            world_state_ref="world-state:durable",
            workspace_ref="workspace:durable",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c29c"],
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
            body_source_ref="body:c29c",
            voice_source_ref="voice:c29c",
            registry_source_ref="registry:c29c",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=durable,
            active_person=person,
            bootstrap_source_ref="runtime:c29c",
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

    def policy(self, threshold=1):
        return CheckpointPressurePolicy(
            schema="kaliv-consciousness-core/checkpoint-pressure-policy/v1",
            checkpoint_transition_count=threshold,
            reserve_transition_slots=2,
            checkpoint_after_post_cycle=True,
            production_activation=False,
        )

    def test_exact_liveness_flag_contract(self):
        os.environ.pop(CHECKPOINT_LIVENESS_FLAG, None)
        self.assertFalse(checkpoint_liveness_enabled())
        for value in ("0", "true", "yes", "on", "01", " 1 "):
            os.environ[CHECKPOINT_LIVENESS_FLAG] = value
            self.assertFalse(checkpoint_liveness_enabled(), value)
        os.environ[CHECKPOINT_LIVENESS_FLAG] = "1"
        self.assertTrue(checkpoint_liveness_enabled())

    def test_policy_service_off_never_checks_liveness_gate(self):
        def explode():
            raise AssertionError("policy-off path checked C29-C gate")

        app = SimpleNamespace(state=SimpleNamespace())
        result = production_policy_checkpoint_service_factory(
            app,
            enabled_fn=lambda: False,
            liveness_enabled_fn=explode,
        )
        self.assertIsNone(result)

    def test_liveness_gate_off_keeps_plain_c27f_service(self):
        authority, durable = self.durable()
        session, engine = self.session(durable)
        with tempfile.TemporaryDirectory() as td:
            store = SelfStateStore(Path(td) / "self.json")
            store.bootstrap(durable, authority)

            def explode_store():
                raise AssertionError("liveness gate-off built C29-A store")

            service = production_policy_checkpoint_service_factory(
                SimpleNamespace(
                    state=SimpleNamespace(consciousness_session=session)
                ),
                enabled_fn=lambda: True,
                store_factory=lambda: store,
                liveness_enabled_fn=lambda: False,
                liveness_store_factory=explode_store,
            )

            self.assertIsInstance(
                service,
                PolicyDrivenSelfStateCheckpointAdapter,
            )
            self.assertNotIsInstance(
                service,
                LivenessCoupledPolicyCheckpointAdapter,
            )
            self.assertEqual(engine.calls, 0)

    def test_hold_performs_zero_liveness_io(self):
        authority, durable = self.durable()
        session, engine = self.session(durable)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self_store = SelfStateStore(root / "self.json")
            self_store.bootstrap(durable, authority)
            liveness_store = CountingLivenessStore(root / "liveness.json")
            service = LivenessCoupledPolicyCheckpointAdapter(
                session=session,
                store=self_store,
                liveness_store=liveness_store,
                policy=self.policy(threshold=8),
            )

            result = service.maybe_checkpoint_once()

            self.assertEqual(result.outcome, "HOLD")
            self.assertEqual(liveness_store.read_calls, 0)
            self.assertEqual(liveness_store.write_calls, 0)
            self.assertIsNone(service.last_liveness_receipt)
            self.assertEqual(engine.calls, 0)

    def test_committed_policy_checkpoint_records_exact_liveness_witness(self):
        authority, durable = self.durable()
        session, engine = self.session(durable)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self_store = SelfStateStore(root / "self.json")
            self_store.bootstrap(durable, authority)
            liveness_store = RuntimeLivenessStore(root / "liveness.json")

            def build_liveness_service(
                *,
                session,
                store,
                liveness_store,
            ):
                return LivenessCoupledPolicyCheckpointAdapter(
                    session=session,
                    store=store,
                    liveness_store=liveness_store,
                    policy=self.policy(),
                )

            service = production_policy_checkpoint_service_factory(
                SimpleNamespace(
                    state=SimpleNamespace(consciousness_session=session)
                ),
                enabled_fn=lambda: True,
                store_factory=lambda: self_store,
                liveness_enabled_fn=lambda: True,
                liveness_store_factory=lambda: liveness_store,
                liveness_adapter_factory=build_liveness_service,
            )
            self.assertIsInstance(
                service,
                LivenessCoupledPolicyCheckpointAdapter,
            )

            result = service.maybe_checkpoint_once()
            witness = liveness_store.read()
            receipt = service.last_liveness_receipt

            self.assertEqual(result.outcome, "COMMITTED")
            self.assertIsNotNone(result.checkpoint)
            self.assertIsNotNone(witness)
            self.assertIsNotNone(receipt)
            self.assertEqual(
                witness.source_ref,
                result.checkpoint.store_receipt_ref,
            )
            self.assertEqual(
                witness.durable_self_state_revision,
                result.checkpoint.revision_after,
            )
            self.assertEqual(
                witness.durable_self_state_revision,
                session.live_state.state.revision,
            )
            self.assertEqual(self_store.read(), session.live_state.state)
            self.assertIsNone(session.self_state_checkpoint_plan)
            self.assertEqual(engine.calls, 0)

    def test_liveness_failure_never_replays_committed_checkpoint(self):
        authority, durable = self.durable()
        session, engine = self.session(durable)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self_store = SelfStateStore(root / "self.json")
            self_store.bootstrap(durable, authority)
            liveness_store = FailingLivenessStore(
                root / "liveness.json"
            )
            service = LivenessCoupledPolicyCheckpointAdapter(
                session=session,
                store=self_store,
                liveness_store=liveness_store,
                policy=self.policy(),
            )

            with self.assertRaises(PolicyCheckpointLivenessError) as caught:
                service.maybe_checkpoint_once()

            error = caught.exception
            self.assertTrue(error.checkpoint_committed)
            self.assertFalse(error.checkpoint_retry_authority)
            self.assertEqual(
                error.checkpoint_result.outcome,
                "COMMITTED",
            )
            self.assertEqual(liveness_store.write_calls, 1)
            self.assertEqual(self_store.read(), session.live_state.state)
            self.assertIsNone(session.self_state_checkpoint_plan)
            self.assertEqual(engine.calls, 0)

            retry = service.maybe_checkpoint_once()
            self.assertEqual(retry.outcome, "IDLE")
            self.assertEqual(liveness_store.write_calls, 1)
            self.assertEqual(engine.calls, 0)


if __name__ == "__main__":
    unittest.main()
