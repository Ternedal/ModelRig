"""HTTP API tests for task command history, auth and path handling."""
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

class OneRequestServer:
    def __init__(self, address, handler):
        from http.server import ThreadingHTTPServer
        self.server = ThreadingHTTPServer(address, handler)

class ReadApiTests(unittest.TestCase):
    def test_commands_endpoint_requires_auth(self):
        # Exercise the real handler through a one-request server, not a mock response.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            store = TaskStore(path)
            store.create("task-1")
            with sqlite3.connect(path) as db:
                db.execute("""INSERT INTO command_outbox
                    (operation_id,task_id,revision,capability,actor_id,status)
                    VALUES ('op-1','task-1',1,'nas.read','owner','simulated')""")
            token = "test-only-token-longer-than-24-characters"
            import http.server
            original = http.server.ThreadingHTTPServer
            servers = []
            class TestServer(original):
                def __init__(self, address, handler):
                    super().__init__(("127.0.0.1", 0), handler)
                    servers.append(self)
                def serve_forever(self):
                    self.handle_request()
                    self.handle_request()
            with patch("read_api.ThreadingHTTPServer", TestServer):
                thread = threading.Thread(target=serve, args=(path, token), daemon=True)
                thread.start()
                # The server is created in the thread; synchronize using an event.
                for _ in range(10000):
                    if servers:
                        break
                    threading.Event().wait(0.001)
                self.assertTrue(servers)
                port = servers[0].server_address[1]
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                conn.request("GET", "/tasks/task-1/commands")
                unauthorized = conn.getresponse()
                self.assertEqual(unauthorized.status, 401)
                unauthorized.read()
                conn.request("GET", "/tasks/task-1/commands",
                             headers={"Authorization": "Bearer " + token})
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                payload = json.loads(response.read())
                self.assertEqual(payload["commands"][0]["status"], "simulated")
                self.assertEqual(payload["commands"][0]["capability"], "nas.read")
                conn.close()
                thread.join(timeout=3)
                servers[0].server_close()

if __name__ == "__main__":
    unittest.main()
