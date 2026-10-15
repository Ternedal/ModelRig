"""Tests for inert, restart-safe timer due-time promotion."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_timer_due_sweeper import TimerDueSweeper
from app.voice_timer_state_ledger import TimerStateLedger
from app.voice_timer_alarm_outbox import TimerAlarmOutbox


class TimerDueSweeperTests(unittest.TestCase):
    def test_deadline_restart_and_idempotent_enqueue(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timer.db")
            sweeper = TimerDueSweeper(path)
            with TimerStateLedger(path) as ledger:
                ledger.register_pending("t1")
                self.assertFalse(sweeper.register_active_deadline("t1", due_at=130))
                # Simulated state from a FUTURE authenticated activation service.
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='active' WHERE timer_id='t1'"
                )
                ledger.db.commit()
            self.assertTrue(sweeper.register_active_deadline("t1", due_at=130))
            self.assertFalse(sweeper.register_active_deadline("t1", due_at=130))
            with self.assertRaisesRegex(ValueError, "conflicting active timer deadline"):
                sweeper.register_active_deadline("t1", due_at=99)
            restarted = TimerDueSweeper(path)
            self.assertEqual(restarted.sweep_due(now=129), 0)
            self.assertEqual(restarted.sweep_due(now=130), 1)
            self.assertEqual(restarted.sweep_due(now=131), 0)
            with TimerStateLedger(path) as ledger:
                rec = ledger.get("t1")
                self.assertEqual((rec.state, rec.revision), ("due", 1))
            outbox = TimerAlarmOutbox(path)
            self.assertEqual(outbox.status("t1"), "queued")
            self.assertFalse(outbox.enqueue_due("t1"))
            # Promotion transfers ownership to the durable outbox and must
            # release the no-longer-needed deadline, including after restart.
            import sqlite3
            with sqlite3.connect(path) as db:
                self.assertIsNone(db.execute(
                    "SELECT due_at FROM voice_timer_deadlines WHERE timer_id='t1'"
                ).fetchone())
            self.assertEqual(TimerDueSweeper(path).sweep_due(now=200), 0)

    def test_cancelled_timer_never_due(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timer.db")
            sweeper = TimerDueSweeper(path)
            with TimerStateLedger(path) as ledger:
                ledger.register_pending("t2")
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='active' WHERE timer_id='t2'"
                )
                ledger.db.commit()
            self.assertTrue(sweeper.register_active_deadline("t2", due_at=100))
            with TimerStateLedger(path) as ledger:
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='cancelled' WHERE timer_id='t2'"
                )
                ledger.db.commit()
            self.assertEqual(sweeper.sweep_due(now=200), 0)
            self.assertIsNone(TimerAlarmOutbox(path).status("t2"))

    def test_conflicting_alarm_rolls_back_due_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timer.db")
            sweeper = TimerDueSweeper(path)
            with TimerStateLedger(path) as ledger:
                ledger.register_pending("t3")
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='active' WHERE timer_id='t3'"
                )
                ledger.db.commit()
            self.assertTrue(sweeper.register_active_deadline("t3", due_at=100))
            # Corrupted pre-existing delivery: sweeper must not overwrite it.
            import sqlite3
            with sqlite3.connect(path) as db:
                db.execute(
                    "INSERT INTO voice_timer_alarm_outbox (timer_id,status) "
                    "VALUES ('t3','delivered')"
                )
            with self.assertRaisesRegex(ValueError, "already has alarm"):
                sweeper.sweep_due(now=100)
            with TimerStateLedger(path) as ledger:
                self.assertEqual((ledger.get("t3").state, ledger.get("t3").revision), ("active", 0))
            self.assertEqual(TimerAlarmOutbox(path).status("t3"), "delivered")
            # A failed promotion must not lose the deadline needed for retry.
            import sqlite3
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute(
                    "SELECT due_at FROM voice_timer_deadlines WHERE timer_id='t3'"
                ).fetchone()[0], 100)

    def test_existing_outbox_rolls_back_due_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timer.db")
            sweeper = TimerDueSweeper(path)
            with TimerStateLedger(path) as ledger:
                ledger.register_pending("conflict")
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='active' WHERE timer_id='conflict'"
                )
                ledger.db.commit()
            self.assertTrue(sweeper.register_active_deadline("conflict", due_at=100))
            # Simulate an inconsistent pre-existing delivery record.
            import sqlite3
            with sqlite3.connect(path) as db:
                db.execute(
                    "INSERT INTO voice_timer_alarm_outbox (timer_id,status) "
                    "VALUES ('conflict','cancelled')"
                )
            with self.assertRaises(ValueError):
                sweeper.sweep_due(now=101)
            with TimerStateLedger(path) as ledger:
                rec = ledger.get("conflict")
                self.assertEqual((rec.state, rec.revision), ("active", 0))
            self.assertEqual(TimerAlarmOutbox(path).status("conflict"), "cancelled")

    def test_cancel_active_removes_deadline_and_blocks_alarm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timer.db")
            sweeper = TimerDueSweeper(path)
            with TimerStateLedger(path) as ledger:
                ledger.register_pending("early")
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='active' WHERE timer_id='early'"
                )
                ledger.db.commit()
            self.assertTrue(sweeper.register_active_deadline("early", due_at=100))
            self.assertTrue(sweeper.cancel_active("early"))
            self.assertFalse(sweeper.cancel_active("early"))
            self.assertEqual(sweeper.sweep_due(now=200), 0)
            with TimerStateLedger(path) as ledger:
                rec = ledger.get("early")
                self.assertEqual((rec.state, rec.revision), ("cancelled", 1))
            import sqlite3
            with sqlite3.connect(path) as db:
                self.assertIsNone(db.execute(
                    "SELECT due_at FROM voice_timer_deadlines WHERE timer_id='early'"
                ).fetchone())
            self.assertIsNone(TimerAlarmOutbox(path).status("early"))

    def test_active_cancel_rejects_inconsistent_existing_alarm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timer.db")
            sweeper = TimerDueSweeper(path)
            with TimerStateLedger(path) as ledger:
                ledger.register_pending("conflict-cancel")
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='active' "
                    "WHERE timer_id='conflict-cancel'"
                )
                ledger.db.commit()
            self.assertTrue(sweeper.register_active_deadline("conflict-cancel", due_at=100))
            import sqlite3
            with sqlite3.connect(path) as db:
                db.execute(
                    "INSERT INTO voice_timer_alarm_outbox(timer_id,status) "
                    "VALUES ('conflict-cancel','queued')"
                )
            with self.assertRaisesRegex(ValueError, "unexpected alarm"):
                sweeper.cancel_active("conflict-cancel")
            with TimerStateLedger(path) as ledger:
                self.assertEqual(ledger.get("conflict-cancel").state, "active")

    def test_active_deadline_rejects_existing_alarm_before_insert(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timer.db")
            sweeper = TimerDueSweeper(path)
            with TimerStateLedger(path) as ledger:
                ledger.register_pending("orphan-alarm")
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='active' "
                    "WHERE timer_id='orphan-alarm'"
                )
                ledger.db.commit()
            import sqlite3
            with sqlite3.connect(path) as db:
                db.execute(
                    "INSERT INTO voice_timer_alarm_outbox(timer_id,status) "
                    "VALUES ('orphan-alarm','queued')"
                )
            with self.assertRaisesRegex(ValueError, "unexpected alarm"):
                sweeper.register_active_deadline("orphan-alarm", due_at=100)
            with sqlite3.connect(path) as db:
                self.assertIsNone(db.execute(
                    "SELECT due_at FROM voice_timer_deadlines WHERE timer_id='orphan-alarm'"
                ).fetchone())

    def test_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            sweeper = TimerDueSweeper(os.path.join(tmp, "timer.db"))
            with self.assertRaises(ValueError):
                sweeper.register_active_deadline("x", due_at=float("nan"))
            for limit in (0, -1, 257, True):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    sweeper.sweep_due(now=100, limit=limit)


if __name__ == "__main__":
    unittest.main()
