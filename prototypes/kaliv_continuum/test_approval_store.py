"""Unit tests for scoped one-use approval grants."""
import tempfile
import unittest
from pathlib import Path
from approval_store import ApprovalStore

class ApprovalTests(unittest.TestCase):
    def test_one_use_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApprovalStore(Path(tmp) / "grants.sqlite")
            token = store.issue(task_id="t", actor_id="a", capability="nas.read", revision=2)
            args = dict(task_id="t", actor_id="a", capability="nas.read", revision=2)
            self.assertFalse(store.consume(token, **{**args, "actor_id": "b"}))
            self.assertFalse(store.consume(token, **{**args, "revision": 3}))
            self.assertTrue(store.consume(token, **args))
            self.assertFalse(store.consume(token, **args))

    def test_reject_invalid_grant(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApprovalStore(Path(tmp) / "grants.sqlite")
            with self.assertRaises(ValueError):
                store.issue(task_id="t", actor_id="a", capability="x", revision=0, ttl_seconds=901)
            self.assertFalse(store.consume("unknown", task_id="t", actor_id="a", capability="x", revision=0))

if __name__ == "__main__":
    unittest.main()
