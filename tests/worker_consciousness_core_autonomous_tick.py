#!/usr/bin/env python3
"""C25-B one-tick autonomous cognition adapter tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_autonomous_tick.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
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
    PersistentSelfState,
    ProductionCognitiveSession,
    SelfAffect,
    bootstrap_runtime_session,
)
from app.consciousness_core.autonomous_tick import (  # noqa: E402
    AUTONOMOUS_COGNITION_FLAG,
    AutonomousCognitionAdapterError,
    AutonomousCognitionTickAdapter,
    autonomous_cognition_enabled,
)
from app.consciousness_core.autonomous_trigger_policy import (  # noqa: E402
    DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
    AutomaticCognitionAccounting,
    AutonomousTriggerPolicy,
)
from app.consciousness_core.profile_source import load_cognitive_profile  # noqa: E402
from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402
from app.consciousness_core.supervisor import CognitionEvent, SupervisorPolicy  # noqa: E402
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
    SupervisorLifecycleError,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


class Engine:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("PRIVATE-AUTONOMOUS-PROVIDER-FAILURE")
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + f"{self.calls:x}"[-1] * 32
        payload["interpretation"] = "AUTONOMOUS-BOUNDED-INTERPRETATION"
        payload["response_intent"] = None
        payload["attention_suggestions"] = []
        payload["hypotheses"] = []
        payload["candidate_intentions"] = []
        payload["predicted_outcomes"] = []
        payload["questions"] = []
        payload["memory_queries"] = []
        payload["body_intent"] = None
        payload["uncertainty"] = 0.2
        return payload


class CountingClock(TrustedRuntimeClock):
    def __init__(self, *, start_ms: int = 100_000, increment_ms: int = 1_000):
        self.calls = 0
        self._mono_ms = start_ms
        self._increment_ms = increment_ms

        def wall_time_ns():
            return int((1_700_000_000_000 + self._mono_ms) * 1_000_000)

        def monotonic_ns():
            value = self._mono_ms
            self._mono_ms += self._increment_ms
            return int(value * 1_000_000)

        super().__init__(
            wall_time_ns=wall_time_ns,
            monotonic_ns=monotonic_ns,
        )

    def sample(self):
        self.calls += 1
        return super().sample()


class CountingProfileLoader:
    def __init__(
        self,
        path: Path,
        *,
        before_load=None,
    ) -> None:
        self.path = path
        self.calls = 0
        self.before_load = before_load

    def __call__(self):
        self.calls += 1
        if self.before_load is not None:
            self.before_load()
        return load_cognitive_profile(
            path=self.path,
            engine_instance_id="thought-engine:test:autonomous",
        )


class AutonomousTickTests(unittest.TestCase):
    def set_flag(self, value: str | None) -> None:
        old = os.environ.get(AUTONOMOUS_COGNITION_FLAG)

        def restore():
            if old is None:
                os.environ.pop(AUTONOMOUS_COGNITION_FLAG, None)
            else:
                os.environ[AUTONOMOUS_COGNITION_FLAG] = old

        self.addCleanup(restore)
        if value is None:
            os.environ.pop(AUTONOMOUS_COGNITION_FLAG, None)
        else:
            os.environ[AUTONOMOUS_COGNITION_FLAG] = value

    def profile_path(self, root: Path) -> Path:
        path = root / "profile.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "kaliv-consciousness-core/cognitive-profile-config/v1",
                    "provider": "mock",
                    "model": "autonomous-test-model",
                    "reasoning_depth": 0.7,
                    "planning_capacity": 0.7,
                    "context_capacity_tokens": 8192,
                    "multimodal_capacity": 0.0,
                    "tool_reasoning": 0.0,
                    "uncertainty_calibration": 0.8,
                    "calibration_refs": ["calibration:c25b:test"],
                }
            ),
            encoding="utf-8",
        )
        return path

    def policy(self, **updates) -> AutonomousTriggerPolicy:
        payload = DEFAULT_AUTONOMOUS_TRIGGER_POLICY.model_dump(mode="json")
        payload.update(updates)
        return AutonomousTriggerPolicy.model_validate(payload)

    def session(
        self,
        *,
        engine: Engine | None = None,
        min_cycle_interval_ms: int = 0,
        max_events_per_cycle: int = 4,
    ):
        persistent = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=400,
            person_id="person-" + "b" * 32,
            person_revision="person-r0042",
            personality_state_ref="personality-state:c25b",
            world_state_ref="world-state:before-c25b",
            workspace_ref="workspace:before-c25b",
            active_goal_refs=["goal:c25b"],
            active_intention_refs=["intent:c25b"],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.1,
                arousal=0.3,
                confidence=0.9,
                source_refs=["affect:c25b"],
            ),
            known_uncertainties=[],
            last_experience_ref="memory4:experience:c25b",
            production_activation=False,
        )
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=persistent.person_id,
            person_revision=persistent.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="bodyrig:c25b",
            voice_source_ref="voicerig:c25b",
            registry_source_ref="person-registry:c25b",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=persistent,
            active_person=person,
            bootstrap_source_ref="runtime:c25b:test",
        )
        actual_engine = engine or Engine()
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(actual_engine),
            clock=CountingClock(start_ms=10_000, increment_ms=1_000),
            policy=SupervisorPolicy(
                schema="kaliv-consciousness-core/supervisor-policy/v1",
                min_cycle_interval_ms=min_cycle_interval_ms,
                max_events_per_cycle=max_events_per_cycle,
                production_activation=False,
            ),
        )
        return (
            ProductionCognitiveSession(
                supervisor_bridge=bridge,
                bootstrap_context=context,
            ),
            actual_engine,
        )

    def event(
        self,
        marker: str,
        *,
        kind: str = "world_change",
        salience: float = 1.0,
        sequence: int = 1,
    ) -> CognitionEvent:
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind=kind,
            source_ref=f"event:c25b:{kind}:{marker}",
            summary=f"C25-B {kind} {marker}",
            salience=salience,
            observed_sequence=sequence,
            production_activation=False,
        )

    def adapter(
        self,
        session,
        loader,
        *,
        clock=None,
        policy=None,
        accounting=None,
    ):
        return AutonomousCognitionTickAdapter(
            session=session,
            clock=clock or CountingClock(),
            profile_loader=loader,
            policy=policy or DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
            accounting=accounting,
        )

    def test_flag_contract_and_disabled_tick_touches_no_clock_profile_or_model(self):
        with tempfile.TemporaryDirectory() as td:
            self.set_flag(None)
            self.assertFalse(autonomous_cognition_enabled())
            session, engine = self.session()
            session.submit(self.event("1"))
            clock = CountingClock()
            loader = CountingProfileLoader(self.profile_path(Path(td)))
            adapter = self.adapter(session, loader, clock=clock)

            receipt = run(adapter.tick_once())

            self.assertEqual(receipt.outcome, "DISABLED")
            self.assertEqual(receipt.reason, "flag_disabled")
            self.assertEqual(clock.calls, 0)
            self.assertEqual(loader.calls, 0)
            self.assertEqual(engine.calls, 0)
            self.assertIsNone(adapter.accounting)
            self.assertEqual(receipt.pending_event_count, 0)
            self.assertEqual(receipt.evaluated_event_count, 0)

            for value in ("true", "yes", "on", "01", " 1 "):
                self.set_flag(value)
                self.assertFalse(autonomous_cognition_enabled(), value)

    def test_no_pending_event_is_idle_without_profile_io(self):
        with tempfile.TemporaryDirectory() as td:
            self.set_flag("1")
            session, engine = self.session()
            loader = CountingProfileLoader(self.profile_path(Path(td)))
            adapter = self.adapter(session, loader)
            receipt = run(adapter.tick_once())
            self.assertEqual(receipt.outcome, "IDLE")
            self.assertEqual(receipt.reason, "no_pending_events")
            self.assertEqual(loader.calls, 0)
            self.assertEqual(engine.calls, 0)
            self.assertIsNotNone(adapter.accounting)
            self.assertEqual(adapter.accounting.automatic_steps_in_window, 0)

    def test_denied_pending_event_blocks_eligible_event_and_profile_io(self):
        with tempfile.TemporaryDirectory() as td:
            self.set_flag("1")
            session, engine = self.session()
            eligible = self.event("1", kind="world_change", salience=1.0, sequence=2)
            denied = self.event("2", kind="user_turn", salience=1.0, sequence=1)
            session.submit(eligible)
            session.submit(denied)
            loader = CountingProfileLoader(self.profile_path(Path(td)))
            adapter = self.adapter(session, loader)

            receipt = run(adapter.tick_once())

            self.assertEqual(receipt.outcome, "IDLE")
            self.assertEqual(receipt.reason, "denied_pending_event")
            self.assertIn(denied.event_id, receipt.denied_event_ids)
            self.assertIn(eligible.event_id, receipt.eligible_event_ids)
            self.assertEqual(loader.calls, 0)
            self.assertEqual(engine.calls, 0)
            self.assertEqual(adapter.accounting.automatic_steps_in_window, 0)
            self.assertEqual(len(session.supervisor_state.pending_events), 2)

    def test_deferred_pending_event_blocks_all_automatic_cognition(self):
        with tempfile.TemporaryDirectory() as td:
            self.set_flag("1")
            session, engine = self.session()
            event = self.event("3", kind="world_change", salience=1.0)
            session.submit(event)
            clock = CountingClock(start_ms=110_000, increment_ms=1_000)
            accounting = AutomaticCognitionAccounting(
                schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
                runtime_epoch_id=clock.runtime_epoch_id,
                window_started_monotonic_ms=100_000,
                automatic_steps_in_window=1,
                last_automatic_step_monotonic_ms=105_000,
                production_activation=False,
            )
            loader = CountingProfileLoader(self.profile_path(Path(td)))
            adapter = self.adapter(
                session,
                loader,
                clock=clock,
                accounting=accounting,
            )

            receipt = run(adapter.tick_once())

            self.assertEqual(receipt.outcome, "DEFER")
            self.assertEqual(receipt.reason, "deferred_pending_event")
            self.assertEqual(receipt.not_before_monotonic_ms, 135_000)
            self.assertEqual(loader.calls, 0)
            self.assertEqual(engine.calls, 0)
            self.assertEqual(adapter.accounting, accounting)

    def test_all_eligible_events_run_once_in_canonical_order_and_record_budget(self):
        with tempfile.TemporaryDirectory() as td:
            self.set_flag("1")
            session, engine = self.session()
            lower = self.event("4", salience=0.90, sequence=1)
            higher_newer = self.event("5", salience=1.0, sequence=2)
            higher_older = self.event("6", salience=1.0, sequence=1)
            session.submit(lower)
            session.submit(higher_newer)
            session.submit(higher_older)
            loader = CountingProfileLoader(self.profile_path(Path(td)))
            adapter = self.adapter(
                session,
                loader,
                policy=self.policy(cooldown_ms=0),
            )

            receipt = run(adapter.tick_once())

            self.assertEqual(receipt.outcome, "RUN")
            self.assertEqual(receipt.reason, "ran")
            self.assertEqual(receipt.selected_event_id, higher_older.event_id)
            self.assertEqual(receipt.model_calls, 1)
            self.assertEqual(engine.calls, 1)
            self.assertEqual(loader.calls, 1)
            self.assertTrue(receipt.accounting_recorded)
            self.assertEqual(receipt.accounting_steps_before, 0)
            self.assertEqual(receipt.accounting_steps_after, 1)
            self.assertEqual(adapter.accounting.automatic_steps_in_window, 1)
            self.assertIn(higher_older.event_id, receipt.supervisor_selected_event_ids)
            self.assertFalse(receipt.execution_authority)
            self.assertFalse(receipt.scheduling_authority)
            self.assertFalse(receipt.durable_memory_write_authority)
            self.assertFalse(receipt.production_activation)

    def test_prediction_error_is_a_real_runnable_autonomous_event(self):
        with tempfile.TemporaryDirectory() as td:
            self.set_flag("1")
            session, engine = self.session(max_events_per_cycle=1)
            event = self.event(
                "7",
                kind="prediction_error",
                salience=0.90,
                sequence=7,
            )
            session.submit(event)
            loader = CountingProfileLoader(self.profile_path(Path(td)))
            adapter = self.adapter(
                session,
                loader,
                policy=self.policy(cooldown_ms=0),
            )

            receipt = run(adapter.tick_once())

            self.assertEqual(receipt.outcome, "RUN")
            self.assertEqual(receipt.selected_event_id, event.event_id)
            self.assertEqual(engine.calls, 1)

    def test_supervisor_wait_preserves_event_and_budget(self):
        with tempfile.TemporaryDirectory() as td:
            self.set_flag("1")
            session, engine = self.session(
                min_cycle_interval_ms=5_000,
                max_events_per_cycle=1,
            )
            loader = CountingProfileLoader(self.profile_path(Path(td)))
            adapter = self.adapter(
                session,
                loader,
                policy=self.policy(cooldown_ms=0),
            )

            first = self.event("8", sequence=1)
            session.submit(first)
            first_receipt = run(adapter.tick_once())
            self.assertEqual(first_receipt.outcome, "RUN")
            self.assertEqual(adapter.accounting.automatic_steps_in_window, 1)

            second = self.event("9", sequence=2)
            session.submit(second)
            before = adapter.accounting
            wait = run(adapter.tick_once())

            self.assertEqual(wait.outcome, "WAIT")
            self.assertEqual(wait.reason, "supervisor_wait")
            self.assertEqual(wait.model_calls, 0)
            self.assertFalse(wait.accounting_recorded)
            self.assertEqual(adapter.accounting, before)
            self.assertEqual(engine.calls, 1)
            self.assertEqual(
                [item.event_id for item in session.supervisor_state.pending_events],
                [second.event_id],
            )

    def test_profile_failure_occurs_only_after_eligibility_and_preserves_budget(self):
        self.set_flag("1")
        session, engine = self.session()
        event = self.event("a")
        session.submit(event)
        calls = {"profile": 0}

        def unavailable():
            calls["profile"] += 1
            return None

        adapter = self.adapter(
            session,
            unavailable,
            policy=self.policy(cooldown_ms=0),
        )
        with self.assertRaises(AutonomousCognitionAdapterError):
            run(adapter.tick_once())
        self.assertEqual(calls["profile"], 1)
        self.assertEqual(engine.calls, 0)
        self.assertEqual(adapter.accounting.automatic_steps_in_window, 0)
        self.assertEqual(len(session.supervisor_state.pending_events), 1)

    def test_provider_failure_preserves_budget(self):
        with tempfile.TemporaryDirectory() as td:
            self.set_flag("1")
            engine = Engine(fail=True)
            session, _ = self.session(engine=engine)
            session.submit(self.event("b"))
            loader = CountingProfileLoader(self.profile_path(Path(td)))
            adapter = self.adapter(
                session,
                loader,
                policy=self.policy(cooldown_ms=0),
            )
            with self.assertRaises(RuntimeError):
                run(adapter.tick_once())
            self.assertEqual(engine.calls, 1)
            self.assertEqual(adapter.accounting.automatic_steps_in_window, 0)

    def test_event_admitted_during_profile_load_cannot_hitchhike(self):
        with tempfile.TemporaryDirectory() as td:
            self.set_flag("1")
            session, engine = self.session(max_events_per_cycle=4)
            eligible = self.event(
                "c",
                kind="world_change",
                salience=0.90,
                sequence=2,
            )
            session.submit(eligible)

            injected = self.event(
                "d",
                kind="user_turn",
                salience=1.0,
                sequence=1,
            )
            loader = CountingProfileLoader(
                self.profile_path(Path(td)),
                before_load=lambda: session.submit(injected),
            )
            adapter = self.adapter(
                session,
                loader,
                policy=self.policy(cooldown_ms=0),
            )

            before = adapter.accounting
            with self.assertRaises(SupervisorLifecycleError):
                run(adapter.tick_once())

            self.assertEqual(loader.calls, 1)
            self.assertEqual(engine.calls, 0)
            self.assertEqual(adapter.accounting, before if before is not None else adapter.accounting)
            self.assertEqual(adapter.accounting.automatic_steps_in_window, 0)
            self.assertEqual(
                {item.event_id for item in session.supervisor_state.pending_events},
                {eligible.event_id, injected.event_id},
            )

    def test_allowed_event_snapshot_rejects_unknown_selected_event_before_model(self):
        with tempfile.TemporaryDirectory() as td:
            self.set_flag("1")
            session, engine = self.session(max_events_per_cycle=4)
            allowed = self.event("e", salience=0.8, sequence=2)
            forbidden = self.event("f", kind="operator_signal", salience=1.0, sequence=1)
            session.submit(allowed)
            session.submit(forbidden)
            loaded = load_cognitive_profile(path=self.profile_path(Path(td)))
            self.assertIsNotNone(loaded)

            with self.assertRaises(SupervisorLifecycleError):
                run(
                    session.step(
                        profile=loaded.profile,
                        required_event_id=allowed.event_id,
                        allowed_event_ids=[allowed.event_id],
                    )
                )
            self.assertEqual(engine.calls, 0)
            self.assertEqual(len(session.supervisor_state.pending_events), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
