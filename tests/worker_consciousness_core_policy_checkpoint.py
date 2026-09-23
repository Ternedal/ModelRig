#!/usr/bin/env python3
"""C27-F explicit policy-driven checkpoint adapter tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_policy_checkpoint.py
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
    bootstrap_runtime_session,
    bootstrap_self_state,
)
from app.consciousness_core.checkpoint_pressure import (  # noqa: E402
    CheckpointPressurePolicy,
)
from app.consciousness_core.policy_checkpoint import (  # noqa: E402
    PolicyDrivenCheckpointError,
    PolicyDrivenSelfStateCheckpointAdapter,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.self_state_checkpoint_runtime import (  # noqa: E402
    ExplicitSelfStateCheckpointCoordinator,
    RuntimeSelfStateCheckpointResult,
)
from app.consciousness_core.supervisor import CognitionEvent  # noqa: E402
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
        payload["interpretation"] = "Policy checkpoint cognition."
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


def deterministic_clock():
    wall = iter(
        1_700_000_000_000_000_000 + i * 1_000_000_000
        for i in range(1, 96)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 96))
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
        raise RuntimeError("simulated write failure")


class WrongPlanCoordinator(ExplicitSelfStateCheckpointCoordinator):
    def __init__(self, **_kwargs):
        self.calls = 0

    def checkpoint_once(self):
        self.calls += 1
        return RuntimeSelfStateCheckpointResult(
            schema=(
                "kaliv-consciousness-core/"
                "runtime-self-state-checkpoint-result/v1"
            ),
            outcome="COMMITTED",
            plan_ref="runtime-self-state-checkpoint-plan:" + "0" * 64,
            store_receipt_ref="self-state-checkpoint-receipt:" + "1" * 64,
            transition_count=1,
            revision_before=1,
            revision_after=2,
            self_state_store_write_applied=True,
            ledger_reanchored=True,
            intermediate_history_persisted=False,
            model_calls=0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )


class PolicyCheckpointTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            authority="operator_review",
            authority_ref="operator:test:c27f",
            source_refs=["registry:test:c27f"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c27f",
            world_state_ref="world-state:durable",
            workspace_ref="workspace:durable",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c27f"],
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
            body_source_ref="body:c27f",
            voice_source_ref="voice:c27f",
            registry_source_ref="registry:c27f",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=durable,
            active_person=person,
            bootstrap_source_ref="runtime:c27f",
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
            profile_id="cog-" + "8" * 32,
            engine_instance_id="engine:test:c27f",
            provider="mock",
            model="c27f-model",
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

    def policy(self, *, threshold=8, post_cycle=True):
        return CheckpointPressurePolicy(
            schema="kaliv-consciousness-core/checkpoint-pressure-policy/v1",
            checkpoint_transition_count=threshold,
            reserve_transition_slots=2,
            checkpoint_after_post_cycle=post_cycle,
            production_activation=False,
        )

    def test_default_bootstrap_pressure_holds_without_store_write(self):
        authority, durable = self.durable()
        session, engine = self.session(durable)
        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, authority)
            store.chain_calls = 0
            adapter = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
            )

            result = adapter.maybe_checkpoint_once()

            self.assertEqual(result.outcome, "HOLD")
            self.assertEqual(result.pressure.decision, "HOLD")
            self.assertFalse(result.coordinator_invoked)
            self.assertFalse(result.self_state_store_write_applied)
            self.assertIsNone(result.checkpoint)
            self.assertIsNotNone(result.evaluated_plan_ref)
            self.assertEqual(store.chain_calls, 0)
            self.assertEqual(store.read(), durable)
            self.assertEqual(engine.calls, 0)

    def test_custom_threshold_commits_bootstrap_once_then_becomes_idle(self):
        authority, durable = self.durable()
        session, engine = self.session(durable)
        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, authority)
            store.chain_calls = 0
            adapter = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
                policy=self.policy(threshold=1),
            )

            committed = adapter.maybe_checkpoint_once()
            self.assertEqual(committed.outcome, "COMMITTED")
            self.assertEqual(
                committed.pressure.decision,
                "CHECKPOINT",
            )
            self.assertTrue(committed.coordinator_invoked)
            self.assertTrue(committed.self_state_store_write_applied)
            self.assertEqual(
                committed.checkpoint.plan_ref,
                committed.evaluated_plan_ref,
            )
            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(store.read(), session.live_state.state)
            self.assertIsNone(session.self_state_checkpoint_plan)

            idle = adapter.maybe_checkpoint_once()
            self.assertEqual(idle.outcome, "IDLE")
            self.assertEqual(idle.pressure.decision, "IDLE")
            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(engine.calls, 0)

    def test_completed_cognitive_cycle_commits_under_default_policy(self):
        authority, durable = self.durable()
        session, engine = self.session(durable)
        session.submit(
            CognitionEvent(
                schema="kaliv-consciousness-core/cognition-event/v1",
                event_id="cevt-" + "7" * 32,
                kind="wake_followup",
                source_ref="wake:test:c27f",
                summary="Wake attention.",
                salience=0.96,
                observed_sequence=3,
                production_activation=False,
            )
        )
        result = run(session.step(profile=self.profile()))
        self.assertEqual(result.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)

        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, authority)
            store.chain_calls = 0
            adapter = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
            )
            committed = adapter.maybe_checkpoint_once()

            self.assertEqual(committed.outcome, "COMMITTED")
            self.assertEqual(
                committed.pressure.reason,
                "completed_cognitive_cycle",
            )
            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(store.read(), session.live_state.state)

    def test_world_only_threshold_commits_at_eight_transitions(self):
        authority, durable = self.durable()
        session, engine = self.session(durable)
        for index in range(7):
            event = WorldEvidenceEvent(
                schema="kaliv-consciousness-core/world-evidence-event/v1",
                event_id="wevt-" + f"{index + 1:x}" * 32,
                subject_ref=f"system:c27f:{index}",
                proposition=f"Verified world update {index}.",
                confidence=1.0,
                epistemic_status="observed",
                source_refs=[f"runtime:c27f:{index}"],
                observed_sequence=index + 10,
                production_activation=False,
            )
            session.submit_world_evidence(
                event,
                attention_salience=1.0,
            )
        self.assertEqual(
            session.self_state_checkpoint_plan.transition_count,
            8,
        )

        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, authority)
            store.chain_calls = 0
            adapter = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
            )
            committed = adapter.maybe_checkpoint_once()

            self.assertEqual(committed.outcome, "COMMITTED")
            self.assertEqual(
                committed.pressure.reason,
                "transition_threshold",
            )
            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(engine.calls, 0)

    def test_store_failure_surfaces_without_replaying_operation(self):
        authority, durable = self.durable()
        session, engine = self.session(durable)
        plan_before = session.self_state_checkpoint_plan
        with tempfile.TemporaryDirectory() as td:
            store = FailingStore(Path(td) / "self.json")
            store.bootstrap(durable, authority)
            store.chain_calls = 0
            adapter = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
                policy=self.policy(threshold=1),
            )

            with self.assertRaisesRegex(
                PolicyDrivenCheckpointError,
                "policy-driven SelfState checkpoint failed",
            ):
                adapter.maybe_checkpoint_once()

            self.assertEqual(store.chain_calls, 1)
            self.assertEqual(store.read(), durable)
            self.assertEqual(
                session.self_state_checkpoint_plan,
                plan_before,
            )
            self.assertEqual(engine.calls, 0)

    def test_wrong_committed_plan_ref_fails_closed(self):
        authority, durable = self.durable()
        session, _engine = self.session(durable)
        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, authority)
            adapter = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
                policy=self.policy(threshold=1),
                coordinator_factory=lambda **kwargs: WrongPlanCoordinator(
                    **kwargs
                ),
            )

            with self.assertRaisesRegex(
                PolicyDrivenCheckpointError,
                "plan differs from evaluated pressure plan",
            ):
                adapter.maybe_checkpoint_once()

    def test_closed_session_fails_before_pressure_evaluation(self):
        authority, durable = self.durable()
        session, _engine = self.session(durable)
        session.close()
        with tempfile.TemporaryDirectory() as td:
            store = CountingStore(Path(td) / "self.json")
            store.bootstrap(durable, authority)
            adapter = PolicyDrivenSelfStateCheckpointAdapter(
                session=session,
                store=store,
            )
            with self.assertRaisesRegex(
                PolicyDrivenCheckpointError,
                "closed session",
            ):
                adapter.maybe_checkpoint_once()
            self.assertEqual(store.chain_calls, 0)


if __name__ == "__main__":
    unittest.main()
