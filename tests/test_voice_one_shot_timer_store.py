"""One-shot timer proposals survive restarts but cannot become alarms."""
import os
import sys
import tempfile
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_one_shot_timer_store import OneShotTimerProposalStore


class OneShotTimerProposalStoreTests(unittest.TestCase):
    def test_proposal_is_pending_not_active_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "proposals.sqlite3")
            with OneShotTimerProposalStore(path) as store:
                item = store.propose(300, now=1000)
                self.assertEqual(item.status, "pending")
            with OneShotTimerProposalStore(path) as store:
                persisted = store.get(item.proposal_id, now=1001)
                self.assertEqual(persisted.duration_seconds, 300)
                self.assertEqual(persisted.status, "pending")
                self.assertEqual(store.expire(now=1180), 1)
                self.assertEqual(store.get(item.proposal_id, now=1180).status, "expired")
                self.assertEqual(store.expire(now=9999), 0)

    def test_cancel_is_idempotent_and_durable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "proposals.sqlite3")
            with OneShotTimerProposalStore(path) as store:
                item = store.propose(30, now=1000)
                self.assertTrue(store.cancel(item.proposal_id))
                self.assertFalse(store.cancel(item.proposal_id))
            with OneShotTimerProposalStore(path) as store:
                self.assertEqual(store.get(item.proposal_id, now=9999).status, "cancelled")

    def test_pending_capacity_expires_stale_before_new_insert(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.db")
            with OneShotTimerProposalStore(path) as store:
                first = [store.propose(30, now=1000) for _ in range(32)]
                with self.assertRaisesRegex(ValueError, "too many outstanding"):
                    store.propose(30, now=1001)
                # Cancelled proposals never occupy capacity.
                self.assertTrue(store.cancel(first[0].proposal_id))
                store.propose(30, now=1001)
                # All pending proposals have expired before this insert.
                newest = store.propose(30, now=1182)
                self.assertEqual(store.get(newest.proposal_id, now=1182).status, "pending")

    def test_terminal_retention_does_not_delete_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "proposals.sqlite3")
            with OneShotTimerProposalStore(path) as store:
                old = store.propose(30, now=1000)
                self.assertTrue(store.cancel(old.proposal_id))
                recent = store.propose(30, now=700000)
                self.assertEqual(store.prune(now=700001), 0)
                self.assertIsNone(store.get(old.proposal_id, now=700001))
                self.assertEqual(store.get(recent.proposal_id, now=700001).status, "pending")
                self.assertEqual(store.prune(now=700001), 0)

    def test_explicit_prune_removes_terminal_history_before_new_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with OneShotTimerProposalStore(os.path.join(tmp, "p.db")) as store:
                old = store.propose(30, now=1000)
                self.assertTrue(store.cancel(old.proposal_id))
                self.assertEqual(store.prune(now=700000), 1)
                self.assertIsNone(store.get(old.proposal_id, now=700000))

    def test_propose_prunes_terminal_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            with OneShotTimerProposalStore(os.path.join(tmp, "p.db")) as store:
                old = store.propose(30, now=1000)
                self.assertTrue(store.cancel(old.proposal_id))
                store.propose(30, now=700000)
                self.assertIsNone(store.get(old.proposal_id, now=700000))

    def test_rejects_invalid_duration_and_missing_path(self):
        with self.assertRaises(ValueError):
            OneShotTimerProposalStore("")
        with tempfile.TemporaryDirectory() as tmp:
            with OneShotTimerProposalStore(os.path.join(tmp, "p.db")) as store:
                for value in (0, 3601, True, 1.5, -3):
                    with self.subTest(value=value), self.assertRaises(ValueError):
                        store.propose(value, now=1000)


if __name__ == "__main__":
    unittest.main()
