#!/usr/bin/env python3
"""C27-B runtime SelfState transition ledger tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_self_state_ledger.py
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
    PersistentSelfState,
    ProductionCognitiveSession,
    SelfAffect,
    SelfBootstrapAuthority,
    SelfStateStore,
    advance_self_state,
    bootstrap_runtime_session,
    bootstrap_self_state,
)
from app.consciousness_core.cycle import self_state_ref  # noqa: E402
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.self_state_ledger import (  # noqa: E402
    RuntimeSelfStateLedger,
    RuntimeSelfStateLedgerError,
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
        payload["interpretation"] = "Bounded C27-B transition-ledger test."
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


class SelfStateLedgerTests(unittest.TestCase):
    def durable(self):
        auth = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            authority="operator_review",
            authority_ref="operator:test:c27b",
            source_refs=["registry:test:c27b"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            auth,
            personality_state_ref="personality-state:c27b",
            world_state_ref="world-state:durable",
            workspace_ref="workspace:durable",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c27b"],
            ),
            active_goal_refs=["goal:c27b"],
            active_intention_refs=["intent:c27b"],
        )
        return auth, state

    def person(self, state):
        return ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c27b",
            voice_source_ref="voice:c27b",
            registry_source_ref="registry:c27b",
            production_activation=False,
        )

    def context(self, state):
        return bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c27b",
        )

    def session(self):
        _auth, durable = self.durable()
        context = self.context(durable)
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
        return session, engine, durable

    def profile(self):
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "4" * 32,
            engine_instance_id="engine:test:c27b",
            provider="mock",
            model="c27b-model",
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

    def world_evidence(self, sequence=10):
        return WorldEvidenceEvent(
            schema="kaliv-consciousness-core/world-evidence-event/v1",
            event_id="wevt-" + "5" * 32,
            subject_ref="system:c27b",
            proposition="A verified runtime fact changed.",
            confidence=1.0,
            epistemic_status="observed",
            source_refs=["runtime:test:c27b"],
            observed_sequence=sequence,
            production_activation=False,
        )

    def test_bootstrap_seeds_exact_first_pending_transition(self):
        session, engine, durable = self.session()
        plan = session.self_state_checkpoint_plan

        self.assertIsNotNone(plan)
        self.assertEqual(engine.calls, 0)
        self.assertEqual(plan.revision_before, durable.revision)
        self.assertEqual(plan.revision_after, durable.revision + 1)
        self.assertEqual(plan.transition_count, 1)
        self.assertEqual(
            [item.kind for item in plan.transitions],
            ["session_bootstrap"],
        )
        self.assertEqual(
            plan.anchor_state_ref,
            self_state_ref(durable),
        )
        self.assertEqual(
            plan.final_state_ref,
            self_state_ref(session.live_state.state),
        )
        self.assertFalse(plan.self_state_store_write_applied)

    def test_world_then_run_captures_complete_ordered_revision_chain(self):
        session, engine, durable = self.session()

        admission = session.submit_world_evidence(
            self.world_evidence(),
            attention_salience=1.0,
        )
        self.assertTrue(admission.cognition_event_queued)
        after_world = session.self_state_checkpoint_plan
        self.assertEqual(
            [item.kind for item in after_world.transitions],
            ["session_bootstrap", "world_evidence"],
        )
        self.assertEqual(
            [item.revision for item in after_world.transitions],
            [durable.revision + 1, durable.revision + 2],
        )

        result = run(session.step(profile=self.profile()))
        self.assertEqual(result.supervisor_step.plan.decision, "RUN")
        self.assertEqual(engine.calls, 1)

        plan = session.self_state_checkpoint_plan
        self.assertEqual(
            [item.kind for item in plan.transitions],
            [
                "session_bootstrap",
                "world_evidence",
                "supervisor_orientation",
                "post_cycle_reduction",
            ],
        )
        self.assertEqual(
            [item.revision for item in plan.transitions],
            [
                durable.revision + 1,
                durable.revision + 2,
                durable.revision + 3,
                durable.revision + 4,
            ],
        )
        self.assertEqual(plan.revision_after, durable.revision + 4)
        self.assertEqual(
            plan.final_state_ref,
            self_state_ref(session.live_state.state),
        )
        checkpoint_states = session.pending_self_state_checkpoint_states()
        self.assertEqual(
            [state.revision for state in checkpoint_states],
            [
                durable.revision + 1,
                durable.revision + 2,
                durable.revision + 3,
                durable.revision + 4,
            ],
        )

    def test_idle_step_adds_no_transition(self):
        session, engine, _durable = self.session()
        before = session.self_state_checkpoint_plan

        result = run(session.step(profile=self.profile()))

        self.assertEqual(result.supervisor_step.plan.decision, "IDLE")
        self.assertEqual(engine.calls, 0)
        self.assertEqual(session.self_state_checkpoint_plan, before)

    def test_event_only_admission_does_not_advance_self_ledger(self):
        session, engine, _durable = self.session()
        before = session.self_state_checkpoint_plan
        session.submit(
            CognitionEvent(
                schema="kaliv-consciousness-core/cognition-event/v1",
                event_id="cevt-" + "6" * 32,
                kind="wake_followup",
                source_ref="wake:test:c27b",
                summary="Wake attention only.",
                salience=0.96,
                observed_sequence=2,
                production_activation=False,
            )
        )
        self.assertEqual(session.self_state_checkpoint_plan, before)
        self.assertEqual(engine.calls, 0)

    def test_world_replay_adds_no_second_transition(self):
        session, engine, _durable = self.session()
        evidence = self.world_evidence()
        first = session.submit_world_evidence(
            evidence,
            attention_salience=1.0,
        )
        after_first = session.self_state_checkpoint_plan

        # Generic world reducer recognizes exact evidence replay in the already
        # updated live world and does not queue or advance SelfState again.
        second = session.submit_world_evidence(
            evidence,
            attention_salience=1.0,
        )

        self.assertTrue(first.cognition_event_queued)
        self.assertFalse(second.cognition_event_queued)
        self.assertEqual(session.self_state_checkpoint_plan, after_first)
        self.assertEqual(engine.calls, 0)

    def test_ledger_checkpoint_receipt_resets_anchor_without_history_claim(self):
        auth, durable = self.durable()
        context = self.context(durable)
        ledger = RuntimeSelfStateLedger(
            anchor_state=durable,
            initial_state=context.state,
            initial_source_ref="session-bootstrap:test:c27b",
        )
        next_state = advance_self_state(
            context.state,
            workspace_ref="workspace:c27b:next",
        )
        ledger.append(
            state=next_state,
            kind="supervisor_orientation",
            source_ref="supervisor:test:c27b",
        )

        with tempfile.TemporaryDirectory() as td:
            store = SelfStateStore(Path(td) / "self.json")
            store.bootstrap(durable, auth)
            receipt = store.write_chain(ledger.checkpoint_states())
            ledger.mark_checkpointed(receipt)

            self.assertEqual(ledger.pending_count, 0)
            self.assertEqual(ledger.anchor_state, next_state)
            with self.assertRaises(RuntimeSelfStateLedgerError):
                ledger.plan()

            after = advance_self_state(
                next_state,
                workspace_ref="workspace:c27b:after-checkpoint",
            )
            ledger.append(
                state=after,
                kind="post_cycle_reduction",
                source_ref="reducer:test:c27b",
            )
            plan = ledger.plan()
            self.assertEqual(plan.revision_before, next_state.revision)
            self.assertEqual(plan.revision_after, after.revision)
            self.assertEqual(plan.transition_count, 1)

    def test_session_acknowledges_exact_checkpoint_and_reanchors(self):
        auth, durable = self.durable()
        context = self.context(durable)
        engine = Engine()
        session = ProductionCognitiveSession(
            supervisor_bridge=ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(engine),
                clock=deterministic_clock(),
            ),
            bootstrap_context=context,
            durable_anchor_state=durable,
        )

        with tempfile.TemporaryDirectory() as td:
            store = SelfStateStore(Path(td) / "self.json")
            store.bootstrap(durable, auth)
            receipt = store.write_chain(
                session.pending_self_state_checkpoint_states()
            )
            session.mark_self_state_checkpointed(receipt)

            self.assertIsNone(session.self_state_checkpoint_plan)
            self.assertEqual(
                session.pending_self_state_checkpoint_states(),
                [],
            )

            session.submit_world_evidence(
                self.world_evidence(sequence=20),
                attention_salience=1.0,
            )
            plan = session.self_state_checkpoint_plan
            self.assertIsNotNone(plan)
            self.assertEqual(
                plan.revision_before,
                context.state.revision,
            )
            self.assertEqual(plan.transition_count, 1)
            self.assertEqual(
                [item.kind for item in plan.transitions],
                ["world_evidence"],
            )
            self.assertEqual(engine.calls, 0)

    def test_capacity_fails_before_overflow(self):
        _auth, durable = self.durable()
        context = self.context(durable)
        ledger = RuntimeSelfStateLedger(
            anchor_state=durable,
            initial_state=context.state,
            initial_source_ref="session-bootstrap:test:c27b",
        )
        current = context.state
        for index in range(127):
            current = advance_self_state(
                current,
                workspace_ref=f"workspace:c27b:{index}",
            )
            ledger.append(
                state=current,
                kind="world_evidence",
                source_ref=f"transition:c27b:{index}",
            )
        self.assertEqual(ledger.pending_count, 128)
        self.assertEqual(ledger.remaining_capacity, 0)

        with self.assertRaises(RuntimeSelfStateLedgerError):
            ledger.require_capacity(1)
        next_state = advance_self_state(
            current,
            workspace_ref="workspace:c27b:overflow",
        )
        with self.assertRaises(RuntimeSelfStateLedgerError):
            ledger.prepare(
                state=next_state,
                kind="world_evidence",
                source_ref="transition:c27b:overflow",
            )
        self.assertEqual(ledger.pending_count, 128)


if __name__ == "__main__":
    unittest.main()
