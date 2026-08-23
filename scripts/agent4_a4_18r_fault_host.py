#!/usr/bin/env python3
"""Bounded A4-18R wire-fault host for the physical Android fail-closed check.

It binds one explicit RFC1918 address, exposes only /healthz and the current
Agent 4 campaign-list path, never records request headers, and returns HTTP 200
with the correct media type but an intentionally unknown schema. It has no
backend/store/worker authority and exists only while the real backend is stopped.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MEDIA_TYPE = "application/vnd.modelrig.agent4.operator+json"
OPERATOR_PATH = "/api/v1/experimental/agent4/operator/campaigns"


class Handler(BaseHTTPRequestHandler):
    server_version = "ModelRig-A4-18R-Fault/1"

    def log_message(self, _format: str, *_args: object) -> None:
        # Never persist URLs/headers from the credential-bearing physical client.
        return

    def _json(self, status: int, value: object, *, media_type: str = "application/json") -> None:
        body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._json(200, {"status": "ok", "service": "a4-18r-fault-host"})
            return
        if path == OPERATOR_PATH:
            self._json(
                200,
                {
                    "schema": "modelrig-agent4/operator-api/unknown-physical-fault",
                    "campaigns": [],
                    "production_activation": False,
                },
                media_type=MEDIA_TYPE,
            )
            return
        self._json(404, {"error": "not found"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    address = ipaddress.ip_address(args.host)
    if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified:
        raise SystemExit("A4-18R fault host requires one concrete private IPv4 address")
    if not (1 <= args.port <= 65535):
        raise SystemExit("invalid port")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
