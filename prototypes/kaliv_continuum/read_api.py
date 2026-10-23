"""Read-only HTTP projection of Continuum prototype tasks.

Not wired into ModelRig production. Bind to loopback and require a bearer token.
Usage: KALIV_CONTINUUM_TOKEN=... python read_api.py /path/to/tasks.sqlite
"""
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from task_store import TaskStore

def serve(db_path, token, host="127.0.0.1", port=8769):
    if not token or len(token) < 24:
        raise ValueError("Set a random token of at least 24 characters")
    store = TaskStore(db_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                return self.reply(401, {"error": "unauthorized"})
            parts = urlsplit(self.path).path.strip("/").split("/")
            if len(parts) not in (2, 3) or parts[0] != "tasks" or not parts[1]:
                return self.reply(404, {"error": "not_found"})
            if len(parts) == 3 and parts[2] != "events":
                return self.reply(404, {"error": "not_found"})
            task_id = unquote(parts[1])
            try:
                if len(parts) == 3:
                    events = store.events(task_id)
                    store.get(task_id)
                    return self.reply(200, {"task_id": task_id, "events": [
                        {"revision": rev, "state": state} for rev, state in events]})
                task = store.get(task_id)
                return self.reply(200, {
                    "task_id": task.task_id, "state": task.state.value,
                    "revision": task.revision, "requires_approval": task.requires_approval})
            except KeyError:
                return self.reply(404, {"error": "not_found"})

        def reply(self, status, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass  # Do not log bearer tokens or task identifiers.

    ThreadingHTTPServer((host, port), Handler).serve_forever()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python read_api.py /path/to/tasks.sqlite")
    serve(sys.argv[1], os.environ.get("KALIV_CONTINUUM_TOKEN", ""))
