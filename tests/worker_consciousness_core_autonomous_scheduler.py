#!/usr/bin/env python3
"""C25-C scheduler cadence bridge regression tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_autonomous_scheduler.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.autonomous_scheduler import (  # noqa: E402
    AUTONOMOUS_SCHEDULER_FLAG,
    ScheduledAutonomousCognitionBridge,
    autonomous_scheduler_enabled,
    compose_autonomous_scheduler_lifespan,
    production_autonomous_scheduler_bridge_factory,
)
from app.consciousness_core.autonomous_tick import (  # noqa: E402
    AUTONOMOUS_COGNITION_FLAG,
    AutonomousCognitionTickAdapter,
    AutonomousCognitionTickReceipt,
)
from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
)
from app.consciousness_core.session_lifecycle import (  # noqa: E402
    ProductionCognitiveSession,
)
from app.schedule_runtime import SchedulerRuntime  # noqa: E402
from app.schedule_runner import TickResult  # noqa: E402
from app.schedule_service import SchedulerService  # noqa: E402


def tick_result() -> TickResult:
    return TickResult(
        enabled=True,
        paused=False,
        claimed=0,
        completed=0,
        blocked=0,
        failed=0,
        job_ids=(),
    )


class Runner:
    def __init__(self):
        self.calls = 0

    def feature_enabled(self):
        return True

    def disable_unschedulable(self):
        return []

    def recover_interrupted(self):
        return {"executed": [], "abandoned": [], "unknown": []}

    def run_once(self):
        self.calls += 1
        return tick_result()


class StubAdapter(AutonomousCognitionTickAdapter):
    def __init__(self, *, delay=0.0):
        self.calls = 0
        self.delay = delay
        self.thread_ids = []
        self.cancelled = False

    async def tick_once(self):
        self.calls += 1
        self.thread_ids.append(threading.get_ident())
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
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


class FakeRuntime:
    def __init__(self, events):
        self.events = events
        self.hook = None

    def set_post_tick_hook(self, hook):
        self.hook = hook
        self.events.append("hook:set" if hook is not None else "hook:clear")
        return True


class LiveSessionStub(ProductionCognitiveSession):
    def __init__(self, clock):
        self._test_clock = clock

    @property
    def closed(self):
        return False

    @property
    def trusted_clock(self):
        return self._test_clock


class HookService:
    def __init__(self):
        self.hook = None

    def set_post_tick_hook(self, hook):
        self.hook = hook


class AutonomousSchedulerTests(unittest.TestCase):
    def test_exact_scheduler_flag_contract(self):
        old = os.environ.get(AUTONOMOUS_SCHEDULER_FLAG)
        try:
            os.environ.pop(AUTONOMOUS_SCHEDULER_FLAG, None)
            self.assertFalse(autonomous_scheduler_enabled())
            for value in ("true", "on", "yes", "01", " 1 "):
                os.environ[AUTONOMOUS_SCHEDULER_FLAG] = value
                self.assertFalse(autonomous_scheduler_enabled(), value)
            os.environ[AUTONOMOUS_SCHEDULER_FLAG] = "1"
            self.assertTrue(autonomous_scheduler_enabled())
        finally:
            if old is None:
                os.environ.pop(AUTONOMOUS_SCHEDULER_FLAG, None)
            else:
                os.environ[AUTONOMOUS_SCHEDULER_FLAG] = old

    def test_scheduler_service_hook_runs_on_existing_thread(self):
        runner = Runner()
        hit = threading.Event()
        names = []

        def hook(_result):
            names.append(threading.current_thread().name)
            hit.set()

        service = SchedulerService(
            runner,
            poll_s=0.01,
            post_tick_hook=hook,
        )
        self.assertTrue(service.start())
        try:
            self.assertTrue(hit.wait(1.0))
        finally:
            self.assertTrue(service.stop(timeout=1.0))

        self.assertGreaterEqual(runner.calls, 1)
        self.assertTrue(names)
        self.assertTrue(all(name == "kaliv-scheduler" for name in names))

    def test_hook_failure_does_not_rewrite_scheduler_tick(self):
        runner = Runner()
        hit = threading.Event()

        def broken(_result):
            hit.set()
            raise RuntimeError("optional observer failure")

        service = SchedulerService(
            runner,
            poll_s=0.01,
            post_tick_hook=broken,
        )
        self.assertTrue(service.start())
        try:
            self.assertTrue(hit.wait(1.0))
        finally:
            self.assertTrue(service.stop(timeout=1.0))

        status = service.status()
        self.assertGreaterEqual(status.ticks, 1)
        self.assertEqual(status.failures, 0)

    def test_hook_can_be_replaced_and_cleared_live(self):
        runner = Runner()
        service = SchedulerService(runner, poll_s=0.01)
        self.assertTrue(service.start())
        try:
            hit = threading.Event()
            service.set_post_tick_hook(lambda _result: hit.set())
            self.assertTrue(hit.wait(1.0))
            service.set_post_tick_hook(None)
        finally:
            self.assertTrue(service.stop(timeout=1.0))

    def test_bridge_moves_cognition_back_to_owner_loop(self):
        async def scenario():
            owner_thread = threading.get_ident()
            adapter = StubAdapter()
            bridge = ScheduledAutonomousCognitionBridge(
                adapter=adapter,
                owner_loop=asyncio.get_running_loop(),
                timeout_s=1.0,
            )
            bridge.mark_installed()
            scheduler_threads = []

            def call():
                scheduler_threads.append(threading.get_ident())
                bridge.on_scheduler_tick(tick_result())

            await asyncio.to_thread(call)
            status = bridge.status()
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(adapter.thread_ids, [owner_thread])
            self.assertNotEqual(scheduler_threads[0], owner_thread)
            self.assertEqual(status.completed_count, 1)
            self.assertEqual(status.last_outcome, "IDLE")
            self.assertFalse(status.active)
            await bridge.aclose()

        asyncio.run(scenario())

    def test_timeout_cancels_without_retry(self):
        async def scenario():
            adapter = StubAdapter(delay=10.0)
            bridge = ScheduledAutonomousCognitionBridge(
                adapter=adapter,
                owner_loop=asyncio.get_running_loop(),
                timeout_s=0.02,
            )
            bridge.mark_installed()
            await asyncio.to_thread(
                bridge.on_scheduler_tick,
                tick_result(),
            )
            await asyncio.sleep(0.02)
            status = bridge.status()
            self.assertEqual(adapter.calls, 1)
            self.assertTrue(adapter.cancelled)
            self.assertEqual(status.timeout_count, 1)
            self.assertEqual(status.completed_count, 0)
            self.assertEqual(status.overlap_rejections, 0)
            await bridge.aclose()

        asyncio.run(scenario())

    def test_aclose_cancels_inflight_before_teardown(self):
        async def scenario():
            adapter = StubAdapter(delay=10.0)
            bridge = ScheduledAutonomousCognitionBridge(
                adapter=adapter,
                owner_loop=asyncio.get_running_loop(),
                timeout_s=30.0,
            )
            bridge.mark_installed()

            started = asyncio.Event()
            original = adapter.tick_once

            async def tracked_tick():
                started.set()
                return await original()

            adapter.tick_once = tracked_tick  # type: ignore[method-assign]

            thread = threading.Thread(
                target=bridge.on_scheduler_tick,
                args=(tick_result(),),
                daemon=True,
            )
            thread.start()
            await asyncio.wait_for(started.wait(), timeout=1.0)
            await bridge.aclose()
            thread.join(1.0)

            self.assertFalse(thread.is_alive())
            self.assertTrue(adapter.cancelled)
            self.assertTrue(bridge.status().closed)

        asyncio.run(scenario())

    def test_lifespan_clears_hook_before_inner_exit(self):
        async def scenario():
            events = []
            runtime = FakeRuntime(events)
            app = SimpleNamespace(state=SimpleNamespace())
            adapter = StubAdapter()
            bridge_box = {}

            @asynccontextmanager
            async def inner(inner_app):
                events.append("inner:enter")
                inner_app.state.scheduler_runtime = runtime
                inner_app.state.consciousness_session = object()
                try:
                    yield
                finally:
                    self.assertIsNone(runtime.hook)
                    self.assertTrue(bridge_box["bridge"].status().closed)
                    events.append("inner:exit")

            def factory(_app):
                bridge = ScheduledAutonomousCognitionBridge(
                    adapter=adapter,
                    owner_loop=asyncio.get_running_loop(),
                    timeout_s=1.0,
                )
                bridge_box["bridge"] = bridge
                return bridge

            composed = compose_autonomous_scheduler_lifespan(
                inner,
                bridge_factory=factory,
            )
            async with composed(app):
                events.append("outer:body")
                self.assertIsNotNone(runtime.hook)
                self.assertTrue(
                    hasattr(
                        app.state,
                        "consciousness_autonomous_scheduler",
                    )
                )

            self.assertEqual(
                events,
                [
                    "inner:enter",
                    "hook:set",
                    "outer:body",
                    "hook:clear",
                    "inner:exit",
                ],
            )

        asyncio.run(scenario())

    def test_factory_is_inert_when_scheduler_bridge_flag_is_off(self):
        class ExplodingRuntime:
            def status(self):
                raise AssertionError("flag-off touched scheduler runtime")

        app = SimpleNamespace(
            state=SimpleNamespace(
                scheduler_runtime=ExplodingRuntime(),
            )
        )
        old_sched = os.environ.get(AUTONOMOUS_SCHEDULER_FLAG)
        old_auto = os.environ.get(AUTONOMOUS_COGNITION_FLAG)
        try:
            os.environ.pop(AUTONOMOUS_SCHEDULER_FLAG, None)
            os.environ[AUTONOMOUS_COGNITION_FLAG] = "1"
            self.assertIsNone(
                production_autonomous_scheduler_bridge_factory(app)
            )
        finally:
            if old_sched is None:
                os.environ.pop(AUTONOMOUS_SCHEDULER_FLAG, None)
            else:
                os.environ[AUTONOMOUS_SCHEDULER_FLAG] = old_sched
            if old_auto is None:
                os.environ.pop(AUTONOMOUS_COGNITION_FLAG, None)
            else:
                os.environ[AUTONOMOUS_COGNITION_FLAG] = old_auto


    def test_enabled_factory_reuses_exact_c18_trusted_clock(self):
        async def scenario():
            old_sched = os.environ.get(AUTONOMOUS_SCHEDULER_FLAG)
            old_auto = os.environ.get(AUTONOMOUS_COGNITION_FLAG)
            try:
                os.environ[AUTONOMOUS_SCHEDULER_FLAG] = "1"
                os.environ[AUTONOMOUS_COGNITION_FLAG] = "1"

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
                bridge = production_autonomous_scheduler_bridge_factory(
                    app,
                    timeout_s=1.0,
                )
                self.assertIsNotNone(bridge)
                self.assertIs(bridge._adapter._clock, clock)
                await bridge.aclose()
            finally:
                if old_sched is None:
                    os.environ.pop(AUTONOMOUS_SCHEDULER_FLAG, None)
                else:
                    os.environ[AUTONOMOUS_SCHEDULER_FLAG] = old_sched
                if old_auto is None:
                    os.environ.pop(AUTONOMOUS_COGNITION_FLAG, None)
                else:
                    os.environ[AUTONOMOUS_COGNITION_FLAG] = old_auto

        asyncio.run(scenario())

    def test_scheduler_runtime_hook_registration_is_inert_when_not_started(self):
        runtime = SchedulerRuntime(enabled_fn=lambda: False)
        hit = lambda _result: None
        self.assertFalse(runtime.set_post_tick_hook(hit))

    def test_scheduler_runtime_registers_and_clears_live_service_hook(self):
        runtime = SchedulerRuntime(enabled_fn=lambda: True)
        service = HookService()
        runtime._service = service
        runtime._started = True

        def hook(_result):
            return None

        self.assertTrue(runtime.set_post_tick_hook(hook))
        self.assertIs(service.hook, hook)
        self.assertTrue(runtime.set_post_tick_hook(None))
        self.assertIsNone(service.hook)


if __name__ == "__main__":
    unittest.main()
