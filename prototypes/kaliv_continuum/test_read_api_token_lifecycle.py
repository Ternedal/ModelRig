"""HTTP regression for expiring and rotated read credentials."""
import http.client
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from read_api import serve
from task_store import TaskStore
from task_access import TaskAccess
from read_identity import ReadIdentity

class HttpTokenLifecycleTests(unittest.TestCase):
    def test_http_rejects_expired_and_rotated_tokens(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tasks.sqlite"
            TaskStore(db).create("task")
            TaskAccess(db).grant("task", "alice", "read")
            identity = ReadIdentity(db)
            with patch("read_identity.time.time", return_value=1000):
                old = identity.issue("alice", ttl_seconds=10)
            import http.server
            base = http.server.ThreadingHTTPServer
            servers = []
            class TestServer(base):
                def __init__(self, address, handler):
                    super().__init__(("127.0.0.1", 0), handler)
                    self.timeout = 3
                    servers.append(self)
                def serve_forever(self):
                    for _ in range(5):
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
                def status(token):
                    conn.request("GET", "/tasks/task/snapshot",
                                 headers={"Authorization": "Bearer " + token})
                    response = conn.getresponse()
                    response.read()
                    return response.status
                with patch("read_identity.time.time", return_value=1001):
                    self.assertEqual(status(old), 200)
                    new = identity.rotate(old, ttl_seconds=20)
                    self.assertEqual(status(old), 401)
                    self.assertEqual(status(new), 200)
                with patch("read_identity.time.time", return_value=1022):
                    self.assertEqual(status(new), 401)
                conn.close()
                thread.join(timeout=5)
                servers[0].server_close()
                self.assertFalse(thread.is_alive())

if __name__ == "__main__":
    unittest.main()
