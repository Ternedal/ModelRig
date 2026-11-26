#!/usr/bin/env python3
"""A deterministic stand-in for Ollama, for the rig simulator.

The simulator proves that the *operators* run: paths, arguments, environment,
PowerShell 5.1 syntax, the HTTP contracts between backend, worker and the
scripts. It does not prove model quality, so no model is loaded. This server
answers the Ollama endpoints the worker and backend call, always the same way:

- ``GET  /``                  liveness text, as Ollama answers it
- ``GET  /api/version``       a fixed version
- ``GET  /api/tags``          two models: a planner and an embedder
- ``POST /api/show``          a minimal model card
- ``POST /api/chat``          one short assistant reply (stream or not)
- ``POST /api/generate``      one short completion (stream or not)
- ``POST /api/embed``         a 26-dimensional letter-count vector per input
- ``POST /api/embeddings``    the legacy single-prompt form of the same

Nothing here is random and nothing depends on the clock, so two runs of the
simulator see identical answers. The vector is the same one ``tests/e2e.py``
uses, so a RAG index built against this server is comparable across runs.

Usage::

    python scripts/rig_simulator/mock_ollama.py --port 11600

The server binds loopback only and stops on SIGINT/SIGTERM. ``run_operators.py``
starts it in-process; the CLI exists so an operator can be tried by hand.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

sys.dont_write_bytecode = True

PLANNER_MODEL = "qwen3:14b"
EMBED_MODEL = "nomic-embed-text"
VERSION = "0.0.0-rig-simulator"
REPLY = "Rig-simulator: deterministisk svar."
DIMENSIONS = 26


def vector(text: str) -> list[float]:
    """Letter counts a-z: deterministic, cheap, and distinct for distinct text."""
    out = [0.0] * DIMENSIONS
    for ch in text.lower():
        index = ord(ch) - 97
        if 0 <= index < DIMENSIONS:
            out[index] += 1.0
    return out


def _model(name: str, family: str) -> dict[str, Any]:
    return {
        "name": name,
        "model": name,
        "modified_at": "2026-01-01T00:00:00Z",
        "size": 1,
        "digest": "0" * 64,
        "details": {
            "family": family,
            "families": [family],
            "parameter_size": "0",
            "quantization_level": "none",
        },
    }


class MockOllama(BaseHTTPRequestHandler):
    server_version = "MockOllama/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: Any) -> None:  # quiet by design
        return

    # -- helpers ---------------------------------------------------------
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def _payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            value = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _ndjson(self, lines: list[dict[str, Any]]) -> None:
        body = b"".join(json.dumps(line).encode("utf-8") + b"\n" for line in lines)
        self._send(200, body, "application/x-ndjson")

    # -- routes ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/":
            self._send(200, b"Ollama is running", "text/plain")
        elif self.path == "/api/version":
            self._json({"version": VERSION})
        elif self.path == "/api/tags":
            self._json({"models": [_model(PLANNER_MODEL, "qwen3"), _model(EMBED_MODEL, "nomic-bert")]})
        elif self.path == "/api/ps":
            self._json({"models": []})
        else:
            self._json({"error": f"unknown path {self.path}"}, 404)

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        payload = self._payload()
        model = str(payload.get("model") or PLANNER_MODEL)
        if self.path == "/api/show":
            self._json({"modelfile": "", "parameters": "", "template": "", "details": _model(model, "mock")["details"]})
        elif self.path == "/api/embed":
            inputs = payload.get("input", "")
            texts = inputs if isinstance(inputs, list) else [str(inputs)]
            self._json({"model": model, "embeddings": [vector(str(t)) for t in texts]})
        elif self.path == "/api/embeddings":
            self._json({"embedding": vector(str(payload.get("prompt", "")))})
        elif self.path == "/api/chat":
            if payload.get("stream", True):
                self._ndjson([
                    {"model": model, "message": {"role": "assistant", "content": REPLY}, "done": False},
                    {"model": model, "message": {"role": "assistant", "content": ""}, "done": True,
                     "done_reason": "stop", "eval_count": 1, "prompt_eval_count": 1},
                ])
            else:
                self._json({"model": model, "message": {"role": "assistant", "content": REPLY},
                            "done": True, "done_reason": "stop", "eval_count": 1, "prompt_eval_count": 1})
        elif self.path == "/api/generate":
            if payload.get("stream", True):
                self._ndjson([
                    {"model": model, "response": REPLY, "done": False},
                    {"model": model, "response": "", "done": True, "done_reason": "stop"},
                ])
            else:
                self._json({"model": model, "response": REPLY, "done": True, "done_reason": "stop"})
        else:
            self._json({"error": f"unknown path {self.path}"}, 404)


class Server:
    """Owns one loopback HTTPServer on a background thread."""

    def __init__(self, port: int) -> None:
        self.httpd = HTTPServer(("127.0.0.1", port), MockOllama)
        self.port = int(self.httpd.server_address[1])
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="mock-ollama", daemon=True)

    def start(self) -> "Server":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=11600, help="loopback port (0 = any free port)")
    args = parser.parse_args(argv)
    server = Server(args.port).start()
    print(json.dumps({"url": server.url, "planner": PLANNER_MODEL, "embedder": EMBED_MODEL}), flush=True)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
