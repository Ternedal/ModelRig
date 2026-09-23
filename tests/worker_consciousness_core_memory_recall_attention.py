#!/usr/bin/env python3
"""C26-C privacy-safe Memory 4 recall attention tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_memory_recall_attention.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

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
    evaluate_autonomous_trigger,
    new_automatic_cognition_accounting,
)
from app.consciousness_core.autonomous_trigger_policy import (  # noqa: E402
    DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
)
from app.consciousness_core.experience import MemoryContextSnapshot  # noqa: E402
from app.consciousness_core.memory_recall_attention import (  # noqa: E402
    MEMORY_RECALL_SALIENCE,
    MemoryRecallAttentionError,
    memory_context_snapshot_ref,
    memory_recall_snapshot_has_items,
    plan_memory_recall,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
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
        return payload


class CountingClock(TrustedRuntimeClock):
    def __init__(self):
        self.calls = 0
        self._wall_values = iter(
            1_700_000_000_000_000_000 + i * 1_000_000_000
            for i in range(1, 32)
        )
        self._mono_values = iter(i * 1_000_000_000 for i in range(1, 32))
        super().__init__(
            wall_time_ns=lambda: next(self._wall_values),
            monotonic_ns=lambda: next(self._mono_values),
        )

    def sample(self):
        self.calls += 1
        return super().sample()


class MemoryRecallAttentionTests(unittest.TestCase):
    def snapshot(self, *, empty=False):
        context = "" if empty else "PRIVATE-CONTEXT-SENTINEL"
        included = [] if empty else ["memory-private-sentinel-id"]
        encoded = context.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        return MemoryContextSnapshot(
            schema="kaliv-consciousness-core/memory-context-snapshot/v1",
            target="local",
            context=context,
            included_ids=included,
            context_sha256=digest,
            character_count=len(context),
            byte_count=len(encoded),
            authority="reference_data",
            sent_to_model=False,
            source_ref=f"memory4-context:{digest}",
            production_activation=False,
        )

    def session(self):
        state = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=140,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            personality_state_ref="personality-state:c26c",
            world_state_ref="world-state:old",
            workspace_ref="workspace:old",
            active_goal_refs=[],
            active_intention_refs=[],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["test:c26c"],
            ),
            known_uncertainties=[],
            last_experience_ref=None,
            production_activation=False,
        )
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c26c",
            voice_source_ref="voice:c26c",
            registry_source_ref="registry:c26c",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=person,
            bootstrap_source_ref="runtime:c26c",
        )
        engine = Engine()
        clock = CountingClock()
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(engine),
            clock=clock,
        )
        return (
            ProductionCognitiveSession(
                supervisor_bridge=bridge,
                bootstrap_context=context,
            ),
            engine,
            clock,
        )

    def test_nonempty_snapshot_creates_privacy_safe_memory_recall(self):
        snapshot = self.snapshot()
        clock = CountingClock()
        sample = clock.sample()
        plan = plan_memory_recall(snapshot=snapshot, clock=sample)

        self.assertEqual(plan.included_count, 1)
        self.assertEqual(plan.context_sha256, snapshot.context_sha256)
        self.assertIsNotNone(plan.cognition_event)
        event = plan.cognition_event
        self.assertEqual(event.kind, "memory_recall")
        self.assertEqual(event.salience, MEMORY_RECALL_SALIENCE)
        self.assertEqual(event.observed_sequence, sample.sampled_sequence)
        serialized = plan.model_dump_json()
        self.assertNotIn(snapshot.context, serialized)
        self.assertNotIn(snapshot.included_ids[0], serialized)
        self.assertNotIn(snapshot.context, event.summary)
        self.assertNotIn(snapshot.included_ids[0], event.summary)

    def test_empty_snapshot_is_no_event_and_requires_no_clock(self):
        snapshot = self.snapshot(empty=True)
        self.assertFalse(memory_recall_snapshot_has_items(snapshot))
        plan = plan_memory_recall(snapshot=snapshot)
        self.assertEqual(plan.included_count, 0)
        self.assertIsNone(plan.clock_sample_ref)
        self.assertIsNone(plan.cognition_event)
        with self.assertRaises(MemoryRecallAttentionError):
            plan_memory_recall(
                snapshot=snapshot,
                clock=CountingClock().sample(),
            )

    def test_snapshot_integrity_is_revalidated(self):
        snapshot = self.snapshot()
        tampered = snapshot.model_copy(
            update={"context": snapshot.context + "-tampered"}
        )
        with self.assertRaises(MemoryRecallAttentionError):
            memory_context_snapshot_ref(tampered)

        bad_source = snapshot.model_copy(
            update={"source_ref": "memory4-context:" + "0" * 64}
        )
        with self.assertRaises(MemoryRecallAttentionError):
            memory_context_snapshot_ref(bad_source)

        inconsistent = snapshot.model_copy(
            update={
                "context": "",
                "context_sha256": hashlib.sha256(b"").hexdigest(),
                "character_count": 0,
                "byte_count": 0,
            }
        )
        with self.assertRaises(MemoryRecallAttentionError):
            memory_recall_snapshot_has_items(inconsistent)

    def test_session_admits_recall_without_live_state_or_model_mutation(self):
        session, engine, clock = self.session()
        snapshot = self.snapshot()
        live_before = session.live_state
        supervisor_before = session.supervisor_state
        clock_before = clock.calls

        receipt = session.submit_memory_recall(snapshot)

        self.assertTrue(receipt.cognition_event_admitted)
        self.assertEqual(engine.calls, 0)
        self.assertEqual(session.live_state, live_before)
        self.assertEqual(clock.calls, clock_before + 1)
        self.assertEqual(
            receipt.supervisor_revision_before,
            supervisor_before.revision,
        )
        self.assertEqual(
            receipt.supervisor_revision_after,
            supervisor_before.revision + 1,
        )
        self.assertEqual(len(session.supervisor_state.pending_events), 1)
        self.assertEqual(
            session.supervisor_state.pending_events[0],
            receipt.plan.cognition_event,
        )

    def test_exact_duplicate_recall_reuses_event_and_clock_binding(self):
        session, engine, clock = self.session()
        snapshot = self.snapshot()

        first = session.submit_memory_recall(snapshot)
        calls_after_first = clock.calls
        revision_after_first = session.supervisor_state.revision
        second = session.submit_memory_recall(snapshot)

        self.assertEqual(second.plan, first.plan)
        self.assertEqual(clock.calls, calls_after_first)
        self.assertEqual(
            second.supervisor_revision_before,
            revision_after_first,
        )
        self.assertEqual(
            second.supervisor_revision_after,
            revision_after_first,
        )
        self.assertEqual(len(session.supervisor_state.pending_events), 1)
        self.assertEqual(engine.calls, 0)

    def test_empty_session_recall_is_total_noop(self):
        session, engine, clock = self.session()
        before = session.supervisor_state
        clock_before = clock.calls

        receipt = session.submit_memory_recall(self.snapshot(empty=True))

        self.assertFalse(receipt.cognition_event_admitted)
        self.assertEqual(receipt.supervisor_revision_before, before.revision)
        self.assertEqual(receipt.supervisor_revision_after, before.revision)
        self.assertEqual(session.supervisor_state, before)
        self.assertEqual(clock.calls, clock_before)
        self.assertEqual(engine.calls, 0)

    def test_memory_recall_is_eligible_under_default_c25a_policy(self):
        snapshot = self.snapshot()
        clock = CountingClock()
        sample = clock.sample()
        plan = plan_memory_recall(snapshot=snapshot, clock=sample)
        event = plan.cognition_event
        self.assertIsNotNone(event)

        accounting = new_automatic_cognition_accounting(sample)
        decision = evaluate_autonomous_trigger(
            event=event,
            clock=sample,
            accounting=accounting,
            policy=DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
        )
        self.assertEqual(decision.decision, "ELIGIBLE")
        self.assertEqual(decision.reason, "eligible")
        self.assertEqual(decision.model_calls, 0)


if __name__ == "__main__":
    unittest.main()
