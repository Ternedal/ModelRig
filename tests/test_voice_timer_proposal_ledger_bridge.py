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

    def test_bulk_expiry_is_consistent_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            first = bridge.create_pending(30, now=1000)
            second = bridge.create_pending(30, now=1001)
            self.assertEqual(bridge.expire_pending(now=1180), 1)
            self.assertEqual(bridge.expire_pending(now=1180), 0)
            with OneShotTimerProposalStore(path) as store, TimerStateLedger(path) as ledger:
                self.assertEqual(store.get(first.proposal_id, now=1180).status, "expired")
                self.assertEqual(ledger.get(first.proposal_id).revision, 1)
                self.assertEqual(store.get(second.proposal_id, now=1180).status, "pending")
                self.assertEqual(ledger.get(second.proposal_id).revision, 0)
            self.assertEqual(bridge.expire_pending(now=1181), 1)
            self.assertEqual(bridge.expire_pending(now=1181), 0)

    def test_expiry_rollback_if_ledger_record_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            item = bridge.create_pending(30, now=1000)
            with TimerStateLedger(path) as ledger:
                ledger.db.execute(
                    "DELETE FROM voice_timer_state_ledger WHERE timer_id=?",
                    (item.proposal_id,),
                )
                ledger.db.commit()
            with self.assertRaises(ValueError):
                bridge.expire_pending(now=1180)
            with OneShotTimerProposalStore(path) as store:
                self.assertEqual(store.get(item.proposal_id, now=1001).status, "pending")

    def test_new_registration_fails_closed_on_expired_ledger_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            old = bridge.create_pending(30, now=1000)
            with TimerStateLedger(path) as ledger:
                ledger.db.execute(
                    "DELETE FROM voice_timer_state_ledger WHERE timer_id=?",
                    (old.proposal_id,),
                )
                ledger.db.commit()
            with self.assertRaises(ValueError):
                bridge.create_pending(30, now=1180)
            with OneShotTimerProposalStore(path) as store:
                self.assertEqual(store.get(old.proposal_id, now=1001).status, "pending")

    def test_new_registration_only_expires_newly_due_ledger_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            first = bridge.create_pending(30, now=1000)
            bridge.create_pending(30, now=1180)
            bridge.create_pending(30, now=1181)
            with TimerStateLedger(path) as ledger:
                self.assertEqual(ledger.get(first.proposal_id).revision, 1)
                self.assertEqual(ledger.get(first.proposal_id).state, "expired")

    def test_rejects_live_pending_proposal_without_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            original = bridge.create_pending(30, now=1000)
            with TimerStateLedger(path) as ledger:
                ledger.db.execute(
                    "DELETE FROM voice_timer_state_ledger WHERE timer_id=?",
                    (original.proposal_id,)
                )
                ledger.db.commit()
            with self.assertRaisesRegex(ValueError, "state mismatch"):
                bridge.create_pending(30, now=1001)
            with self.assertRaisesRegex(ValueError, "state mismatch"):
                bridge.expire_pending(now=1001)
            with OneShotTimerProposalStore(path) as store:
                self.assertEqual(store.get(original.proposal_id, now=1001).status, "pending")

    def test_rejects_orphan_pending_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            bridge.create_pending(30, now=1000)
            with TimerStateLedger(path) as ledger:
                ledger.register_pending("orphan")
            with self.assertRaisesRegex(ValueError, "state mismatch"):
                bridge.create_pending(30, now=1001)
            with self.assertRaisesRegex(ValueError, "state mismatch"):
                bridge.expire_pending(now=1001)

    def test_rejects_terminal_state_divergence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            item = bridge.create_pending(30, now=1000)
            self.assertTrue(bridge.cancel_pending(item.proposal_id, now=1001))
            with TimerStateLedger(path) as ledger:
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='expired' WHERE timer_id=?",
                    (item.proposal_id,)
                )
                ledger.db.commit()
            with self.assertRaisesRegex(ValueError, "state mismatch"):
                bridge.create_pending(30, now=1002)

    def test_inspection_is_read_only_and_never_claims_active_timer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            proposal = bridge.create_pending(30, now=1000)
            snapshot = bridge.inspect_pending(proposal.proposal_id, now=1001)
            self.assertEqual(snapshot["status"], "pending")
            self.assertEqual(snapshot["revision"], 0)
            self.assertTrue(snapshot["can_request_confirmation"])
            self.assertFalse(snapshot["timer_started"])
            expired_view = bridge.inspect_pending(proposal.proposal_id, now=1180)
            self.assertFalse(expired_view["can_request_confirmation"])
            self.assertEqual(expired_view["revision"], 0)
            self.assertEqual(bridge.inspect_pending("not-found", now=1001), None)
            self.assertEqual(bridge.expire_pending(now=1180), 1)

    def test_inspection_fails_closed_on_missing_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            proposal = bridge.create_pending(30, now=1000)
            with TimerStateLedger(path) as ledger:
                ledger.db.execute(
                    "DELETE FROM voice_timer_state_ledger WHERE timer_id=?",
                    (proposal.proposal_id,)
                )
                ledger.db.commit()
            with self.assertRaisesRegex(ValueError, "state mismatch"):
                bridge.inspect_pending(proposal.proposal_id, now=1001)
            with self.assertRaises(ValueError):
                bridge.inspect_pending("", now=1001)

    def test_cancel_rejects_divergent_terminal_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "timers.sqlite")
            bridge = TimerProposalLedgerBridge(path)
            item = bridge.create_pending(30, now=1000)
            self.assertTrue(bridge.cancel_pending(item.proposal_id, now=1001))
            with TimerStateLedger(path) as ledger:
                ledger.db.execute(
                    "UPDATE voice_timer_state_ledger SET state='expired' WHERE timer_id=?",
                    (item.proposal_id,)
                )
                ledger.db.commit()
            with self.assertRaisesRegex(ValueError, "state mismatch"):
                bridge.cancel_pending(item.proposal_id, now=1002)

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
