"""A tiny stand-in for ComfyUI's HTTP API, for supervisor and adapter tests.

It is launched as a real child process with ComfyUI-shaped arguments
(--listen, --port, --output-directory, ...). No GPU, no models, loopback only.
Behaviour is steered by FAKE_COMFY_* environment variables, and it writes its
pid and the environment it saw to FAKE_COMFY_STATE_DIR so tests can check what
the supervisor actually passed. The real supervisor drops FAKE_COMFY_* (not
in its passthrough list); tests add them in a ComfySupervisor subclass.
"""
import argparse
import json
import os
import signal
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

parser = argparse.ArgumentParser()
parser.add_argument("--listen", required=True)
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--input-directory")
parser.add_argument("--output-directory", required=True)
parser.add_argument("--temp-directory")
parser.add_argument("--user-directory")
parser.add_argument("--disable-auto-launch", action="store_true")
parser.add_argument("--disable-metadata", action="store_true")
parser.add_argument("--disable-all-custom-nodes", action="store_true")
args = parser.parse_args()

if args.listen != "127.0.0.1":
    sys.exit("fake ComfyUI only listens on loopback")

STATE = os.environ.get("FAKE_COMFY_STATE_DIR", "")
GIB = 1024 ** 3
devices = int(os.environ.get("FAKE_COMFY_DEVICES", "1"))
vram_total = int(float(os.environ.get("FAKE_COMFY_VRAM_TOTAL_GIB", "24")) * GIB)
vram_free = int(float(os.environ.get("FAKE_COMFY_VRAM_FREE_GIB", "20")) * GIB)
render_seconds = float(os.environ.get("FAKE_COMFY_RENDER_SECONDS", "0.2"))
startup_delay = float(os.environ.get("FAKE_COMFY_STARTUP_DELAY", "0"))
device_type = os.environ.get("FAKE_COMFY_DEVICE_TYPE", "cuda")

if os.environ.get("FAKE_COMFY_IGNORE_TERM") == "1":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if os.environ.get("FAKE_COMFY_EXIT_EARLY") == "1":
    sys.exit(3)

if STATE:
    with open(os.path.join(STATE, "pid"), "w") as fh:
        fh.write(str(os.getpid()))
    with open(os.path.join(STATE, "env.json"), "w") as fh:
        json.dump({"env": dict(os.environ), "argv": sys.argv[1:],
                   "fds": sorted(int(fd) for fd in os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else []}, fh)

lock = threading.Lock()
history: dict = {}
queue: list = []
interrupted = threading.Event()


def _render(prompt_id: str) -> None:
    deadline = time.monotonic() + render_seconds
    while time.monotonic() < deadline:
        if interrupted.is_set():
            with lock:
                history[prompt_id] = {"status": {"status_str": "error", "completed": False}, "outputs": {}}
                queue.remove(prompt_id)
            return
        time.sleep(0.02)
    name = f"kaliv_{prompt_id[:8]}.mp4"
    with open(os.path.join(args.output_directory, name), "wb") as fh:
        fh.write(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 64)
    with lock:
        history[prompt_id] = {
            "status": {"status_str": "success", "completed": True},
            "outputs": {"9": {"videos": [{"filename": name, "subfolder": "", "type": "output"}]}},
        }
        queue.remove(prompt_id)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, obj, status=200):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/system_stats":
            device = {"name": "cuda:0 Fake GPU", "type": device_type, "index": 0,
                      "vram_total": vram_total, "vram_free": vram_free}
            self._send({"system": {"comfyui_version": "fake"}, "devices": [device] * devices})
        elif self.path == "/queue":
            with lock:
                self._send({"queue_running": [[0, pid] for pid in queue[:1]],
                            "queue_pending": [[i, pid] for i, pid in enumerate(queue[1:], 1)]})
        elif self.path.startswith("/history/"):
            prompt_id = self.path[len("/history/"):]
            with lock:
                self._send({prompt_id: history[prompt_id]} if prompt_id in history else {})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/prompt":
            if not isinstance(body.get("prompt"), dict):
                self._send({"error": "no prompt"}, 400)
                return
            prompt_id = str(uuid.uuid4())
            interrupted.clear()
            with lock:
                queue.append(prompt_id)
            threading.Thread(target=_render, args=(prompt_id,), daemon=True).start()
            self._send({"prompt_id": prompt_id, "number": 0})
        elif self.path == "/interrupt":
            interrupted.set()
            self._send({})
        else:
            self._send({"error": "not found"}, 404)


time.sleep(startup_delay)
ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
