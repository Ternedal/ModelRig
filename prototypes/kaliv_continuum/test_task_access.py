"""Task ACL model tests; caller identity is not authenticated here."""
import tempfile
import unittest
from pathlib import Path
from task_access import TaskAccess
from task_store import TaskStore

class TaskAccessTests(unittest.TestCase):
    def test_default_deny_grant_and_revoke(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            TaskStore(path).create("task-1")
            access = TaskAccess(path)
            with self.assertRaises(PermissionError):
                access.require("task-1", "alice", "read")
            access.grant("task-1", "alice", "read")
            access.require("task-1", "alice", "read")
            with self.assertRaises(PermissionError):
                access.require("task-1", "bob", "read")
            with self.assertRaises(PermissionError):
                access.require("task-1", "alice", "approve")
            access.revoke("task-1", "alice", "read")
            with self.assertRaises(PermissionError):
                access.require("task-1", "alice", "read")

    def test_unknown_task_and_permission_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            TaskStore(path)
            access = TaskAccess(path)
            with self.assertRaises(KeyError):
                access.grant("missing", "alice", "read")
            with self.assertRaises(ValueError):
                access.grant("missing", "alice", "delete")
            with self.assertRaises(PermissionError):
                access.require("missing", "alice", "delete")

if __name__ == "__main__":
    unittest.main()
