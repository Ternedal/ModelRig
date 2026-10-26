"""HTTP boundary tests: method restrictions and URL length."""
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

class HttpBoundaryTests(unittest.TestCase):
    def test_mutations_denied_and_oversize_url_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tasks.sqlite"
            TaskStore(db).create("task")
            TaskAccess(db).grant("task", "alice", "read")
            token = ReadIdentity(db).issue("alice")
            import http.server
            base = http.server.ThreadingHTTPServer
            servers = []
            class TestServer(base):
                def __init__(self, address, handler):
                    super().__init__(("127.0.0.1", 0), handler)
                    self.timeout = 3
                    servers.append(self)
                def serve_forever(self):
                    for _ in range(6):
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
                for method in ("POST", "PUT", "PATCH", "DELETE"):
                    conn.request(method, "/tasks/task", body=b"{}",
                                 headers={"Authorization": "Bearer " + token})
                    response = conn.getresponse()
                    self.assertEqual(response.status, 405)
                    self.assertEqual(response.getheader("Allow"), "GET")
                    response.read()
                conn.request("GET", "/tasks/" + "x" * 2050,
                             headers={"Authorization": "Bearer " + token})
                response = conn.getresponse()
                self.assertEqual(response.status, 414)
                response.read()
                conn.request("GET", "/tasks/task",
                             headers={"Authorization": "Bearer " + token})
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                conn.close()
                thread.join(timeout=5)
                servers[0].server_close()
                self.assertFalse(thread.is_alive())

if __name__ == "__main__":
    unittest.main()
