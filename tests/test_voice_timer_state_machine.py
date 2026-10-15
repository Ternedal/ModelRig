"""Unit tests of inert one-shot timer lifecycle."""
import os
import sys
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_timer_state_machine import TimerState, activate, mark_due, delivered, cancel


class OneShotTimerStateMachineTests(unittest.TestCase):
    def test_happy_path_is_pure(self):
        active = activate(TimerState.PENDING, authorized=True, persisted=True,
                          delivery_channel_ready=True, confirmed_at=100, duration_seconds=5)
        self.assertEqual(active.state, TimerState.ACTIVE)
        self.assertEqual(active.due_at, 105)
        with self.assertRaises(ValueError):
            mark_due(active.state, due_at=105, now=104)
        due = mark_due(active.state, due_at=105, now=105)
        self.assertEqual(due.state, TimerState.DUE)
        with self.assertRaises(ValueError):
            delivered(due.state, transport_acknowledged=False)
        self.assertEqual(delivered(due.state, transport_acknowledged=True).state, TimerState.DELIVERED)

    def test_no_activation_without_every_prerequisite(self):
        for authorized, persisted, ready in ((False, True, True), (True, False, True), (True, True, False)):
            with self.subTest(flags=(authorized, persisted, ready)):
                with self.assertRaises(PermissionError):
                    activate(TimerState.PENDING, authorized=authorized, persisted=persisted,
                             delivery_channel_ready=ready, confirmed_at=100, duration_seconds=5)

    def test_rejects_invalid_transitions(self):
        with self.assertRaises(ValueError):
            activate(TimerState.CANCELLED, authorized=True, persisted=True,
                     delivery_channel_ready=True, confirmed_at=100, duration_seconds=5)
        for duration in (0, 3601, True, 1.5):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                activate(TimerState.PENDING, authorized=True, persisted=True,
                         delivery_channel_ready=True, confirmed_at=100, duration_seconds=duration)
        self.assertEqual(cancel(TimerState.ACTIVE).state, TimerState.CANCELLED)
        with self.assertRaises(ValueError):
            cancel(TimerState.DELIVERED)


if __name__ == "__main__":
    unittest.main()
