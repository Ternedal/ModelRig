"""Atomic timer proposal/ledger integration, using only temporary SQLite."""
import os
import sys
import tempfile
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_timer_proposal_ledger_bridge import TimerProposalLedgerBridge
from app.voice_one_shot_timer_store import OneShotTimerProposalStore
from app.voice_timer_state_ledger import TimerStateLedger


class TimerProposalLedgerBridgeTest(unittest.TestCase):
    def test_registers_both_records_with_same_identifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            proposal = TimerProposalLedgerBridge(path).create_pending(300, now=1000)
            with OneShotTimerProposalStore(path) as store, TimerStateLedger(path) as ledger:
                self.assertEqual(store.get(proposal.proposal_id, now=1001).status, "pending")
                record = ledger.get(proposal.proposal_id)
                self.assertEqual((record.state, record.revision), ("pending", 0))

    def test_expiry_updates_ledger_and_revision_on_next_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            old = bridge.create_pending(30, now=1000)
            bridge.create_pending(30, now=1180)
            with OneShotTimerProposalStore(path) as store, TimerStateLedger(path) as ledger:
                self.assertEqual(store.get(old.proposal_id, now=1180).status, "expired")
                record = ledger.get(old.proposal_id)
                self.assertEqual((record.state, record.revision), ("expired", 1))
                with self.assertRaises(ValueError):
                    ledger.transition(old.proposal_id, expected_revision=0, target="cancelled")

    def test_cancel_updates_both_tables_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            item = bridge.create_pending(30, now=1000)
            self.assertTrue(bridge.cancel_pending(item.proposal_id, now=1001))
            self.assertFalse(bridge.cancel_pending(item.proposal_id, now=1002))
            with OneShotTimerProposalStore(path) as store, TimerStateLedger(path) as ledger:
                self.assertEqual(store.get(item.proposal_id, now=1002).status, "cancelled")
                self.assertEqual((ledger.get(item.proposal_id).state, ledger.get(item.proposal_id).revision), ("cancelled", 1))

    def test_cancel_at_deadline_expires_both_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            item = bridge.create_pending(30, now=1000)
            self.assertFalse(bridge.cancel_pending(item.proposal_id, now=1180))
            with OneShotTimerProposalStore(path) as store, TimerStateLedger(path) as ledger:
                self.assertEqual(store.get(item.proposal_id, now=1180).status, "expired")
                self.assertEqual(ledger.get(item.proposal_id).state, "expired")

    def test_rejected_requests_do_not_create_orphans(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            for duration in (0, 3601, True, "30"):
                with self.subTest(duration=duration), self.assertRaises(ValueError):
                    bridge.create_pending(duration, now=1000)
            item = bridge.create_pending(30, now=1000)
            with OneShotTimerProposalStore(path) as store, TimerStateLedger(path) as ledger:
                self.assertEqual(store.get(item.proposal_id, now=1001).duration_seconds, 30)
                self.assertIsNotNone(ledger.get(item.proposal_id))


if __name__ == "__main__":
    unittest.main()
