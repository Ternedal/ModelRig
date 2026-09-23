#!/usr/bin/env python3
"""C27-C explicit durable SelfState checkpoint coordinator tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_checkpoint_runtime.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ActivePersonBindingSnapshot,
    CognitiveProfile,
    ConsciousnessCoreRuntime,
    ProductionCognitiveSession,
    SelfAffect,
    SelfBootstrapAuthority,
    SelfStateStore,
    advance_self_state,
    bootstrap_runtime_session,
    bootstrap_self_state,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.self_state_checkpoint_runtime import (  # noqa: E402
    ExplicitSelfStateCheckpointCoordinator,
    RuntimeSelfStateCheckpointError,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)
from app.consciousness_core.world_reducer import (  # noqa: E402
    WorldEvidenceEvent,
)


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
        payload["proposal_id"] = "thinkprop-" + f"{self.calls:x}"[-1] * 32
        payload["interpretation"] = "Checkpointed cognition."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


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


class CountingStore(SelfStateStore):
    def __init__(self, path):
        super().__init__(path)
        self.chain_calls = 0

    def write_chain(self, states):
        self.chain_calls += 1
        return super().write_chain(states)


class FailingStore(CountingStore):
    def write_chain(self, states):
        self.chain_calls += 1
        raise RuntimeError("simulated checkpoint failure")


class CheckpointRuntimeTests(unittest.TestCase):
    def durable(self):
        auth = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            authority="operator_review",
            authority_ref="operator:test:c27c",
            source_refs=["registry:test:c27c"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            auth,
            personality_state_ref="personality-state:c27c",
            world_state_ref="world-state:durable",
            workspace_ref="workspace:durable",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c27c"],
            ),
        )
        return auth, state

    def session(self, durable):
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=durable.person_id,
            person_revision=durable.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c27c",
            voice_source_ref="voice:c27c",
            registry_source_ref="registry:c27c",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=durable,
            active_person=person,
            bootstrap_source_ref="runtime:c27c",
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

    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "7" * 32,
            engine_instance_id="engine:test:c27c",
            provider="mock",
            model="c27c-model",
            reasoning_depth=0.8,
            planning_capacity=0.8,
            context_capacity_tokens=8192,
            multimodal_capacity=0.0,
            tool_reasoning=0.0,
            uncertainty_calibration=0.9,
            ephemeral=True,
            identity_authority=False,
            persistent_state_authority=False,
            action_authority=False,
            production_activation=False,
        )

    def evidence(self):
        return WorldEvidenceEvent(
            schema="kaliv-consciousness-core/world-evidence-event/v1",
            event_id="wevt-" + "8" * 32,
            subject_ref="system:c27c",
            proposition="Verified state changed.",
            confidence=1.0,
            epistemic_status="observed",
            source_refs=["runtime:test:c27c"],
            observed_sequence=10,
            production_activation=False,
        )

    def test_bootstrap_chain_commits_and_reanchors_once(self):
        auth, durable = self.durable()
        session, engine = self.session(durable)
        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, auth)
            coordinator = ExplicitSelfStateCheckpointCoordinator(
                session=session,
                store=store,
            )

            result = coordinator.checkpoint_once()

            self.assertEqual(result.outcome, "COMMITTED")
            self.assertEqual(result.transition_count, 1)
            self.assertEqual(result.revision_before, durable.revision)
            self.assertEqual(
                result.revision_after,
                session.live_state.state.revision,
            )
            self.assertTrue(result.self_state_store_write_applied)
            self.assertTrue(result.ledger_reanchored)
            self.assertFalse(result.intermediate_history_persisted)
            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(store.read(), session.live_state.state)
            self.assertIsNone(session.self_state_checkpoint_plan)
            self.assertEqual(engine.calls, 0)

            idle = coordinator.checkpoint_once()
            self.assertEqual(idle.outcome, "IDLE")
            self.assertFalse(idle.self_state_store_write_applied)
            self.assertEqual(store.chain_calls, 1)

    def test_world_and_run_chain_commits_as_one_atomic_final_replace(self):
        auth, durable = self.durable()
        session, engine = self.session(durable)
        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, auth)
            coordinator = ExplicitSelfStateCheckpointCoordinator(
                session=session,
                store=store,
            )
            coordinator.checkpoint_once()
            store.chain_calls = 0

            session.submit_world_evidence(
                self.evidence(),
                attention_salience=1.0,
            )
            result = run(session.step(profile=self.profile()))
            self.assertEqual(result.supervisor_step.plan.decision, "RUN")
            plan = session.self_state_checkpoint_plan
            self.assertEqual(plan.transition_count, 3)

            checkpoint = coordinator.checkpoint_once()

            self.assertEqual(checkpoint.outcome, "COMMITTED")
            self.assertEqual(checkpoint.transition_count, 3)
            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(store.read(), session.live_state.state)
            self.assertIsNone(session.self_state_checkpoint_plan)
            self.assertEqual(engine.calls, 1)

    def test_stale_store_anchor_fails_before_write_and_keeps_ledger(self):
        auth, durable = self.durable()
        session, engine = self.session(durable)
        pending_before = session.self_state_checkpoint_plan
        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, auth)
            # Advance durable state behind the coordinator's back. The ledger
            # still says its anchor is revision 1.
            bootstrap_state = session.pending_self_state_checkpoint_states()[0]
            store.write_next(bootstrap_state)
            store.chain_calls = 0

            coordinator = ExplicitSelfStateCheckpointCoordinator(
                session=session,
                store=store,
            )
            with self.assertRaisesRegex(
                RuntimeSelfStateCheckpointError,
                "no longer matches ledger anchor",
            ):
                coordinator.checkpoint_once()

            self.assertEqual(store.chain_calls, 0)
            self.assertEqual(session.self_state_checkpoint_plan, pending_before)
            self.assertEqual(engine.calls, 0)

    def test_store_failure_leaves_ledger_pending(self):
        auth, durable = self.durable()
        session, engine = self.session(durable)
        pending_before = session.self_state_checkpoint_plan
        with tempfile.TemporaryDirectory() as td:
            store = FailingStore(Path(td) / "self.json")
            store.bootstrap(durable, auth)
            coordinator = ExplicitSelfStateCheckpointCoordinator(
                session=session,
                store=store,
            )

            with self.assertRaisesRegex(
                RuntimeSelfStateCheckpointError,
                "durable SelfState checkpoint failed",
            ):
                coordinator.checkpoint_once()

            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(store.read(), durable)
            self.assertEqual(session.self_state_checkpoint_plan, pending_before)
            self.assertEqual(engine.calls, 0)

    def test_post_write_ack_failure_is_explicit_and_never_retries(self):
        auth, durable = self.durable()
        session, engine = self.session(durable)
        committed_state = session.live_state.state

        def broken_ack(_receipt):
            raise RuntimeError("simulated ack failure")

        session.mark_self_state_checkpointed = broken_ack  # type: ignore[method-assign]

        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, auth)
            coordinator = ExplicitSelfStateCheckpointCoordinator(
                session=session,
                store=store,
            )

            with self.assertRaisesRegex(
                RuntimeSelfStateCheckpointError,
                "committed but session acknowledgement failed",
            ):
                coordinator.checkpoint_once()

            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(store.read(), committed_state)
            self.assertEqual(engine.calls, 0)

    def test_closed_session_cannot_checkpoint(self):
        auth, durable = self.durable()
        session, _engine = self.session(durable)
        session.close()
        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, auth)
            coordinator = ExplicitSelfStateCheckpointCoordinator(
                session=session,
                store=store,
            )
            with self.assertRaisesRegex(
                RuntimeSelfStateCheckpointError,
                "closed cognitive session",
            ):
                coordinator.checkpoint_once()
            self.assertEqual(store.chain_calls, 0)


if __name__ == "__main__":
    unittest.main()
