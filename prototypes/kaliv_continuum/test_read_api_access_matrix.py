"""End-to-end read API access matrix across every endpoint."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from read_api import serve
from task_store import TaskStore
from task_access import TaskAccess
from read_identity import ReadIdentity

class AccessMatrixTests(unittest.TestCase):
    def test_every_route_denies_other_actor_and_revocations(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tasks.sqlite"
            TaskStore(db).create("private")
            acl = TaskAccess(db)
            ids = ReadIdentity(db)
            alice = ids.issue("alice")
            bob = ids.issue("bob")
            acl.grant("private", "alice", "read")
            import http.server
            base = http.server.ThreadingHTTPServer
            servers = []
            class TestServer(base):
                def __init__(self, address, handler):
                    super().__init__(("127.0.0.1", 0), handler)
                    self.timeout = 3
                    servers.append(self)
                def serve_forever(self):
                    for _ in range(18):
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
                routes = ("/tasks/private", "/tasks/private/events",
                          "/tasks/private/commands", "/tasks/private/snapshot")
                def request(path, credential):
                    conn.request("GET", path, headers={"Authorization": "Bearer " + credential})
                    response = conn.getresponse()
                    status = response.status
                    body = json.loads(response.read())
                    return status, body
                for route in routes:
                    self.assertEqual(request(route, bob)[0], 404)
                    self.assertEqual(request(route, alice)[0], 200)
                acl.revoke("private", "alice", "read")
                for route in routes:
                    self.assertEqual(request(route, alice)[0], 404)
                acl.grant("private", "alice", "read")
                ids.revoke(alice)
                for route in routes:
                    self.assertEqual(request(route, alice)[0], 401)
                self.assertEqual(request("/tasks/nonexistent", bob)[0], 404)
                self.assertEqual(request("/tasks/private/%2fsecret", bob)[0], 404)
                conn.close()
                thread.join(timeout=5)
                servers[0].server_close()
                self.assertFalse(thread.is_alive())

if __name__ == "__main__":
    unittest.main()
