"""Contract checks for client snapshot response shape and state semantics."""
import tempfile
import unittest
from pathlib import Path
from continuum_state import State
from task_store import TaskStore
from task_snapshot import snapshot

class ClientContractTests(unittest.TestCase):
    def test_snapshot_has_stable_client_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            store = TaskStore(path)
            task = store.create("client-1")
            result = snapshot(path, task.task_id)
            self.assertEqual(result["state"], State.QUEUED.value)
            self.assertEqual(result["presentation"]["phase"], "queued")
            self.assertEqual(result["events"], [])
            self.assertEqual(result["commands"], [])
            self.assertFalse(result["presentation"]["is_running"])
            self.assertFalse(result["presentation"]["terminal"])

    def test_approval_required_state_is_not_authorization(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            store = TaskStore(path)
            task = store.create("client-2")
            task = store.move(task.task_id, State.PLANNING, task.revision)
            task = store.move(task.task_id, State.AWAITING_APPROVAL, task.revision)
            result = snapshot(path, task.task_id)
            self.assertTrue(result["presentation"]["awaiting_approval"])
            self.assertTrue(result["presentation"]["can_request_approval"])
            self.assertEqual(result["revision"], task.revision)
            self.assertEqual(result["state"], "awaiting_approval")

if __name__ == "__main__":
    unittest.main()
