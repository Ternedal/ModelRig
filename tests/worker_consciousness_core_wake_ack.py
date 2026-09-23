#!/usr/bin/env python3
"""C28-B single-use planned sleep wake acknowledgement tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_wake_ack.py
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
    SleepWakeAcknowledgement,
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
        source_ref="trusted:c28b:" + marker,
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
        raise AssertionError("C28-B wake acknowledgement must not call model")


class WakeAckTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id=PERSON,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c28b",
            source_refs=["registry:test:c28b"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c28b",
            world_state_ref="world-state:c28b",
            workspace_ref="workspace:c28b",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c28b"],
            ),
        )
        return authority, state

    def sleep_anchor(self):
        return anchor_from_clock(
            sample("1", 1_000, 9_000, 1, EPOCH_A),
            event_ref="sleep:c28b",
        )

    def wake_anchor(self):
        return anchor_from_clock(
            sample("2", 61_000, 100, 2, EPOCH_B),
            event_ref="wake:c28b",
        )

    def binding(self, state):
        return SleepBinding(
            schema="kaliv-consciousness-core/sleep-binding/v1",
            self_id=state.self_id,
            person_revision=state.person_revision,
            durable_self_state_ref=self_state_ref(state),
            durable_self_state_revision=state.revision,
            open_goal_refs=list(state.active_goal_refs),
            open_loop_refs=list(state.active_intention_refs),
            pending_review_refs=[],
            production_activation=False,
        )

    def pending_store(self, path, state):
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
        return store

    def test_store_acknowledgement_consumes_planned_sleep_once(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            store = self.pending_store(Path(td) / "sleep.json", state)
            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.wake_anchor(),
                store_factory=lambda: store,
            )
            self.assertTrue(runtime.start())
            wake = runtime.wake_receipt
            self.assertIsNotNone(wake)

            self.assertTrue(runtime.acknowledge_wake(wake))
            ack = store.read_acknowledgement()

            self.assertIsInstance(ack, SleepWakeAcknowledgement)
            self.assertEqual(ack.sleep_id, wake.sleep_id)
            self.assertEqual(ack.wake_id, wake.wake_id)
            self.assertEqual(
                ack.durable_self_state_ref,
                self_state_ref(state),
            )
            self.assertEqual(
                ack.durable_self_state_revision,
                state.revision,
            )
            self.assertTrue(ack.planned_sleep_consumed)
            self.assertIsNone(store.read())

            # Exact duplicate acknowledgement is idempotent.
            self.assertTrue(runtime.acknowledge_wake(wake))
            self.assertEqual(store.read_acknowledgement(), ack)

    def test_conflicting_wake_cannot_replace_acknowledgement(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            store = self.pending_store(Path(td) / "sleep.json", state)
            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.wake_anchor(),
                store_factory=lambda: store,
            )
            self.assertTrue(runtime.start())
            wake = runtime.wake_receipt
            self.assertIsNotNone(wake)
            self.assertTrue(runtime.acknowledge_wake(wake))
            ack_before = store.read_acknowledgement()

            forged = wake.model_copy(
                update={"wake_id": "wake-" + "f" * 32}
            )
            with self.assertRaises(SleepLifecycleError):
                store.acknowledge_wake(forged)
            self.assertEqual(
                store.read_acknowledgement(),
                ack_before,
            )

    def test_runtime_rejects_wake_other_than_its_own(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            store = self.pending_store(Path(td) / "sleep.json", state)
            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.wake_anchor(),
                store_factory=lambda: store,
            )
            self.assertTrue(runtime.start())
            wake = runtime.wake_receipt
            self.assertIsNotNone(wake)
            forged = wake.model_copy(
                update={"wake_id": "wake-" + "f" * 32}
            )

            with self.assertRaisesRegex(
                SleepLifecycleError,
                "does not match this sleep runtime",
            ):
                runtime.acknowledge_wake(forged)

            self.assertIsNotNone(store.read())
            self.assertIsNone(store.read_acknowledgement())
            self.assertIsNone(runtime.wake_acknowledgement)

    def test_ack_marker_is_not_replayed_as_planned_sleep(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            store = self.pending_store(Path(td) / "sleep.json", state)
            first = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.wake_anchor(),
                store_factory=lambda: store,
            )
            self.assertTrue(first.start())
            self.assertTrue(first.acknowledge_wake())

            second = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.wake_anchor(),
                store_factory=lambda: store,
            )
            self.assertTrue(second.start())
            self.assertIsNone(second.wake_receipt)
            self.assertIsNotNone(store.read_acknowledgement())

    def test_clean_shutdown_overwrites_ack_marker_with_new_sleep(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            store = self.pending_store(Path(td) / "sleep.json", state)
            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda kind: (
                    self.wake_anchor()
                    if kind == "wake"
                    else self.sleep_anchor()
                ),
                store_factory=lambda: store,
            )
            self.assertTrue(runtime.start())
            self.assertTrue(runtime.acknowledge_wake())
            self.assertIsNone(store.read())

            self.assertTrue(runtime.close())
            next_sleep = store.read()
            self.assertIsNotNone(next_sleep)
            self.assertIsNone(store.read_acknowledgement())
            self.assertEqual(next_sleep.self_id, state.self_id)

    def test_production_session_acknowledges_only_after_bootstrap(self):
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
                        "source_id": "body-c28b",
                    },
                    "voice": {
                        "id": "voice-r0001",
                        "source_id": "voice-c28b",
                    },
                    "personality": {
                        "id": "personality-r0001",
                        "source_id": "personality-c28b",
                    },
                }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            person_path = root / "person.json"
            person_path.write_text("{}", encoding="utf-8")
            sleep_store = self.pending_store(
                root / "sleep.json",
                state,
            )
            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.wake_anchor(),
                store_factory=lambda: sleep_store,
            )
            self.assertTrue(runtime.start())
            self.assertIsNotNone(runtime.wake_receipt)
            self.assertIsNotNone(sleep_store.read())

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
            self.assertTrue(session.supervisor_state.pending_events)
            self.assertEqual(
                session.supervisor_state.pending_events[0].kind,
                "wake_followup",
            )
            self.assertIsNone(sleep_store.read())
            ack = sleep_store.read_acknowledgement()
            self.assertIsNotNone(ack)
            self.assertEqual(
                ack.wake_id,
                runtime.wake_receipt.wake_id,
            )


if __name__ == "__main__":
    unittest.main()
