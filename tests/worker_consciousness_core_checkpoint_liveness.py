#!/usr/bin/env python3
"""C29-B committed-checkpoint liveness recorder tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_checkpoint_liveness.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

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
from app.consciousness_core.checkpoint_liveness import (  # noqa: E402
    CheckpointLivenessError,
    CommittedCheckpointLivenessRecorder,
)
from app.consciousness_core.liveness import (  # noqa: E402
    RuntimeLivenessStore,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.self_state_checkpoint_runtime import (  # noqa: E402
    ExplicitSelfStateCheckpointCoordinator,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)
from app.consciousness_core.world_reducer import (  # noqa: E402
    WorldEvidenceEvent,
)


class Engine:
    def __init__(self):
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        raise AssertionError("C29-B liveness recording must not call model")


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


class FailingLivenessStore(RuntimeLivenessStore):
    def __init__(self, path):
        super().__init__(path)
        self.calls = 0

    def write_next(self, witness):
        self.calls += 1
        raise RuntimeError("simulated liveness write failure")


class CheckpointLivenessTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            authority="operator_review",
            authority_ref="operator:test:c29b",
            source_refs=["registry:test:c29b"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c29b",
            world_state_ref="world-state:durable",
            workspace_ref="workspace:durable",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c29b"],
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
            body_source_ref="body:c29b",
            voice_source_ref="voice:c29b",
            registry_source_ref="registry:c29b",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=durable,
            active_person=person,
            bootstrap_source_ref="runtime:c29b",
        )
        engine = Engine()
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(engine),
            clock=deterministic_clock(),
        )
        session = ProductionCognitiveSession(
            supervisor_bridge=bridge,
            bootstrap_context=context,
            durable_anchor_state=durable,
        )
        return session, engine

    def checkpoint(self, root):
        authority, durable = self.durable()
        session, engine = self.session(durable)
        self_store = SelfStateStore(root / "self.json")
        self_store.bootstrap(durable, authority)
        coordinator = ExplicitSelfStateCheckpointCoordinator(
            session=session,
            store=self_store,
        )
        committed = coordinator.checkpoint_once()
        self.assertEqual(committed.outcome, "COMMITTED")
        self.assertIsNone(session.self_state_checkpoint_plan)
        return (
            authority,
            durable,
            session,
            engine,
            self_store,
            coordinator,
            committed,
        )

    def test_committed_checkpoint_records_exact_live_state_witness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (
                _authority,
                _durable,
                session,
                engine,
                self_store,
                _coordinator,
                committed,
            ) = self.checkpoint(root)
            liveness = RuntimeLivenessStore(root / "liveness.json")
            recorder = CommittedCheckpointLivenessRecorder(
                session=session,
                store=liveness,
            )

            receipt = recorder.record_once(committed)
            witness = liveness.read()

            self.assertEqual(receipt.outcome, "RECORDED")
            self.assertTrue(receipt.liveness_store_write_applied)
            self.assertTrue(receipt.trusted_clock_sampled)
            self.assertFalse(receipt.checkpoint_retry_authority)
            self.assertIsNotNone(witness)
            self.assertEqual(
                witness.durable_self_state_revision,
                committed.revision_after,
            )
            self.assertEqual(
                witness.durable_self_state_revision,
                session.live_state.state.revision,
            )
            self.assertEqual(
                witness.source_ref,
                committed.store_receipt_ref,
            )
            self.assertEqual(
                witness.anchor.runtime_epoch_id,
                session.trusted_clock.runtime_epoch_id,
            )
            self.assertEqual(
                self_store.read(),
                session.live_state.state,
            )
            self.assertEqual(engine.calls, 0)

    def test_duplicate_checkpoint_receipt_is_idempotent_without_clock_sample(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (
                _authority,
                _durable,
                session,
                engine,
                _self_store,
                _coordinator,
                committed,
            ) = self.checkpoint(root)
            liveness = RuntimeLivenessStore(root / "liveness.json")
            recorder = CommittedCheckpointLivenessRecorder(
                session=session,
                store=liveness,
            )

            first = recorder.record_once(committed)
            witness_before = liveness.read()
            sequence_before = session.trusted_clock._sequence
            second = recorder.record_once(committed)

            self.assertEqual(first.outcome, "RECORDED")
            self.assertEqual(second.outcome, "ALREADY_RECORDED")
            self.assertFalse(second.liveness_store_write_applied)
            self.assertFalse(second.trusted_clock_sampled)
            self.assertEqual(
                session.trusted_clock._sequence,
                sequence_before,
            )
            self.assertEqual(liveness.read(), witness_before)
            self.assertEqual(engine.calls, 0)

    def test_idle_checkpoint_is_rejected_before_clock_or_store_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (
                _authority,
                _durable,
                session,
                _engine,
                _self_store,
                coordinator,
                committed,
            ) = self.checkpoint(root)
            liveness = RuntimeLivenessStore(root / "liveness.json")
            recorder = CommittedCheckpointLivenessRecorder(
                session=session,
                store=liveness,
            )
            recorder.record_once(committed)
            idle = coordinator.checkpoint_once()
            self.assertEqual(idle.outcome, "IDLE")
            witness_before = liveness.read()
            sequence_before = session.trusted_clock._sequence

            with self.assertRaisesRegex(
                CheckpointLivenessError,
                "requires a committed",
            ):
                recorder.record_once(idle)

            self.assertEqual(
                session.trusted_clock._sequence,
                sequence_before,
            )
            self.assertEqual(liveness.read(), witness_before)

    def test_new_pending_state_after_commit_blocks_old_checkpoint_recording(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (
                _authority,
                _durable,
                session,
                engine,
                _self_store,
                _coordinator,
                committed,
            ) = self.checkpoint(root)
            liveness = RuntimeLivenessStore(root / "liveness.json")
            recorder = CommittedCheckpointLivenessRecorder(
                session=session,
                store=liveness,
            )
            event = WorldEvidenceEvent(
                schema="kaliv-consciousness-core/world-evidence-event/v1",
                event_id="wevt-" + "7" * 32,
                subject_ref="system:c29b",
                proposition="State changed after the committed checkpoint.",
                confidence=1.0,
                epistemic_status="observed",
                source_refs=["runtime:test:c29b"],
                observed_sequence=10,
                production_activation=False,
            )
            session.submit_world_evidence(
                event,
                attention_salience=1.0,
            )
            self.assertIsNotNone(session.self_state_checkpoint_plan)
            sequence_before = session.trusted_clock._sequence

            with self.assertRaisesRegex(
                CheckpointLivenessError,
                "pending SelfState transitions",
            ):
                recorder.record_once(committed)

            self.assertEqual(
                session.trusted_clock._sequence,
                sequence_before,
            )
            self.assertIsNone(liveness.read())
            self.assertEqual(engine.calls, 0)

    def test_liveness_write_failure_never_retries_committed_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (
                _authority,
                _durable,
                session,
                engine,
                self_store,
                coordinator,
                committed,
            ) = self.checkpoint(root)
            durable_after = self_store.read()
            liveness = FailingLivenessStore(root / "liveness.json")
            recorder = CommittedCheckpointLivenessRecorder(
                session=session,
                store=liveness,
            )

            with self.assertRaisesRegex(
                CheckpointLivenessError,
                "write failed after committed checkpoint",
            ):
                recorder.record_once(committed)

            self.assertEqual(liveness.calls, 1)
            self.assertEqual(self_store.read(), durable_after)
            self.assertIsNone(session.self_state_checkpoint_plan)
            self.assertEqual(
                coordinator.checkpoint_once().outcome,
                "IDLE",
            )
            self.assertEqual(engine.calls, 0)

    def test_closed_session_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (
                _authority,
                _durable,
                session,
                _engine,
                _self_store,
                _coordinator,
                committed,
            ) = self.checkpoint(root)
            recorder = CommittedCheckpointLivenessRecorder(
                session=session,
                store=RuntimeLivenessStore(root / "liveness.json"),
            )
            session.close()

            with self.assertRaisesRegex(
                CheckpointLivenessError,
                "closed cognitive session",
            ):
                recorder.record_once(committed)


if __name__ == "__main__":
    unittest.main()
