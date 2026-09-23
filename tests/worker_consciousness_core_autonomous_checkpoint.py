#!/usr/bin/env python3
"""C27-H autonomous cognition/checkpoint coupling tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_autonomous_checkpoint.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.autonomous_scheduler import (  # noqa: E402
    AUTONOMOUS_CHECKPOINT_FLAG,
    AUTONOMOUS_SCHEDULER_FLAG,
    AutonomousSchedulerBridgeError,
    ScheduledAutonomousCognitionBridge,
    autonomous_checkpoint_enabled,
    production_autonomous_scheduler_bridge_factory,
)
from app.consciousness_core.autonomous_tick import (  # noqa: E402
    AUTONOMOUS_COGNITION_FLAG,
    AutonomousCognitionTickAdapter,
    AutonomousCognitionTickReceipt,
)
from app.consciousness_core.checkpoint_pressure import (  # noqa: E402
    evaluate_checkpoint_pressure,
)
from app.consciousness_core.policy_checkpoint import (  # noqa: E402
    PolicyDrivenCheckpointResult,
    PolicyDrivenSelfStateCheckpointAdapter,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.self_state_checkpoint_runtime import (  # noqa: E402
    RuntimeSelfStateCheckpointResult,
    runtime_checkpoint_plan_ref,
)
from app.consciousness_core.self_state_ledger import (  # noqa: E402
    RuntimeSelfStateCheckpointPlan,
    RuntimeSelfStateTransition,
)
from app.consciousness_core.session_lifecycle import (  # noqa: E402
    ProductionCognitiveSession,
)
from app.schedule_runner import TickResult  # noqa: E402


def schedule_tick() -> TickResult:
    return TickResult(
        enabled=True,
        paused=False,
        claimed=0,
        completed=0,
        blocked=0,
        failed=0,
        job_ids=(),
    )


def checkpoint_plan(*, completed_cycle=False):
    transitions = [
        RuntimeSelfStateTransition(
            schema=(
                "kaliv-consciousness-core/"
                "runtime-self-state-transition/v1"
            ),
            kind="session_bootstrap",
            state_ref="self-state:" + "1" * 64,
            revision=2,
            source_ref="bootstrap:test:c27h",
            production_activation=False,
        )
    ]
    if completed_cycle:
        transitions.extend(
            [
                RuntimeSelfStateTransition(
                    schema=(
                        "kaliv-consciousness-core/"
                        "runtime-self-state-transition/v1"
                    ),
                    kind="supervisor_orientation",
                    state_ref="self-state:" + "2" * 64,
                    revision=3,
                    source_ref="supervisor:test:c27h",
                    production_activation=False,
                ),
                RuntimeSelfStateTransition(
                    schema=(
                        "kaliv-consciousness-core/"
                        "runtime-self-state-transition/v1"
                    ),
                    kind="post_cycle_reduction",
                    state_ref="self-state:" + "3" * 64,
                    revision=4,
                    source_ref="reducer:test:c27h",
                    production_activation=False,
                ),
            ]
        )
    return RuntimeSelfStateCheckpointPlan(
        schema=(
            "kaliv-consciousness-core/"
            "runtime-self-state-checkpoint-plan/v1"
        ),
        anchor_state_ref="self-state:" + "0" * 64,
        final_state_ref=transitions[-1].state_ref,
        self_id="self-" + "a" * 32,
        person_id="person-" + "b" * 32,
        person_revision="person-r0007",
        revision_before=1,
        revision_after=transitions[-1].revision,
        transitions=transitions,
        transition_count=len(transitions),
        self_state_store_write_applied=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )


def policy_result(outcome):
    if outcome == "IDLE":
        pressure = evaluate_checkpoint_pressure(plan=None)
        return PolicyDrivenCheckpointResult(
            schema=(
                "kaliv-consciousness-core/"
                "policy-driven-checkpoint-result/v1"
            ),
            outcome="IDLE",
            pressure=pressure,
            evaluated_plan_ref=None,
            checkpoint=None,
            coordinator_invoked=False,
            self_state_store_write_applied=False,
            model_calls=0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )

    plan = checkpoint_plan(completed_cycle=outcome == "COMMITTED")
    pressure = evaluate_checkpoint_pressure(plan=plan)
    plan_ref = runtime_checkpoint_plan_ref(plan)
    if outcome == "HOLD":
        return PolicyDrivenCheckpointResult(
            schema=(
                "kaliv-consciousness-core/"
                "policy-driven-checkpoint-result/v1"
            ),
            outcome="HOLD",
            pressure=pressure,
            evaluated_plan_ref=plan_ref,
            checkpoint=None,
            coordinator_invoked=False,
            self_state_store_write_applied=False,
            model_calls=0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )

    checkpoint = RuntimeSelfStateCheckpointResult(
        schema=(
            "kaliv-consciousness-core/"
            "runtime-self-state-checkpoint-result/v1"
        ),
        outcome="COMMITTED",
        plan_ref=plan_ref,
        store_receipt_ref="self-state-checkpoint-receipt:" + "4" * 64,
        transition_count=plan.transition_count,
        revision_before=plan.revision_before,
        revision_after=plan.revision_after,
        self_state_store_write_applied=True,
        ledger_reanchored=True,
        intermediate_history_persisted=False,
        model_calls=0,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
    return PolicyDrivenCheckpointResult(
        schema=(
            "kaliv-consciousness-core/"
            "policy-driven-checkpoint-result/v1"
        ),
        outcome="COMMITTED",
        pressure=pressure,
        evaluated_plan_ref=plan_ref,
        checkpoint=checkpoint,
        coordinator_invoked=True,
        self_state_store_write_applied=True,
        model_calls=0,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )


def tick_receipt(outcome):
    if outcome == "RUN":
        event_id = "cevt-" + "7" * 32
        return AutonomousCognitionTickReceipt(
            schema="kaliv-consciousness-core/autonomous-cognition-tick/v1",
            outcome="RUN",
            reason="ran",
            clock_sample_id="clock-" + "1" * 32,
            runtime_epoch_id="epoch-" + "2" * 32,
            pending_event_count=1,
            evaluated_event_count=1,
            denied_event_ids=[],
            deferred_event_ids=[],
            eligible_event_ids=[event_id],
            selected_event_id=event_id,
            supervisor_selected_event_ids=[event_id],
            not_before_monotonic_ms=None,
            cognitive_profile_ref="cognitive-profile:test:c27h",
            model_calls=1,
            accounting_steps_before=0,
            accounting_steps_after=1,
            accounting_recorded=True,
            automatic_repeat=False,
            internal_thread_created=False,
            internal_timer_created=False,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
    return AutonomousCognitionTickReceipt(
        schema="kaliv-consciousness-core/autonomous-cognition-tick/v1",
        outcome="IDLE",
        reason="no_pending_events",
        clock_sample_id="clock-" + "1" * 32,
        runtime_epoch_id="epoch-" + "2" * 32,
        pending_event_count=0,
        evaluated_event_count=0,
        denied_event_ids=[],
        deferred_event_ids=[],
        eligible_event_ids=[],
        selected_event_id=None,
        supervisor_selected_event_ids=[],
        not_before_monotonic_ms=None,
        cognitive_profile_ref=None,
        model_calls=0,
        accounting_steps_before=0,
        accounting_steps_after=0,
        accounting_recorded=False,
        automatic_repeat=False,
        internal_thread_created=False,
        internal_timer_created=False,
        self_state_store_write_applied=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )


class StubTickAdapter(AutonomousCognitionTickAdapter):
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0
        self.thread_ids = []

    async def tick_once(self):
        self.calls += 1
        self.thread_ids.append(threading.get_ident())
        return tick_receipt(self._outcomes.pop(0))


class StubCheckpointAdapter(PolicyDrivenSelfStateCheckpointAdapter):
    def __init__(self, actions):
        self._actions = list(actions)
        self.calls = 0
        self.thread_ids = []

    def maybe_checkpoint_once(self):
        self.calls += 1
        self.thread_ids.append(threading.get_ident())
        action = self._actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


class LiveSessionStub(ProductionCognitiveSession):
    def __init__(self, clock):
        self._test_clock = clock

    @property
    def closed(self):
        return False

    @property
    def trusted_clock(self):
        return self._test_clock


class AutonomousCheckpointTests(unittest.TestCase):
    def setUp(self):
        self._old = {
            name: os.environ.get(name)
            for name in (
                AUTONOMOUS_CHECKPOINT_FLAG,
                AUTONOMOUS_SCHEDULER_FLAG,
                AUTONOMOUS_COGNITION_FLAG,
            )
        }

    def tearDown(self):
        for name, value in self._old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_exact_autonomous_checkpoint_flag_contract(self):
        os.environ.pop(AUTONOMOUS_CHECKPOINT_FLAG, None)
        self.assertFalse(autonomous_checkpoint_enabled())
        for value in ("0", "true", "yes", "on", "01", " 1 "):
            os.environ[AUTONOMOUS_CHECKPOINT_FLAG] = value
            self.assertFalse(autonomous_checkpoint_enabled(), value)
        os.environ[AUTONOMOUS_CHECKPOINT_FLAG] = "1"
        self.assertTrue(autonomous_checkpoint_enabled())

    def test_checkpoint_preflight_and_tick_run_on_owner_loop(self):
        async def scenario():
            owner_thread = threading.get_ident()
            tick = StubTickAdapter(["IDLE"])
            checkpoint = StubCheckpointAdapter([policy_result("HOLD")])
            bridge = ScheduledAutonomousCognitionBridge(
                adapter=tick,
                checkpoint_adapter=checkpoint,
                owner_loop=asyncio.get_running_loop(),
                timeout_s=1.0,
            )
            bridge.mark_installed()

            await asyncio.to_thread(
                bridge.on_scheduler_tick,
                schedule_tick(),
            )

            status = bridge.status()
            self.assertEqual(tick.calls, 1)
            self.assertEqual(checkpoint.calls, 1)
            self.assertEqual(tick.thread_ids, [owner_thread])
            self.assertEqual(checkpoint.thread_ids, [owner_thread])
            self.assertTrue(status.checkpoint_enabled)
            self.assertEqual(status.checkpoint_evaluation_count, 1)
            self.assertEqual(status.checkpoint_commit_count, 0)
            self.assertEqual(status.checkpoint_failure_count, 0)
            self.assertEqual(status.last_checkpoint_outcome, "HOLD")
            self.assertIsNone(status.last_checkpoint_error)
            self.assertEqual(status.completed_count, 1)
            self.assertEqual(status.last_outcome, "IDLE")
            await bridge.aclose()

        asyncio.run(scenario())

    def test_run_performs_post_checkpoint_and_records_both_outcomes(self):
        async def scenario():
            tick = StubTickAdapter(["RUN"])
            checkpoint = StubCheckpointAdapter(
                [
                    policy_result("HOLD"),
                    policy_result("COMMITTED"),
                ]
            )
            bridge = ScheduledAutonomousCognitionBridge(
                adapter=tick,
                checkpoint_adapter=checkpoint,
                owner_loop=asyncio.get_running_loop(),
                timeout_s=1.0,
            )
            bridge.mark_installed()

            await asyncio.to_thread(
                bridge.on_scheduler_tick,
                schedule_tick(),
            )

            status = bridge.status()
            self.assertEqual(tick.calls, 1)
            self.assertEqual(checkpoint.calls, 2)
            self.assertEqual(status.completed_count, 1)
            self.assertEqual(status.last_outcome, "RUN")
            self.assertEqual(status.failure_count, 0)
            self.assertEqual(status.checkpoint_evaluation_count, 2)
            self.assertEqual(status.checkpoint_commit_count, 1)
            self.assertEqual(status.checkpoint_failure_count, 0)
            self.assertEqual(
                status.last_checkpoint_outcome,
                "COMMITTED",
            )
            self.assertIsNone(status.last_checkpoint_error)
            await bridge.aclose()

        asyncio.run(scenario())

    def test_pre_checkpoint_failure_blocks_cognition_until_recovered(self):
        async def scenario():
            tick = StubTickAdapter(["IDLE"])
            checkpoint = StubCheckpointAdapter(
                [
                    RuntimeError("simulated preflight failure"),
                    policy_result("HOLD"),
                ]
            )
            bridge = ScheduledAutonomousCognitionBridge(
                adapter=tick,
                checkpoint_adapter=checkpoint,
                owner_loop=asyncio.get_running_loop(),
                timeout_s=1.0,
            )
            bridge.mark_installed()

            await asyncio.to_thread(
                bridge.on_scheduler_tick,
                schedule_tick(),
            )
            first = bridge.status()
            self.assertEqual(tick.calls, 0)
            self.assertEqual(first.completed_count, 0)
            self.assertEqual(first.failure_count, 1)
            self.assertEqual(first.checkpoint_failure_count, 1)
            self.assertIn(
                "pre-tick SelfState checkpoint failed",
                first.last_checkpoint_error,
            )

            await asyncio.to_thread(
                bridge.on_scheduler_tick,
                schedule_tick(),
            )
            second = bridge.status()
            self.assertEqual(tick.calls, 1)
            self.assertEqual(checkpoint.calls, 2)
            self.assertEqual(second.completed_count, 1)
            self.assertEqual(second.last_outcome, "IDLE")
            self.assertEqual(second.checkpoint_failure_count, 1)
            self.assertEqual(second.last_checkpoint_outcome, "HOLD")
            self.assertIsNone(second.last_checkpoint_error)
            await bridge.aclose()

        asyncio.run(scenario())

    def test_post_run_failure_records_run_and_next_tick_checkpoints_first(self):
        async def scenario():
            tick = StubTickAdapter(["RUN", "IDLE"])
            checkpoint = StubCheckpointAdapter(
                [
                    policy_result("HOLD"),
                    RuntimeError("simulated post-run failure"),
                    policy_result("COMMITTED"),
                ]
            )
            bridge = ScheduledAutonomousCognitionBridge(
                adapter=tick,
                checkpoint_adapter=checkpoint,
                owner_loop=asyncio.get_running_loop(),
                timeout_s=1.0,
            )
            bridge.mark_installed()

            await asyncio.to_thread(
                bridge.on_scheduler_tick,
                schedule_tick(),
            )
            first = bridge.status()
            self.assertEqual(tick.calls, 1)
            self.assertEqual(first.completed_count, 1)
            self.assertEqual(first.last_outcome, "RUN")
            self.assertEqual(first.failure_count, 1)
            self.assertEqual(first.checkpoint_failure_count, 1)
            self.assertIn(
                "post-tick SelfState checkpoint failed",
                first.last_checkpoint_error,
            )

            await asyncio.to_thread(
                bridge.on_scheduler_tick,
                schedule_tick(),
            )
            second = bridge.status()
            self.assertEqual(checkpoint.calls, 3)
            self.assertEqual(tick.calls, 2)
            self.assertEqual(second.completed_count, 2)
            self.assertEqual(second.last_outcome, "IDLE")
            self.assertEqual(second.checkpoint_commit_count, 1)
            self.assertEqual(
                second.last_checkpoint_outcome,
                "COMMITTED",
            )
            self.assertIsNone(second.last_checkpoint_error)
            await bridge.aclose()

        asyncio.run(scenario())

    def test_gate_off_does_not_read_checkpoint_service(self):
        async def scenario():
            os.environ[AUTONOMOUS_SCHEDULER_FLAG] = "1"
            os.environ[AUTONOMOUS_COGNITION_FLAG] = "1"
            os.environ[AUTONOMOUS_CHECKPOINT_FLAG] = "0"

            clock = TrustedRuntimeClock(
                wall_time_ns=lambda: 1_700_000_000_000_000_000,
                monotonic_ns=lambda: 10_000_000_000,
            )
            session = LiveSessionStub(clock)

            class RunningRuntime:
                def status(self):
                    return SimpleNamespace(running=True)

            class State:
                scheduler_runtime = RunningRuntime()
                consciousness_session = session

                @property
                def consciousness_policy_checkpoint(self):
                    raise AssertionError(
                        "checkpoint gate-off touched C27-G service"
                    )

            app = SimpleNamespace(state=State())
            bridge = production_autonomous_scheduler_bridge_factory(
                app,
                timeout_s=1.0,
            )
            self.assertIsNotNone(bridge)
            self.assertIsNone(bridge._checkpoint_adapter)
            await bridge.aclose()

        asyncio.run(scenario())

    def test_gate_on_requires_live_c27g_service(self):
        async def scenario():
            os.environ[AUTONOMOUS_SCHEDULER_FLAG] = "1"
            os.environ[AUTONOMOUS_COGNITION_FLAG] = "1"
            os.environ[AUTONOMOUS_CHECKPOINT_FLAG] = "1"

            clock = TrustedRuntimeClock(
                wall_time_ns=lambda: 1_700_000_000_000_000_000,
                monotonic_ns=lambda: 10_000_000_000,
            )
            session = LiveSessionStub(clock)

            class RunningRuntime:
                def status(self):
                    return SimpleNamespace(running=True)

            app = SimpleNamespace(
                state=SimpleNamespace(
                    scheduler_runtime=RunningRuntime(),
                    consciousness_session=session,
                )
            )
            with self.assertRaisesRegex(
                AutonomousSchedulerBridgeError,
                "requires live C27-G policy checkpoint service",
            ):
                production_autonomous_scheduler_bridge_factory(
                    app,
                    timeout_s=1.0,
                )

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
