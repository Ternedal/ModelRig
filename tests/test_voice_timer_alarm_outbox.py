"""SQLite tests for inert durable alarm outbox; no alarms are delivered."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_timer_alarm_outbox import TimerAlarmOutbox


class TimerAlarmOutboxTests(unittest.TestCase):
    def test_lease_expiry_and_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = TimerAlarmOutbox(os.path.join(tmp, "outbox.db"))
            self.assertTrue(outbox.enqueue_due("a"))
            self.assertFalse(outbox.enqueue_due("a"))
            first = outbox.claim("a", now=100, lease_seconds=30)
            self.assertEqual(first.attempts, 1)
            self.assertIsNone(outbox.claim("a", now=129))
            self.assertFalse(outbox.acknowledge(first, now=130))
            second = outbox.claim("a", now=130)
            self.assertEqual(second.attempts, 2)
            self.assertNotEqual(first.delivery_token, second.delivery_token)
            self.assertFalse(outbox.acknowledge(first, now=131))
            self.assertTrue(outbox.acknowledge(second, now=131))
            self.assertFalse(outbox.acknowledge(second, now=132))
            self.assertIsNone(outbox.claim("a", now=200))
            self.assertEqual(outbox.status("a"), "delivered")

    def test_missing_and_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = TimerAlarmOutbox(os.path.join(tmp, "outbox.db"))
            self.assertIsNone(outbox.claim("unknown", now=1))
            self.assertIsNone(outbox.status("unknown"))
            for bad in ("", None, 5):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    outbox.enqueue_due(bad)
            for lease in (0, 301, True, 1.5):
                with self.subTest(lease=lease), self.assertRaises(ValueError):
                    outbox.claim("a", now=1, lease_seconds=lease)


if __name__ == "__main__":
    unittest.main()
