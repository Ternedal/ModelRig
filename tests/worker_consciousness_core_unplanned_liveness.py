#!/usr/bin/env python3
"""C29-D liveness-bounded unplanned dormancy tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_unplanned_liveness.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    RuntimeLivenessStore,
    SelfAffect,
    SelfBootstrapAuthority,
    SleepBinding,
    SleepLifecycleError,
    SleepLifecycleRuntime,
    SleepStateStore,
    UNPLANNED_LIVENESS_FLAG,
    anchor_from_clock,
    bootstrap_self_state,
    build_runtime_liveness_witness,
    prepare_sleep,
    unplanned_liveness_enabled,
)
from app.consciousness_core.cycle import self_state_ref  # noqa: E402


SELF = "self-" + "a" * 32
PERSON_REV = "person-r0007"
EPOCH_SLEEP = "epoch-" + "1" * 32
EPOCH_AWAKE = "epoch-" + "2" * 32
EPOCH_RESTART = "epoch-" + "3" * 32


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
        source_ref="trusted:c29d:" + marker,
        confidence=1.0,
        production_activation=False,
    )


def anchor(marker: str, wall: int, mono: int, seq: int, epoch: str):
    return anchor_from_clock(
        sample(marker, wall, mono, seq, epoch),
        event_ref="c29d:" + marker,
    )


class CountingLivenessStore(RuntimeLivenessStore):
    def __init__(self, path):
        super().__init__(path)
        self.read_calls = 0

    def read(self):
        self.read_calls += 1
        return super().read()


class UnplannedLivenessTests(unittest.TestCase):
    def setUp(self):
        self._old_flag = os.environ.get(UNPLANNED_LIVENESS_FLAG)

    def tearDown(self):
        if self._old_flag is None:
            os.environ.pop(UNPLANNED_LIVENESS_FLAG, None)
        else:
            os.environ[UNPLANNED_LIVENESS_FLAG] = self._old_flag

    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id="person-" + "b" * 32,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c29d",
            source_refs=["registry:test:c29d"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c29d",
            world_state_ref="world-state:c29d",
            workspace_ref="workspace:c29d",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c29d"],
            ),
        )
        return authority, state

    def binding(self, state):
        return SleepBinding(
            schema="kaliv-consciousness-core/sleep-binding/v1",
            self_id=state.self_id,
            person_revision=state.person_revision,
            durable_self_state_ref=self_state_ref(state),
            durable_self_state_revision=state.revision,
            open_goal_refs=[],
            open_loop_refs=[],
            pending_review_refs=[],
            production_activation=False,
        )

    def acknowledged_store(self, path, state):
        store = SleepStateStore(path)
        sleep_anchor = anchor(
            "1", 1_000, 9_000, 1, EPOCH_SLEEP
        )
        first_wake = anchor(
            "2", 61_000, 100, 2, EPOCH_AWAKE
        )
        store.write(
            prepare_sleep(
                self_id=state.self_id,
                person_revision=state.person_revision,
                entry_anchor=sleep_anchor,
                reason="app_closed",
                durable_self_state_ref=self_state_ref(state),
                durable_self_state_revision=state.revision,
            )
        )
        runtime = SleepLifecycleRuntime(
            enabled_fn=lambda: True,
            binding_provider=lambda: self.binding(state),
            anchor_provider=lambda _kind: first_wake,
            store_factory=lambda: store,
            unplanned_liveness_enabled_fn=lambda: False,
        )
        self.assertTrue(runtime.start())
        self.assertTrue(runtime.acknowledge_wake())
        return store

    def witness(self, state, *, wall=111_000, marker="4"):
        return build_runtime_liveness_witness(
            state=state,
            anchor=anchor(
                marker,
                wall,
                50_000,
                8,
                EPOCH_AWAKE,
            ),
            source_ref="self-state-checkpoint-receipt:" + "c" * 64,
        )

    def restart_anchor(self, *, wall=121_000):
        return anchor(
            "3", wall, 200, 1, EPOCH_RESTART
        )

    def test_exact_flag_contract(self):
        os.environ.pop(UNPLANNED_LIVENESS_FLAG, None)
        self.assertFalse(unplanned_liveness_enabled())
        for value in ("0", "true", "yes", "on", "01", " 1 "):
            os.environ[UNPLANNED_LIVENESS_FLAG] = value
            self.assertFalse(unplanned_liveness_enabled(), value)
        os.environ[UNPLANNED_LIVENESS_FLAG] = "1"
        self.assertTrue(unplanned_liveness_enabled())

    def test_planned_sleep_never_checks_c29d_or_liveness_store(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SleepStateStore(root / "sleep.json")
            store.write(
                prepare_sleep(
                    self_id=state.self_id,
                    person_revision=state.person_revision,
                    entry_anchor=anchor(
                        "1", 1_000, 9_000, 1, EPOCH_SLEEP
                    ),
                    reason="app_closed",
                    durable_self_state_ref=self_state_ref(state),
                    durable_self_state_revision=state.revision,
                )
            )

            def explode_flag():
                raise AssertionError("planned wake checked C29-D gate")

            def explode_store():
                raise AssertionError("planned wake built liveness store")

            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: anchor(
                    "2", 61_000, 100, 2, EPOCH_AWAKE
                ),
                store_factory=lambda: store,
                unplanned_liveness_enabled_fn=explode_flag,
                liveness_store_factory=explode_store,
            )

            self.assertTrue(runtime.start())
            self.assertEqual(
                runtime.wake_receipt.dormancy_kind,
                "PLANNED_SLEEP",
            )

    def test_gate_off_preserves_c28c_without_liveness_io(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self.acknowledged_store(
                root / "sleep.json",
                state,
            )

            def explode_store():
                raise AssertionError("gate-off built liveness store")

            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.restart_anchor(),
                store_factory=lambda: store,
                unplanned_liveness_enabled_fn=lambda: False,
                liveness_store_factory=explode_store,
            )

            self.assertTrue(runtime.start())
            wake = runtime.wake_receipt
            self.assertEqual(
                wake.dormancy_kind,
                "UNPLANNED_DORMANCY",
            )
            self.assertIsNone(wake.last_known_alive_witness_ref)
            self.assertIsNone(wake.last_known_alive_anchor_ref)
            self.assertIsNone(wake.offline_duration_upper_bound_ms)
            self.assertEqual(
                wake.offline_duration_upper_bound_confidence,
                0.0,
            )
            self.assertFalse(wake.duration_known)
            self.assertIsNone(wake.offline_duration_ms)

    def test_last_known_alive_yields_upper_bound_not_exact_duration(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sleep_store = self.acknowledged_store(
                root / "sleep.json",
                state,
            )
            liveness_store = CountingLivenessStore(
                root / "liveness.json"
            )
            witness = self.witness(state)
            liveness_store.write_next(witness)
            liveness_store.read_calls = 0

            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.restart_anchor(),
                store_factory=lambda: sleep_store,
                unplanned_liveness_enabled_fn=lambda: True,
                liveness_store_factory=lambda: liveness_store,
            )

            self.assertTrue(runtime.start())
            wake = runtime.wake_receipt
            self.assertEqual(liveness_store.read_calls, 1)
            self.assertEqual(
                wake.dormancy_kind,
                "UNPLANNED_DORMANCY",
            )
            self.assertFalse(wake.duration_known)
            self.assertIsNone(wake.offline_duration_ms)
            self.assertEqual(wake.duration_confidence, 0.0)
            self.assertEqual(
                wake.offline_duration_upper_bound_ms,
                10_000,
            )
            self.assertEqual(
                wake.offline_duration_upper_bound_confidence,
                1.0,
            )
            self.assertIsNotNone(wake.last_known_alive_witness_ref)
            self.assertEqual(
                wake.last_known_alive_anchor_ref,
                "temporal-anchor:" + witness.anchor.anchor_id,
            )
            self.assertIsNone(wake.entry_anchor_ref)
            self.assertFalse(wake.cognition_during_gap)

    def test_wall_clock_rollback_keeps_only_last_alive_evidence(self):
        _authority, state = self.durable()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sleep_store = self.acknowledged_store(
                root / "sleep.json",
                state,
            )
            liveness_store = RuntimeLivenessStore(
                root / "liveness.json"
            )
            witness = self.witness(state, wall=130_000)
            liveness_store.write_next(witness)

            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.restart_anchor(
                    wall=121_000
                ),
                store_factory=lambda: sleep_store,
                unplanned_liveness_enabled_fn=lambda: True,
                liveness_store_factory=lambda: liveness_store,
            )

            self.assertTrue(runtime.start())
            wake = runtime.wake_receipt
            self.assertIsNotNone(wake.last_known_alive_witness_ref)
            self.assertIsNone(wake.offline_duration_upper_bound_ms)
            self.assertEqual(
                wake.offline_duration_upper_bound_confidence,
                0.0,
            )
            self.assertFalse(wake.duration_known)
            self.assertIsNone(wake.offline_duration_ms)

    def test_foreign_identity_liveness_fails_closed(self):
        _authority, state = self.durable()
        foreign_authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "f" * 32,
            person_id="person-" + "e" * 32,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c29d:foreign",
            source_refs=["registry:test:c29d:foreign"],
            production_activation=False,
        )
        foreign = bootstrap_self_state(
            foreign_authority,
            personality_state_ref="personality-state:foreign",
            world_state_ref="world-state:foreign",
            workspace_ref="workspace:foreign",
            affect=state.affect,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sleep_store = self.acknowledged_store(
                root / "sleep.json",
                state,
            )
            liveness_store = RuntimeLivenessStore(
                root / "liveness.json"
            )
            liveness_store.write_next(self.witness(foreign))

            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.restart_anchor(),
                store_factory=lambda: sleep_store,
                unplanned_liveness_enabled_fn=lambda: True,
                liveness_store_factory=lambda: liveness_store,
            )

            with self.assertRaisesRegex(
                SleepLifecycleError,
                "another Self/Person binding",
            ):
                runtime.start()

    def test_same_revision_conflicting_state_ref_fails_closed(self):
        _authority, state = self.durable()
        conflict = state.model_copy(
            update={"workspace_ref": "workspace:conflicting"}
        )
        self.assertEqual(conflict.revision, state.revision)
        self.assertNotEqual(
            self_state_ref(conflict),
            self_state_ref(state),
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sleep_store = self.acknowledged_store(
                root / "sleep.json",
                state,
            )
            liveness_store = RuntimeLivenessStore(
                root / "liveness.json"
            )
            liveness_store.write_next(self.witness(conflict))

            runtime = SleepLifecycleRuntime(
                enabled_fn=lambda: True,
                binding_provider=lambda: self.binding(state),
                anchor_provider=lambda _kind: self.restart_anchor(),
                store_factory=lambda: sleep_store,
                unplanned_liveness_enabled_fn=lambda: True,
                liveness_store_factory=lambda: liveness_store,
            )

            with self.assertRaisesRegex(
                SleepLifecycleError,
                "conflicts with authoritative durable SelfState",
            ):
                runtime.start()


if __name__ == "__main__":
    unittest.main()
