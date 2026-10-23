"""Read-only Continuum HTTP API with per-actor task authorization.

Prototype only: local loopback, no external execution or production wiring.
An administrator must provision actor credentials and task ACLs separately.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from task_store import TaskStore
from outbox_inspector import OutboxInspector
from task_snapshot import snapshot
from task_access import TaskAccess
from read_identity import ReadIdentity

def serve(db_path, token=None, host="127.0.0.1", port=8769):
    if token is not None:
        raise ValueError("Shared bearer token mode is disabled; provision actor credentials")
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Prototype must bind to loopback")
    store = TaskStore(db_path)
    inspector = OutboxInspector(db_path)
    access = TaskAccess(db_path)
    identities = ReadIdentity(db_path)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            return self.reply(405, {"error": "method_not_allowed"})

        def do_PUT(self):
            return self.reply(405, {"error": "method_not_allowed"})

        def do_PATCH(self):
            return self.reply(405, {"error": "method_not_allowed"})

        def do_DELETE(self):
            return self.reply(405, {"error": "method_not_allowed"})

        def do_GET(self):
            if len(self.path) > 2048:
                return self.reply(414, {"error": "uri_too_long"})
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer "):
                return self.reply(401, {"error": "unauthorized"})
            try:
                actor_id = identities.resolve(authorization[7:])
            except PermissionError:
                return self.reply(401, {"error": "unauthorized"})
            path = urlsplit(self.path).path
            parts = path.strip("/").split("/")
            if len(parts) not in (2, 3) or parts[0] != "tasks" or not parts[1]:
                return self.reply(404, {"error": "not_found"})
            if len(parts) == 3 and parts[2] not in ("events", "commands", "snapshot"):
                return self.reply(404, {"error": "not_found"})
            task_id = unquote(parts[1])
            if task_id in (".", "..") or "/" in task_id or "\\" in task_id:
                return self.reply(404, {"error": "not_found"})
            try:
                access.require(task_id, actor_id, "read")
            except PermissionError:
                return self.reply(404, {"error": "not_found"})
            try:
                if len(parts) == 3 and parts[2] == "snapshot":
                    return self.reply(200, snapshot(db_path, task_id))
                task = store.get(task_id)
                if len(parts) == 3 and parts[2] == "events":
                    return self.reply(200, {"task_id": task_id, "events": [
                        {"revision": rev, "state": state}
                        for rev, state in store.events(task_id)]})
                if len(parts) == 3 and parts[2] == "commands":
                    return self.reply(200, {"task_id": task_id, "commands": [
                        {"operation_id": command.operation_id,
                         "revision": command.revision,
                         "capability": command.capability,
                         "status": command.status}
                        for command in inspector.list_for_task(task_id)]})
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
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Allow", "GET")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    ThreadingHTTPServer((host, port), Handler).serve_forever()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python read_api.py /path/to/tasks.sqlite")
    serve(sys.argv[1])
