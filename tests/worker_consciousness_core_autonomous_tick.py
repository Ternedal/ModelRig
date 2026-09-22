#!/usr/bin/env python3
"""C25-B caller-driven one-tick autonomous cognition adapter tests.

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
    AutonomousCognitionTickAdapter,
    AutonomousCognitionTickError,
    autonomous_cognition_enabled,
)
from app.consciousness_core.autonomous_trigger_policy import (  # noqa: E402
    DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
    AutomaticCognitionAccounting,
    AutonomousTriggerPolicy,
)
from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402
from app.consciousness_core.profile_source import load_cognitive_profile  # noqa: E402
from app.consciousness_core.supervisor import (  # noqa: E402
    CognitionEvent,
    SupervisorPolicy,
)
from app.consciousness_core.supervisor_lifecycle import ProductionSupervisorBridge  # noqa: E402
from app.consciousness_core.temporal import ClockSample  # noqa: E402


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


class Engine:
    def __init__(self, *, fail: bool = False):
        self.calls = 0
        self.fail = fail

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("PRIVATE-PROVIDER-FAILURE")
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + f"{self.calls:x}"[-1] * 32
        payload["interpretation"] = "autonomous thought"
        payload["response_intent"] = None
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.1
        return payload


class CountingClock:
    def __init__(self, samples):
        self.samples = list(samples)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if not self.samples:
            raise AssertionError("unexpected autonomous clock call")
        return self.samples.pop(0)


class CountingLoader:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


def bridge_clock(monotonic_values):
    wall_values = iter(
        1_700_000_000_000_000_000 + value * 1_000_000
        for value in monotonic_values
    )
    mono_values = iter(value * 1_000_000 for value in monotonic_values)
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall_values),
        monotonic_ns=lambda: next(mono_values),
    )


class AutonomousTickTests(unittest.TestCase):
    def clock(
        self,
        *,
        monotonic_ms: int,
        marker: str,
        epoch: str = "a",
    ) -> ClockSample:
        return ClockSample(
            schema="kaliv-consciousness-core/clock-sample/v1",
            sample_id="clock-" + marker * 32,
            wall_time_unix_ms=1_700_000_000_000 + monotonic_ms,
            timezone_name="Europe/Copenhagen",
            utc_offset_minutes=120,
            local_hour=12,
            monotonic_ms=monotonic_ms,
            runtime_epoch_id="epoch-" + epoch * 32,
            sampled_sequence=monotonic_ms // 1000,
            source_ref="clock:test:c25b",
            confidence=1.0,
            production_activation=False,
        )

    def policy(self, **updates) -> AutonomousTriggerPolicy:
        values = DEFAULT_AUTONOMOUS_TRIGGER_POLICY.model_dump(mode="json")
        values.update(updates)
        return AutonomousTriggerPolicy.model_validate(values)

    def profile_result(self):
        td = tempfile.TemporaryDirectory()
        path = Path(td.name) / "profile.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "kaliv-consciousness-core/cognitive-profile-config/v1",
                    "provider": "mock",
                    "model": "c25b-model",
                    "reasoning_depth": 0.8,
                    "planning_capacity": 0.8,
                    "context_capacity_tokens": 8192,
                    "multimodal_capacity": 0.0,
                    "tool_reasoning": 0.0,
                    "uncertainty_calibration": 0.9,
                    "calibration_refs": ["test:c25b"],
                }
            ),
            encoding="utf-8",
        )
        loaded = load_cognitive_profile(path=path)
        self.assertIsNotNone(loaded)
        return td, loaded

    def session(
        self,
        *,
        engine=None,
        bridge_monotonic=(1_000, 2_000, 3_000, 4_000),
        min_cycle_interval_ms=500,
    ):
        state = PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=120,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            personality_state_ref="personality-state:test",
            world_state_ref="world-state:prior",
            workspace_ref="workspace:prior",
            active_goal_refs=["goal:test"],
            active_intention_refs=["intent:test"],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.1,
                arousal=0.2,
                confidence=0.9,
                source_refs=["affect:test"],
            ),
            known_uncertainties=[],
            last_experience_ref="memory4:last",
            production_activation=False,
        )
        person = ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:test",
            voice_source_ref="voice:test",
            registry_source_ref="registry:test",
            production_activation=False,
        )
        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=person,
            bootstrap_source_ref="runtime:test:c25b",
        )
        actual_engine = engine or Engine()
        bridge = ProductionSupervisorBridge(
            runtime=ConsciousnessCoreRuntime(actual_engine),
            clock=bridge_clock(bridge_monotonic),
            policy=SupervisorPolicy(
                schema="kaliv-consciousness-core/supervisor-policy/v1",
                min_cycle_interval_ms=min_cycle_interval_ms,
                max_events_per_cycle=4,
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
        kind: str,
        *,
        marker: str,
        salience: float = 1.0,
        sequence: int = 1,
    ) -> CognitionEvent:
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind=kind,
            source_ref=f"event:test:{kind}:{marker}",
            summary=f"Event {kind}",
            salience=salience,
            observed_sequence=sequence,
            production_activation=False,
        )

    def test_exact_autonomous_flag_contract(self):
        old = os.environ.get(AUTONOMOUS_COGNITION_FLAG)
        try:
            os.environ.pop(AUTONOMOUS_COGNITION_FLAG, None)
            self.assertFalse(autonomous_cognition_enabled())
            for value in ("true", "on", "yes", "01", " 1 "):
                os.environ[AUTONOMOUS_COGNITION_FLAG] = value
                self.assertFalse(autonomous_cognition_enabled(), value)
            os.environ[AUTONOMOUS_COGNITION_FLAG] = "1"
            self.assertTrue(autonomous_cognition_enabled())
        finally:
            if old is None:
                os.environ.pop(AUTONOMOUS_COGNITION_FLAG, None)
            else:
                os.environ[AUTONOMOUS_COGNITION_FLAG] = old

    def test_disabled_tick_touches_no_clock_profile_or_model(self):
        session, engine = self.session()
        clock = CountingClock([])
        loader = CountingLoader(None)
        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=clock,
            profile_loader=loader,
            enabled_fn=lambda: False,
        )
        receipt = run(adapter.tick_once())
        self.assertEqual(receipt.outcome, "DISABLED")
        self.assertEqual(receipt.reason, "disabled")
        self.assertEqual(clock.calls, 0)
        self.assertEqual(loader.calls, 0)
        self.assertEqual(engine.calls, 0)
        self.assertIsNone(adapter.accounting)

    def test_no_pending_events_is_idle_and_does_not_load_profile(self):
        session, engine = self.session()
        clock = CountingClock([self.clock(monotonic_ms=100_000, marker="1")])
        loader = CountingLoader(None)
        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=clock,
            profile_loader=loader,
            enabled_fn=lambda: True,
        )
        receipt = run(adapter.tick_once())
        self.assertEqual(receipt.outcome, "IDLE")
        self.assertEqual(receipt.reason, "no_pending_events")
        self.assertEqual(loader.calls, 0)
        self.assertEqual(engine.calls, 0)
        self.assertIsNotNone(adapter.accounting)

    def test_pending_user_turn_blocks_eligible_world_change_anti_hitchhike(self):
        td, profile = self.profile_result()
        self.addCleanup(td.cleanup)
        session, engine = self.session()
        session.submit(self.event("world_change", marker="2", salience=1.0, sequence=2))
        session.submit(self.event("user_turn", marker="3", salience=1.0, sequence=3))
        loader = CountingLoader(profile)
        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=CountingClock(
                [self.clock(monotonic_ms=100_000, marker="2")]
            ),
            profile_loader=loader,
            enabled_fn=lambda: True,
        )
        receipt = run(adapter.tick_once())
        self.assertEqual(receipt.outcome, "IDLE")
        self.assertEqual(receipt.reason, "pending_event_denied")
        self.assertEqual(loader.calls, 0)
        self.assertEqual(engine.calls, 0)
        self.assertEqual(len(session.supervisor_state.pending_events), 2)

    def test_any_deferred_event_blocks_tick_before_profile(self):
        td, profile = self.profile_result()
        self.addCleanup(td.cleanup)
        session, engine = self.session()
        session.submit(self.event("world_change", marker="4", sequence=4))
        accounting = AutomaticCognitionAccounting(
            schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
            runtime_epoch_id="epoch-" + "a" * 32,
            window_started_monotonic_ms=90_000,
            automatic_steps_in_window=1,
            last_automatic_step_monotonic_ms=99_000,
            production_activation=False,
        )
        loader = CountingLoader(profile)
        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=CountingClock(
                [self.clock(monotonic_ms=100_000, marker="3")]
            ),
            profile_loader=loader,
            policy=self.policy(cooldown_ms=30_000),
            accounting=accounting,
            enabled_fn=lambda: True,
        )
        receipt = run(adapter.tick_once())
        self.assertEqual(receipt.outcome, "DEFER")
        self.assertEqual(receipt.reason, "pending_event_deferred")
        self.assertEqual(receipt.not_before_monotonic_ms, 129_000)
        self.assertEqual(loader.calls, 0)
        self.assertEqual(engine.calls, 0)
        self.assertEqual(adapter.accounting, accounting)

    def test_profile_unavailable_never_calls_model_or_updates_accounting(self):
        session, engine = self.session()
        session.submit(self.event("wake_followup", marker="5", sequence=5))
        clock = self.clock(monotonic_ms=100_000, marker="4")
        accounting = AutomaticCognitionAccounting(
            schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
            runtime_epoch_id=clock.runtime_epoch_id,
            window_started_monotonic_ms=100_000,
            automatic_steps_in_window=0,
            last_automatic_step_monotonic_ms=None,
            production_activation=False,
        )
        loader = CountingLoader(None)
        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=CountingClock([clock]),
            profile_loader=loader,
            accounting=accounting,
            enabled_fn=lambda: True,
        )
        receipt = run(adapter.tick_once())
        self.assertEqual(receipt.outcome, "IDLE")
        self.assertEqual(receipt.reason, "profile_unavailable")
        self.assertEqual(loader.calls, 1)
        self.assertEqual(engine.calls, 0)
        self.assertEqual(adapter.accounting, accounting)

    def test_run_selects_highest_salience_and_records_once(self):
        td, profile = self.profile_result()
        self.addCleanup(td.cleanup)
        session, engine = self.session()
        low = self.event(
            "world_change",
            marker="6",
            salience=0.85,
            sequence=1,
        )
        high = self.event(
            "prediction_error",
            marker="7",
            salience=0.99,
            sequence=2,
        )
        session.submit(low)
        session.submit(high)
        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=CountingClock(
                [self.clock(monotonic_ms=100_000, marker="5")]
            ),
            profile_loader=CountingLoader(profile),
            policy=self.policy(cooldown_ms=0),
            enabled_fn=lambda: True,
        )
        receipt = run(adapter.tick_once())
        self.assertEqual(receipt.outcome, "RUN")
        self.assertEqual(receipt.reason, "run_completed")
        self.assertEqual(receipt.selected_event_id, high.event_id)
        self.assertIn(high.event_id, receipt.supervisor_selected_event_ids)
        self.assertEqual(receipt.thought_engine_calls, 1)
        self.assertEqual(engine.calls, 1)
        self.assertTrue(receipt.accounting_updated)
        self.assertEqual(receipt.accounting_steps_before, 0)
        self.assertEqual(receipt.accounting_steps_after, 1)
        self.assertEqual(adapter.accounting.automatic_steps_in_window, 1)

    def test_tie_break_prefers_oldest_observed_sequence_then_event_id(self):
        td, profile = self.profile_result()
        self.addCleanup(td.cleanup)
        session, _ = self.session()
        newer = self.event(
            "world_change",
            marker="8",
            salience=0.9,
            sequence=10,
        )
        older = self.event(
            "prediction_error",
            marker="9",
            salience=0.9,
            sequence=5,
        )
        session.submit(newer)
        session.submit(older)
        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=CountingClock(
                [self.clock(monotonic_ms=100_000, marker="6")]
            ),
            profile_loader=CountingLoader(profile),
            policy=self.policy(cooldown_ms=0),
            enabled_fn=lambda: True,
        )
        receipt = run(adapter.tick_once())
        self.assertEqual(receipt.selected_event_id, older.event_id)

    def test_selection_matches_canonical_supervisor_order_beyond_cycle_budget(self):
        td, profile = self.profile_result()
        self.addCleanup(td.cleanup)
        session, engine = self.session()
        events = [
            self.event(
                "world_change",
                marker=marker,
                salience=0.95,
                sequence=sequence,
            )
            for marker, sequence in zip(("1", "2", "3", "4", "5"), (5, 4, 3, 2, 1))
        ]
        for event in events:
            session.submit(event)

        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=CountingClock(
                [self.clock(monotonic_ms=100_000, marker="d")]
            ),
            profile_loader=CountingLoader(profile),
            policy=self.policy(cooldown_ms=0),
            enabled_fn=lambda: True,
        )
        receipt = run(adapter.tick_once())
        expected = events[-1]
        self.assertEqual(receipt.outcome, "RUN")
        self.assertEqual(receipt.selected_event_id, expected.event_id)
        self.assertIn(expected.event_id, receipt.supervisor_selected_event_ids)
        self.assertEqual(len(receipt.supervisor_selected_event_ids), 4)
        self.assertEqual(engine.calls, 1)

    def test_supervisor_wait_does_not_increment_accounting(self):
        td, profile = self.profile_result()
        self.addCleanup(td.cleanup)
        session, engine = self.session(
            bridge_monotonic=(1_000, 2_000, 2_100, 3_000),
            min_cycle_interval_ms=500,
        )
        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=CountingClock(
                [
                    self.clock(monotonic_ms=100_000, marker="7"),
                    self.clock(monotonic_ms=101_000, marker="8"),
                ]
            ),
            profile_loader=CountingLoader(profile),
            policy=self.policy(cooldown_ms=0),
            enabled_fn=lambda: True,
        )

        session.submit(self.event("wake_followup", marker="a", sequence=1))
        first = run(adapter.tick_once())
        self.assertEqual(first.outcome, "RUN")
        self.assertEqual(adapter.accounting.automatic_steps_in_window, 1)

        session.submit(self.event("wake_followup", marker="b", sequence=2))
        before = adapter.accounting
        second = run(adapter.tick_once())
        self.assertEqual(second.outcome, "WAIT")
        self.assertEqual(second.reason, "supervisor_wait")
        self.assertEqual(second.thought_engine_calls, 0)
        self.assertFalse(second.accounting_updated)
        self.assertEqual(adapter.accounting, before)
        self.assertEqual(engine.calls, 1)
        self.assertTrue(
            any(
                event.event_id == "cevt-" + "b" * 32
                for event in session.supervisor_state.pending_events
            )
        )

    def test_provider_failure_does_not_increment_accounting(self):
        td, profile = self.profile_result()
        self.addCleanup(td.cleanup)
        session, engine = self.session(engine=Engine(fail=True))
        session.submit(self.event("wake_followup", marker="c", sequence=1))
        clock = self.clock(monotonic_ms=100_000, marker="9")
        accounting = AutomaticCognitionAccounting(
            schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
            runtime_epoch_id=clock.runtime_epoch_id,
            window_started_monotonic_ms=100_000,
            automatic_steps_in_window=0,
            last_automatic_step_monotonic_ms=None,
            production_activation=False,
        )
        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=CountingClock([clock]),
            profile_loader=CountingLoader(profile),
            policy=self.policy(cooldown_ms=0),
            accounting=accounting,
            enabled_fn=lambda: True,
        )
        with self.assertRaises(AutonomousCognitionTickError):
            run(adapter.tick_once())
        self.assertEqual(engine.calls, 1)
        self.assertEqual(adapter.accounting, accounting)
        self.assertEqual(adapter.accounting.automatic_steps_in_window, 0)

    def test_epoch_mismatch_fails_closed_without_profile_or_model(self):
        td, profile = self.profile_result()
        self.addCleanup(td.cleanup)
        session, engine = self.session()
        session.submit(self.event("wake_followup", marker="d", sequence=1))
        accounting = AutomaticCognitionAccounting(
            schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
            runtime_epoch_id="epoch-" + "a" * 32,
            window_started_monotonic_ms=90_000,
            automatic_steps_in_window=0,
            last_automatic_step_monotonic_ms=None,
            production_activation=False,
        )
        loader = CountingLoader(profile)
        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=CountingClock(
                [self.clock(monotonic_ms=100_000, marker="a", epoch="b")]
            ),
            profile_loader=loader,
            accounting=accounting,
            enabled_fn=lambda: True,
        )
        receipt = run(adapter.tick_once())
        self.assertEqual(receipt.outcome, "IDLE")
        self.assertEqual(receipt.reason, "pending_event_denied")
        self.assertEqual(loader.calls, 0)
        self.assertEqual(engine.calls, 0)
        self.assertEqual(adapter.accounting, accounting)

    def test_closed_session_is_idle_before_clock_or_profile(self):
        session, engine = self.session()
        session.close()
        clock = CountingClock([])
        loader = CountingLoader(None)
        adapter = AutonomousCognitionTickAdapter(
            session=session,
            clock_sample_fn=clock,
            profile_loader=loader,
            enabled_fn=lambda: True,
        )
        receipt = run(adapter.tick_once())
        self.assertEqual(receipt.outcome, "IDLE")
        self.assertEqual(receipt.reason, "session_closed")
        self.assertEqual(clock.calls, 0)
        self.assertEqual(loader.calls, 0)
        self.assertEqual(engine.calls, 0)


if __name__ == "__main__":
    unittest.main()
