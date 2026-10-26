"""HTTP approval audit route must require approve ACL, not read ACL."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from approval_gate import ApprovalGate
from continuum_state import State
from read_api import serve
from read_identity import ReadIdentity
from task_access import TaskAccess
from task_store import TaskStore

class ApprovalAuditHttpTests(unittest.TestCase):
    def test_approve_only_and_redacted(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tasks.sqlite"
            store = TaskStore(db)
            task = store.create("demo")
            task = store.move("demo", State.PLANNING, task.revision)
            task = store.move("demo", State.AWAITING_APPROVAL, task.revision)
            acl = TaskAccess(db)
            acl.grant("demo", "reader", "read")
            acl.grant("demo", "approver", "approve")
            identity = ReadIdentity(db)
            reader = identity.issue("reader")
            approver = identity.issue("approver")
            secret = ApprovalGate(db).issue_for_checkpoint(
                task_id="demo", approver_id="approver", executor_id="worker",
                capability="nas.read", expected_revision=task.revision)
            import http.server
            servers = []
            base = http.server.ThreadingHTTPServer
            class TestServer(base):
                def __init__(self, address, handler):
                    super().__init__(("127.0.0.1", 0), handler)
                    self.timeout = 3
                    servers.append(self)
                def serve_forever(self):
                    for _ in range(4):
                        self.handle_request()
            with patch("read_api.ThreadingHTTPServer", TestServer):
                thread = threading.Thread(target=serve, args=(db,), daemon=True)
                thread.start()
                for _ in range(10000):
                    if servers:
                        break
                    threading.Event().wait(0.001)
                self.assertTrue(servers)
                conn = http.client.HTTPConnection("127.0.0.1", servers[0].server_address[1], timeout=3)
                def request(token):
                    conn.request("GET", "/tasks/demo/approvals",
                                 headers={"Authorization": "Bearer " + token})
                    response = conn.getresponse()
                    return response.status, response.read().decode()
                status, _ = request(reader)
                self.assertEqual(status, 404)
                status, body = request(approver)
                self.assertEqual(status, 200)
                payload = json.loads(body)
                self.assertEqual(payload["approvals"][0]["approver_id"], "approver")
                self.assertNotIn(secret, body)
                self.assertNotIn("grant_digest", body)
                acl.revoke("demo", "approver", "approve")
                status, _ = request(approver)
                self.assertEqual(status, 404)
                conn.close()
                thread.join(timeout=5)
                servers[0].server_close()
                self.assertFalse(thread.is_alive())

if __name__ == "__main__":
    unittest.main()
