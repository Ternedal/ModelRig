"""ACL audit records are emitted only for actual committed changes."""
import tempfile
import unittest
from pathlib import Path
from task_access import TaskAccess
from task_store import TaskStore

class AuditTests(unittest.TestCase):
    def test_grant_revoke_audit_noop_suppression(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tasks.sqlite"
            TaskStore(db).create("task")
            acl = TaskAccess(db)
            acl.grant("task", "alice", "read", administrator_id="admin")
            acl.grant("task", "alice", "read", administrator_id="admin")
            acl.revoke("task", "alice", "read", administrator_id="admin")
            acl.revoke("task", "alice", "read", administrator_id="admin")
            records = acl.audit("task")
            self.assertEqual(len(records), 2)
            self.assertEqual([record[2] for record in records], ["grant", "revoke"])
            self.assertEqual([record[3] for record in records], ["admin", "admin"])
            with self.assertRaises(PermissionError):
                acl.require("task", "alice", "read")

    def test_failed_grant_does_not_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tasks.sqlite"
            TaskStore(db)
            acl = TaskAccess(db)
            with self.assertRaises(KeyError):
                acl.grant("missing", "alice", "read")
            self.assertEqual(acl.audit("missing"), [])

if __name__ == "__main__":
    unittest.main()
