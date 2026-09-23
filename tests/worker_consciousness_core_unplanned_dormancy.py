#!/usr/bin/env python3
"""C28-C unplanned dormancy detection tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_unplanned_dormancy.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    ConsciousnessCoreRuntime,
    SelfAffect,
    SelfBootstrapAuthority,
    SleepBinding,
    SleepLifecycleError,
    SleepLifecycleRuntime,
    SleepStateStore,
    TrustedRuntimeClock,
    anchor_from_clock,
    bootstrap_self_state,
    prepare_sleep,
)
from app.consciousness_core.cycle import self_state_ref  # noqa: E402
from app.consciousness_core.session_lifecycle import (  # noqa: E402
    production_cognitive_session_factory,
)
from app.consciousness_core.supervisor_lifecycle import (  # noqa: E402
    ProductionSupervisorBridge,
)


SELF = "self-" + "a" * 32
PERSON = "person-" + "b" * 32
PERSON_REV = "person-r0007"
EPOCH_A = "epoch-" + "1" * 32
EPOCH_B = "epoch-" + "2" * 32
EPOCH_C = "epoch-" + "3" * 32


def sample(marker: str, wall: int, mono: int, seq: int, epoch: str):
    return ClockSample(
        schema="kaliv-consciousness-core/clock-sample/v1",
        sample_id="clock-" + marker * 32,
        wall_time_unix_ms=wall,
        timezone_name="Europe/Copenhagen",
        utc_offset_minutes=120,
        local_hour=10,
        monotonic_ms=mono,
        runtime_epoch_id=epoch,
        sampled_sequence=seq,
        source_ref="trusted:c28c:" + marker,
        confidence=1.0,
        production_activation=False,
    )


def deterministic_clock():
    wall = iter(
        1_700_000_000_000_000_000 + i * 1_000_000_000
        for i in range(1, 32)
    )
    mono = iter(i * 1_000_000_000 for i in range(1, 32))
    return TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )


class Engine:
    async def think(self, request, cognitive_profile, *, context=None):
        raise AssertionError("C28-C unplanned wake must not call model")


class UnplannedDormancyTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id=PERSON,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c28c",
            source_refs=["registry:test:c28c"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c28c",
            world_state_ref="world-state:c28c",
            workspace_ref="workspace:c28c",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c28c"],
            ),
        )
        return authority, state

    def binding(self, state, *, self_id=None):
        return SleepBinding(
            schema="kaliv-consciousness-core/sleep-binding/v1",
            self_id=state.self_id if self_id is None else self_id,
            person_revision=state.person_revision,
            durable_self_state_ref=self_state_ref(state),
            durable_self_state_revision=state.revision,
            open_goal_refs=[],
            open_loop_refs=[],
            pending_review_refs=[],
            production_activation=False,
        )

    def sleep_anchor(self):
        return anchor_from_clock(
            sample("1", 1_000, 9_000, 1, EPOCH_A),
            event_ref="sleep:c28c",
        )

    def first_wake_anchor(self):
        return anchor_from_clock(
            sample("2", 61_000, 100, 2, EPOCH_B),
            event_ref="wake:c28c:first",
        )

    def crash_restart_anchor(self):
        return anchor_from_clock(
            sample("3", 121_000, 200, 3, EPOCH_C),
            event_ref="wake:c28c:crash",
        )

    def acknowledged_store(self, path, state):
        store = SleepStateStore(path)
        store.write(
            prepare_sleep(
                self_id=state.self_id,
                person_revision=state.person_revision,
                entry_anchor=self.sleep_anchor(),
                reason="app_closed",
                durable_self_state_ref=self_state_ref(state),
                durable_self_state_revision=state.revision,
            )
        )
        runtime = SleepLifecycleRuntime(
            enabled_fn=lambda: True,
            binding_provider=lambda: self.binding(state),
            anchor_provider=lambda _kind: self.first_wake_anchor(),
            store_factory=lambda: store,
        )
        self.assertTrue(runtime.start())
        self.assertTrue(runtime.acknowledge_wake())
        self.assertIsNone(store.read())
        self.assertIsNotNone(store.read_acknowledgement())
        return store

    def test_ack_marker_becomes_unplanned_wake_with_unknown_duration(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            store = self.acknowledged_store(
                Path(td) / "sleep.json",
                state,
            )
            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.crash_restart_anchor(),
                store_factory=lambda: store,
            )

            self.assertTrue(runtime.start())
            wake = runtime.wake_receipt

            self.assertIsNotNone(wake)
            self.assertEqual(
                wake.dormancy_kind,
                "UNPLANNED_DORMANCY",
            )
            self.assertIsNone(wake.sleep_id)
            self.assertIsNone(wake.entry_anchor_ref)
            self.assertFalse(wake.duration_known)
            self.assertIsNone(wake.offline_duration_ms)
            self.assertEqual(wake.duration_confidence, 0.0)
            self.assertIsNone(wake.durable_self_state_ref)
            self.assertIsNone(wake.durable_self_state_revision)
            self.assertFalse(wake.cognition_during_gap)
            self.assertIsNotNone(store.read_acknowledgement())

    def test_unplanned_wake_acknowledgement_is_explicit_noop(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            store = self.acknowledged_store(
                Path(td) / "sleep.json",
                state,
            )
            marker_before = store.read_acknowledgement()
            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.crash_restart_anchor(),
                store_factory=lambda: store,
            )
            self.assertTrue(runtime.start())
            wake = runtime.wake_receipt
            self.assertIsNotNone(wake)
            self.assertIsNone(wake.sleep_id)

            self.assertFalse(runtime.acknowledge_wake(wake))
            self.assertEqual(
                store.read_acknowledgement(),
                marker_before,
            )
            self.assertIsNone(store.read())
            self.assertIsNone(runtime.wake_acknowledgement)

    def test_ack_marker_identity_mismatch_fails_closed(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            store = self.acknowledged_store(
                Path(td) / "sleep.json",
                state,
            )
            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(
                    state,
                    self_id="self-" + "f" * 32,
                ),
                anchor_provider=lambda _kind: self.crash_restart_anchor(),
                store_factory=lambda: store,
            )

            with self.assertRaisesRegex(
                SleepLifecycleError,
                "another Self/Person binding",
            ):
                runtime.start()

    def test_clean_shutdown_after_unplanned_wake_restores_planned_sleep(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            store = self.acknowledged_store(
                Path(td) / "sleep.json",
                state,
            )
            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda kind: (
                    self.crash_restart_anchor()
                    if kind == "wake"
                    else self.sleep_anchor()
                ),
                store_factory=lambda: store,
            )
            self.assertTrue(runtime.start())
            self.assertEqual(
                runtime.wake_receipt.dormancy_kind,
                "UNPLANNED_DORMANCY",
            )

            self.assertTrue(runtime.close())
            self.assertIsNotNone(store.read())
            self.assertIsNone(store.read_acknowledgement())

            next_runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.first_wake_anchor(),
                store_factory=lambda: store,
            )
            self.assertTrue(next_runtime.start())
            self.assertEqual(
                next_runtime.wake_receipt.dormancy_kind,
                "PLANNED_SLEEP",
            )

    def test_c19_accepts_unplanned_wake_without_consuming_marker(self):
        _authority, state = self.durable()

        class DurableStore:
            def read(self):
                return state

        class Registry:
            def __init__(self, _path):
                pass

            def active_bindings(self):
                return {
                    "person_id": state.person_id,
                    "person_revision": state.person_revision,
                    "body": {
                        "id": "body-r0001",
                        "source_id": "body-c28c",
                    },
                    "voice": {
                        "id": "voice-r0001",
                        "source_id": "voice-c28c",
                    },
                    "personality": {
                        "id": "personality-r0001",
                        "source_id": "personality-c28c",
                    },
                }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            person_path = root / "person.json"
            person_path.write_text("{}", encoding="utf-8")
            store = self.acknowledged_store(
                root / "sleep.json",
                state,
            )
            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.crash_restart_anchor(),
                store_factory=lambda: store,
            )
            self.assertTrue(runtime.start())
            self.assertEqual(
                runtime.wake_receipt.dormancy_kind,
                "UNPLANNED_DORMANCY",
            )

            bridge = ProductionSupervisorBridge(
                runtime=ConsciousnessCoreRuntime(Engine()),
                clock=deterministic_clock(),
            )
            app = SimpleNamespace(
                state=SimpleNamespace(
                    consciousness_supervisor=bridge,
                    consciousness_sleep_runtime=runtime,
                    consciousness_sleep_wake_receipt=runtime.wake_receipt,
                )
            )
            session = production_cognitive_session_factory(
                app,
                self_store_factory=lambda: DurableStore(),
                registry_path_fn=lambda: str(person_path),
                registry_factory=Registry,
            )

            self.assertIsNotNone(session)
            self.assertEqual(
                session.supervisor_state.pending_events[0].kind,
                "wake_followup",
            )
            self.assertIsNotNone(store.read_acknowledgement())
            self.assertIsNone(store.read())


if __name__ == "__main__":
    unittest.main()
