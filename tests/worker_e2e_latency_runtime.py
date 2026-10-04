#!/usr/bin/env python3
"""Qualification-only end-to-end latency runtime receipt tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.production_lifecycle import TrustedRuntimeClock  # noqa: E402
from app.e2e_latency_runtime import EndToEndLatencyObserver  # noqa: E402


class EndToEndLatencyRuntimeTests(unittest.TestCase):
    def observer(self):
        wall = iter((1_700_000_000_000_000_000, 1_700_000_001_000_000_000))
        mono = iter((10_000_000_000, 12_000_000_000))
        clock = TrustedRuntimeClock(
            wall_time_ns=lambda: next(wall),
            monotonic_ns=lambda: next(mono),
        )
        return EndToEndLatencyObserver(
            candidate_git_sha="a" * 40,
            event_id="cevt-" + "b" * 32,
            observer_id="observer-e2e-test",
            clock=clock,
        )

    def test_perception_and_cognition_share_exact_observer_epoch_and_event(self):
        observer = self.observer()
        perception = observer.perception_received(
            input_kind="voice-asr",
            input_id="voice-turn-1",
        )
        cognition = observer.cognition_completed(
            transition_receipt_ref="transition:test:1",
            completed_cycles=4,
        )

        self.assertEqual(perception["schema"], "kaliv-system/end-to-end-latency-source/v1")
        self.assertEqual(cognition["schema"], perception["schema"])
        self.assertEqual(perception["event_id"], cognition["event_id"])
        self.assertEqual(perception["runtime_epoch"], cognition["runtime_epoch"])
        self.assertEqual(perception["observer_id"], cognition["observer_id"])
        self.assertLessEqual(perception["observed_at_ms"], cognition["observed_at_ms"])
        self.assertEqual(perception["phase"], "perception_received")
        self.assertEqual(cognition["phase"], "cognition_completed")
        self.assertEqual(
            cognition["details"]["cognition_event_id"],
            perception["event_id"],
        )
        for receipt in (perception, cognition):
            self.assertIs(receipt["real_event"], True)
            self.assertIs(receipt["simulated"], False)
            self.assertIs(receipt["replay"], False)
            self.assertIs(receipt["production_activation"], False)
            self.assertEqual(
                receipt["clock"],
                {
                    "kind": "monotonic",
                    "unit": "milliseconds",
                    "origin": "single-observer",
                },
            )

    def test_outward_binding_carries_same_worker_owned_identity(self):
        observer = self.observer()
        binding = observer.outward_binding()
        self.assertEqual(binding["candidate_git_sha"], "a" * 40)
        self.assertEqual(binding["cognition_event_id"], "cevt-" + "b" * 32)
        self.assertEqual(binding["runtime_epoch"], observer.clock.runtime_epoch_id)
        self.assertEqual(binding["observer_id"], "observer-e2e-test")

    def test_invalid_identity_and_fake_cycle_claims_fail_closed(self):
        with self.assertRaises(ValueError):
            EndToEndLatencyObserver(
                candidate_git_sha="bad",
                event_id="cevt-" + "b" * 32,
                observer_id="observer-e2e-test",
                clock=TrustedRuntimeClock(),
            )
        observer = self.observer()
        with self.assertRaises(ValueError):
            observer.cognition_completed(
                transition_receipt_ref="",
                completed_cycles=1,
            )
        with self.assertRaises(ValueError):
            observer.cognition_completed(
                transition_receipt_ref="transition:test:1",
                completed_cycles=0,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
