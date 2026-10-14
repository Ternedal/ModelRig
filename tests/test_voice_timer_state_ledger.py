"""Timer ledger is restart-safe, compare-and-swap, and activation-proof."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_timer_state_ledger import TimerStateLedger


class TimerLedgerTests(unittest.TestCase):
    def test_cancel_and_expire_survive_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "timer.sqlite")
            with TimerStateLedger(path) as ledger:
                timer = ledger.register_pending("a")
                cancelled = ledger.transition("a", expected_revision=timer.revision, target="cancelled")
                self.assertEqual((cancelled.state, cancelled.revision), ("cancelled", 1))
                with self.assertRaises(ValueError):
                    ledger.transition("a", expected_revision=0, target="expired")
            with TimerStateLedger(path) as ledger:
                self.assertEqual(ledger.get("a").state, "cancelled")
                expired = ledger.register_pending("b")
                ledger.transition("b", expected_revision=expired.revision, target="expired")
                self.assertEqual(ledger.get("b").state, "expired")

    def test_two_connections_cannot_reuse_same_revision(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "timer.sqlite")
            with TimerStateLedger(path) as first, TimerStateLedger(path) as second:
                first.register_pending("shared")
                first.transition("shared", expected_revision=0, target="cancelled")
                with self.assertRaises(ValueError):
                    second.transition("shared", expected_revision=0, target="expired")
                self.assertEqual(second.get("shared").state, "cancelled")

    def test_rejects_invalid_revisions_and_identifiers(self):
        with tempfile.TemporaryDirectory() as d:
            with TimerStateLedger(os.path.join(d, "timer.sqlite")) as ledger:
                ledger.register_pending("valid")
                for revision in (-1, True, 0.5, "0"):
                    with self.subTest(revision=revision), self.assertRaises(ValueError):
                        ledger.transition("valid", expected_revision=revision, target="cancelled")
                for timer_id in (None, 3, "", "  "):
                    with self.subTest(timer_id=timer_id), self.assertRaises(ValueError):
                        ledger.register_pending(timer_id)
                self.assertEqual(ledger.get("valid").state, "pending")

    def test_rejects_activation_and_duplicate_registration(self):
        with tempfile.TemporaryDirectory() as d:
            with TimerStateLedger(os.path.join(d, "timer.sqlite")) as ledger:
                ledger.register_pending("a")
                with self.assertRaises(ValueError):
                    ledger.transition("a", expected_revision=0, target="active")
                with self.assertRaises(ValueError):
                    ledger.transition("a", expected_revision=0, target="delivered")
                with self.assertRaises(ValueError):
                    ledger.register_pending(" ")
                with self.assertRaises(Exception):
                    ledger.register_pending("a")
                self.assertEqual(ledger.get("a").state, "pending")


if __name__ == "__main__":
    unittest.main()
