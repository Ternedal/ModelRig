#!/usr/bin/env python3
"""C28-A exact durable SelfState sleep/wake binding tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_sleep_self_state_binding.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ActivePersonBindingSnapshot,
    ClockSample,
    SelfAffect,
    SelfBootstrapAuthority,
    SessionBootstrapError,
    SleepBinding,
    SleepRecord,
    WakeReceipt,
    anchor_from_clock,
    bootstrap_runtime_session,
    bootstrap_self_state,
    prepare_sleep,
    wake_from_sleep,
)
from app.consciousness_core.cycle import self_state_ref  # noqa: E402
from app.consciousness_core import production_lifecycle  # noqa: E402


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
        source_ref="trusted:c28a:" + marker,
        confidence=1.0,
        production_activation=False,
    )


class SleepSelfStateBindingTests(unittest.TestCase):
    def durable(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id=SELF,
            person_id=PERSON,
            person_revision=PERSON_REV,
            authority="operator_review",
            authority_ref="operator:test:c28a",
            source_refs=["registry:test:c28a"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c28a",
            world_state_ref="world-state:c28a",
            workspace_ref="workspace:c28a",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c28a"],
            ),
        )
        return authority, state

    def person(self, state):
        return ActivePersonBindingSnapshot(
            schema="kaliv-consciousness-core/active-person-binding/v1",
            person_id=state.person_id,
            person_revision=state.person_revision,
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0001",
            body_source_ref="body:c28a",
            voice_source_ref="voice:c28a",
            registry_source_ref="registry:c28a",
            production_activation=False,
        )

    def sleep_anchor(self):
        return anchor_from_clock(
            sample("1", 1_000, 9_000, 1, EPOCH_A),
            event_ref="sleep:c28a",
        )

    def wake_anchor(self):
        return anchor_from_clock(
            sample("2", 61_000, 100, 2, EPOCH_B),
            event_ref="wake:c28a",
        )

    def test_new_sleep_record_carries_exact_state_binding_through_wake(self):
        _authority, state = self.durable()
        ref = self_state_ref(state)

        sleep = prepare_sleep(
            self_id=state.self_id,
            person_revision=state.person_revision,
            entry_anchor=self.sleep_anchor(),
            reason="app_closed",
            durable_self_state_ref=ref,
            durable_self_state_revision=state.revision,
        )
        wake = wake_from_sleep(
            wake_anchor=self.wake_anchor(),
            sleep_record=sleep,
            expected_self_id=state.self_id,
            expected_person_revision=state.person_revision,
        )

        self.assertEqual(sleep.durable_self_state_ref, ref)
        self.assertEqual(sleep.durable_self_state_revision, state.revision)
        self.assertEqual(wake.durable_self_state_ref, ref)
        self.assertEqual(wake.durable_self_state_revision, state.revision)
        self.assertFalse(wake.cognition_during_gap)

        context = bootstrap_runtime_session(
            persistent_state=state,
            active_person=self.person(state),
            bootstrap_source_ref="runtime:c28a",
            wake_receipt=wake,
        )
        self.assertEqual(
            context.receipt.bootstrap_kind,
            "WAKE_REORIENTATION",
        )
        self.assertEqual(
            context.receipt.self_revision_before,
            state.revision,
        )

    def test_legacy_v1_without_state_binding_remains_readable(self):
        sleep = prepare_sleep(
            self_id=SELF,
            person_revision=PERSON_REV,
            entry_anchor=self.sleep_anchor(),
            reason="host_shutdown",
        )
        payload = sleep.model_dump(mode="json", exclude_none=True)
        payload.pop("durable_self_state_ref", None)
        payload.pop("durable_self_state_revision", None)

        legacy = SleepRecord.model_validate(payload)
        wake = wake_from_sleep(
            wake_anchor=self.wake_anchor(),
            sleep_record=legacy,
            expected_self_id=SELF,
            expected_person_revision=PERSON_REV,
        )

        self.assertIsNone(legacy.durable_self_state_ref)
        self.assertIsNone(legacy.durable_self_state_revision)
        self.assertIsNone(wake.durable_self_state_ref)
        self.assertIsNone(wake.durable_self_state_revision)

    def test_partial_bindings_fail_validation(self):
        base = {
            "schema": "kaliv-consciousness-core/sleep-binding/v1",
            "self_id": SELF,
            "person_revision": PERSON_REV,
            "open_goal_refs": [],
            "open_loop_refs": [],
            "pending_review_refs": [],
            "production_activation": False,
        }
        with self.assertRaises(ValueError):
            SleepBinding.model_validate(
                {
                    **base,
                    "durable_self_state_ref": "self-state:" + "1" * 64,
                }
            )

        _authority, state = self.durable()
        sleep = prepare_sleep(
            self_id=SELF,
            person_revision=PERSON_REV,
            entry_anchor=self.sleep_anchor(),
            reason="app_closed",
            durable_self_state_ref=self_state_ref(state),
            durable_self_state_revision=state.revision,
        )
        wake_payload = wake_from_sleep(
            wake_anchor=self.wake_anchor(),
            sleep_record=sleep,
        ).model_dump(mode="json")
        wake_payload["durable_self_state_revision"] = None
        with self.assertRaises(ValueError):
            WakeReceipt.model_validate(wake_payload)

    def test_bootstrap_rejects_sleep_revision_mismatch(self):
        _authority, state = self.durable()
        sleep = prepare_sleep(
            self_id=SELF,
            person_revision=PERSON_REV,
            entry_anchor=self.sleep_anchor(),
            reason="app_closed",
            durable_self_state_ref=self_state_ref(state),
            durable_self_state_revision=state.revision + 1,
        )
        wake = wake_from_sleep(
            wake_anchor=self.wake_anchor(),
            sleep_record=sleep,
        )

        with self.assertRaisesRegex(
            SessionBootstrapError,
            "revision does not match current state",
        ):
            bootstrap_runtime_session(
                persistent_state=state,
                active_person=self.person(state),
                bootstrap_source_ref="runtime:c28a:mismatch-revision",
                wake_receipt=wake,
            )

    def test_bootstrap_rejects_sleep_ref_mismatch(self):
        _authority, state = self.durable()
        sleep = prepare_sleep(
            self_id=SELF,
            person_revision=PERSON_REV,
            entry_anchor=self.sleep_anchor(),
            reason="app_closed",
            durable_self_state_ref="self-state:" + "f" * 64,
            durable_self_state_revision=state.revision,
        )
        wake = wake_from_sleep(
            wake_anchor=self.wake_anchor(),
            sleep_record=sleep,
        )

        with self.assertRaisesRegex(
            SessionBootstrapError,
            "ref does not match current state",
        ):
            bootstrap_runtime_session(
                persistent_state=state,
                active_person=self.person(state),
                bootstrap_source_ref="runtime:c28a:mismatch-ref",
                wake_receipt=wake,
            )

    def test_authoritative_sleep_binding_uses_exact_c14_state(self):
        _authority, state = self.durable()

        class Store:
            def read(self):
                return state

        class Registry:
            def __init__(self, _path):
                pass

            def active_bindings(self):
                return {
                    "person_id": state.person_id,
                    "person_revision": state.person_revision,
                }

        with tempfile.TemporaryDirectory() as td:
            registry = Path(td) / "person.json"
            registry.write_text("{}", encoding="utf-8")
            with (
                patch.object(
                    production_lifecycle,
                    "SelfStateStore",
                    return_value=Store(),
                ),
                patch.object(
                    production_lifecycle,
                    "registry_path",
                    return_value=str(registry),
                ),
                patch.object(
                    production_lifecycle,
                    "PersonRegistry",
                    Registry,
                ),
            ):
                binding = (
                    production_lifecycle.authoritative_sleep_binding()
                )

        self.assertIsNotNone(binding)
        self.assertEqual(
            binding.durable_self_state_ref,
            self_state_ref(state),
        )
        self.assertEqual(
            binding.durable_self_state_revision,
            state.revision,
        )


if __name__ == "__main__":
    unittest.main()
