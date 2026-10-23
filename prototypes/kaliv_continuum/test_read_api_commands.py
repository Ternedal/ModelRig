"""HTTP API tests for per-actor read authorization."""
import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from read_api import serve
from task_store import TaskStore
from task_access import TaskAccess
from read_identity import ReadIdentity

class ReadApiTests(unittest.TestCase):
    def test_commands_endpoint_requires_task_scoped_actor(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            store = TaskStore(path)
            store.create("task-1")
            with sqlite3.connect(path) as db:
                db.execute("""INSERT INTO command_outbox
                    (operation_id,task_id,revision,capability,actor_id,status)
                    VALUES ('op-1','task-1',1,'nas.read','owner','simulated')""")
            identities = ReadIdentity(path)
            alice = identities.issue("alice")
            bob = identities.issue("bob")
            TaskAccess(path).grant("task-1", "alice", "read")
            import http.server
            original = http.server.ThreadingHTTPServer
            servers = []
            class TestServer(original):
                def __init__(self, address, handler):
                    super().__init__(("127.0.0.1", 0), handler)
                    self.timeout = 3
                    servers.append(self)
                def serve_forever(self):
                    for _ in range(4):
                        self.handle_request()
            with patch("read_api.ThreadingHTTPServer", TestServer):
                thread = threading.Thread(target=serve, args=(path,), daemon=True)
                thread.start()
                for _ in range(10000):
                    if servers:
                        break
                    threading.Event().wait(0.001)
                self.assertTrue(servers)
                conn = http.client.HTTPConnection("127.0.0.1", servers[0].server_address[1], timeout=3)
                for credential, expected in ((None,401),(bob,404),(alice,200),("invalid",401)):
                    headers = {} if credential is None else {"Authorization": "Bearer " + credential}
                    conn.request("GET", "/tasks/task-1/commands", headers=headers)
                    response = conn.getresponse()
                    self.assertEqual(response.status, expected)
                    payload = json.loads(response.read())
                    if expected == 200:
                        self.assertEqual(payload["commands"][0]["status"], "simulated")
                conn.close()
                thread.join(timeout=5)
                servers[0].server_close()
                self.assertFalse(thread.is_alive())

if __name__ == "__main__":
    unittest.main()
