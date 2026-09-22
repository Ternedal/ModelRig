#!/usr/bin/env python3
"""C13-A persisted sleep boundary / lifecycle seam tests."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    SleepBinding,
    SleepLifecycleError,
    SleepLifecycleRuntime,
    SleepStateStore,
    anchor_from_clock,
    compose_sleep_lifecycle_lifespan,
)

SELF = "self-" + "1" * 32
PERSON = "person-r0007"
EPOCH_A = "epoch-" + "a" * 32
EPOCH_B = "epoch-" + "b" * 32


def sample(suffix: str, wall: int, mono: int, seq: int, epoch: str):
    return ClockSample(
        schema="kaliv-consciousness-core/clock-sample/v1",
        sample_id="clock-" + suffix * 32,
        wall_time_unix_ms=wall,
        timezone_name="Europe/Copenhagen",
        utc_offset_minutes=120,
        local_hour=10,
        monotonic_ms=mono,
        runtime_epoch_id=epoch,
        sampled_sequence=seq,
        source_ref="trusted:" + suffix,
        confidence=1.0,
        production_activation=False,
    )


def binding() -> SleepBinding:
    return SleepBinding(
        schema="kaliv-consciousness-core/sleep-binding/v1",
        self_id=SELF,
        person_revision=PERSON,
        open_goal_refs=["goal:1"],
        open_loop_refs=["loop:1"],
        pending_review_refs=["review:1"],
        production_activation=False,
    )


class SleepLifecycleTests(unittest.TestCase):
    def test_flag_off_does_not_touch_binding_clock_or_store(self) -> None:
        calls = []
        runtime = SleepLifecycleRuntime(
            enabled_fn=lambda: False,
            binding_provider=lambda: calls.append("binding"),
            anchor_provider=lambda kind: calls.append("anchor"),
            store_factory=lambda: calls.append("store"),
        )
        self.assertFalse(runtime.start())
        self.assertFalse(runtime.close())
        self.assertEqual(calls, [])

    def test_missing_authoritative_binding_never_opens_store_or_writes(self) -> None:
        calls = []
        runtime = SleepLifecycleRuntime(
            enabled_fn=lambda: True,
            binding_provider=lambda: None,
            anchor_provider=lambda kind: calls.append("anchor"),
            store_factory=lambda: calls.append("store"),
        )
        self.assertFalse(runtime.start())
        self.assertFalse(runtime.close())
        self.assertEqual(calls, [])

    def test_atomic_store_roundtrip_and_digest_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sleep.json"
            store = SleepStateStore(path)
            anchors = {
                "sleep": anchor_from_clock(
                    sample("1", 1_000, 9_000, 1, EPOCH_A),
                    event_ref="sleep",
                )
            }
            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=binding,
                anchor_provider=lambda kind: anchors[kind],
                store_factory=lambda: store,
            )
            self.assertTrue(runtime.close())
            record = store.read()
            self.assertIsNotNone(record)
            self.assertEqual(record.self_id, SELF)
            self.assertFalse(record.cognition_continues)

            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["payload"]["self_id"] = "self-" + "2" * 32
            path.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaises(SleepLifecycleError):
                store.read()

    def test_start_consumes_valid_record_into_non_authoritative_wake_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sleep.json"
            store = SleepStateStore(path)
            sleep_anchor = anchor_from_clock(
                sample("1", 1_000, 9_000, 1, EPOCH_A),
                event_ref="sleep",
            )
            writer = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=binding,
                anchor_provider=lambda kind: sleep_anchor,
                store_factory=lambda: store,
            )
            self.assertTrue(writer.close())

            wake_anchor = anchor_from_clock(
                sample("2", 61_000, 100, 2, EPOCH_B),
                event_ref="wake",
            )
            reader = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=binding,
                anchor_provider=lambda kind: wake_anchor,
                store_factory=lambda: store,
            )
            self.assertTrue(reader.start())
            wake = reader.wake_receipt
            self.assertIsNotNone(wake)
            self.assertEqual((wake.self_id, wake.person_revision), (SELF, PERSON))
            self.assertEqual(wake.offline_duration_ms, 60_000)
            self.assertFalse(wake.cognition_during_gap)
            self.assertFalse(wake.execution_authority)
            self.assertFalse(wake.scheduling_authority)
            self.assertFalse(wake.durable_memory_write_authority)

    def test_record_for_other_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SleepStateStore(Path(tmp) / "sleep.json")
            original = binding()
            sleep_anchor = anchor_from_clock(
                sample("1", 1_000, 9_000, 1, EPOCH_A), event_ref="sleep"
            )
            writer = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: original,
                anchor_provider=lambda kind: sleep_anchor,
                store_factory=lambda: store,
            )
            self.assertTrue(writer.close())

            other = original.model_copy(update={"self_id": "self-" + "2" * 32})
            wake_anchor = anchor_from_clock(
                sample("2", 2_000, 100, 2, EPOCH_B), event_ref="wake"
            )
            reader = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: other,
                anchor_provider=lambda kind: wake_anchor,
                store_factory=lambda: store,
            )
            with self.assertRaises(Exception):
                reader.start()

    def test_lifespan_wrapper_preserves_owner_and_closes_before_inner_exit(self) -> None:
        events = []

        @asynccontextmanager
        async def inner(app):
            events.append("inner:start")
            try:
                yield
            finally:
                events.append("inner:close")

        sleep_anchor = anchor_from_clock(
            sample("1", 1_000, 1_000, 1, EPOCH_A), event_ref="sleep"
        )
        runtime = SleepLifecycleRuntime(
            enabled_fn=lambda: True,
            binding_provider=binding,
            anchor_provider=lambda kind: sleep_anchor,
            store_factory=lambda: _RecordingStore(events),
        )
        wrapped = compose_sleep_lifecycle_lifespan(inner, lambda app: runtime)
        self.assertIs(wrapped.__wrapped__, inner)

        app = SimpleNamespace(state=SimpleNamespace())

        async def run():
            async with wrapped(app):
                events.append("body")

        asyncio.run(run())
        self.assertEqual(
            events,
            ["inner:start", "store:read", "body", "store:write", "inner:close"],
        )

    def test_source_has_no_scheduler_agent_memory_or_background_authority(self) -> None:
        source = (
            ROOT
            / "worker"
            / "app"
            / "consciousness_core"
            / "sleep_lifecycle.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "Agent3Orchestrator",
            "MemoryStore",
            "schedule_service",
            "SchedulerRuntime",
            "create_task(",
            "threading.Thread",
            "time.sleep(",
        ):
            self.assertNotIn(forbidden, source)


class _RecordingStore:
    def __init__(self, events):
        self.events = events

    def read(self):
        self.events.append("store:read")
        return None

    def write(self, record):
        self.events.append("store:write")


if __name__ == "__main__":
    unittest.main(verbosity=2)
