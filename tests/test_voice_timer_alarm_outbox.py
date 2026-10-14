"""SQLite tests for inert durable alarm outbox; no alarms are delivered."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_timer_alarm_outbox import TimerAlarmOutbox
from app.voice_timer_state_ledger import TimerStateLedger


class TimerAlarmOutboxTests(unittest.TestCase):
    def test_lease_expiry_and_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = TimerAlarmOutbox(os.path.join(tmp, "outbox.db"))
            with TimerStateLedger(outbox.path) as ledger:
                ledger.register_pending("a")
                self.assertFalse(outbox.enqueue_due("a"))
                # Test fixture represents a trusted executor that has recorded
                # the due transition; no activation API is exposed by the outbox.
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='due' WHERE timer_id='a'"
                )
                ledger.db.commit()
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

    def test_rejects_undue_and_unknown_timer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "outbox.db")
            outbox = TimerAlarmOutbox(path)
            with TimerStateLedger(path) as ledger:
                ledger.register_pending("pending")
                self.assertFalse(outbox.enqueue_due("pending"))
                self.assertFalse(outbox.enqueue_due("unknown"))
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='cancelled' "
                    "WHERE timer_id='pending'"
                )
                ledger.db.commit()
                self.assertFalse(outbox.enqueue_due("pending"))
            self.assertIsNone(outbox.status("pending"))

    def test_cancelled_due_timer_cannot_be_claimed_or_acknowledged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "outbox.db")
            outbox = TimerAlarmOutbox(path)
            with TimerStateLedger(path) as ledger:
                ledger.register_pending("cancelled-before-claim")
                ledger.register_pending("cancelled-after-claim")
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='due' "
                    "WHERE timer_id IN ('cancelled-before-claim','cancelled-after-claim')"
                )
                ledger.db.commit()
                self.assertTrue(outbox.enqueue_due("cancelled-before-claim"))
                self.assertTrue(outbox.enqueue_due("cancelled-after-claim"))
                claim = outbox.claim("cancelled-after-claim", now=100)
                self.assertIsNotNone(claim)
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='cancelled' "
                    "WHERE timer_id IN ('cancelled-before-claim','cancelled-after-claim')"
                )
                ledger.db.commit()
            self.assertIsNone(outbox.claim("cancelled-before-claim", now=101))
            self.assertFalse(outbox.acknowledge(claim, now=101))
            self.assertEqual(outbox.status("cancelled-before-claim"), "queued")
            self.assertEqual(outbox.status("cancelled-after-claim"), "leased")

    def test_fresh_outbox_has_empty_ledger_and_denies_unknown_alarm(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = TimerAlarmOutbox(os.path.join(tmp, "fresh.sqlite"))
            self.assertFalse(outbox.enqueue_due("unknown"))
            self.assertIsNone(outbox.claim("unknown", now=100))
            with TimerStateLedger(outbox.path) as ledger:
                self.assertIsNone(ledger.get("unknown"))

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
