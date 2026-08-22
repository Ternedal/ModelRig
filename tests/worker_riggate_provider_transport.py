from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.data_sharing import DataSharingLedger  # noqa: E402
from app.home_rig_connector_contract import HomeRigDenied, HomeRigGrantStore, HomeRigScope  # noqa: E402
from app.home_rig_read_boundary import prepare_read  # noqa: E402
from app.riggate_provider_transport import (  # noqa: E402
    RigGateConnection,
    RigGateTransportError,
    execute_riggate_status_read,
)
from app.riggate_v1_contract import authorize_riggate_request  # noqa: E402
from app.web_fetch import TransportResponse  # noqa: E402

passed = failed = 0
TOKEN = "fixture-riggate-bearer-token-12345"


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def rejects(fn, exc_type, name: str, contains: str = "") -> None:
    try:
        fn()
    except exc_type as exc:
        check(not contains or contains in str(exc), name)
    else:
        check(False, name)


class UUIDs:
    def __init__(self, start: int = 0) -> None:
        self.value = start

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:
        fixture = self.server.fixture
        fixture["hits"] += 1
        fixture["path"] = self.path
        fixture["authorization"] = self.headers.get("Authorization")
        mode = fixture["mode"]
        if mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/must-not-follow")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        rig_id = "substituted-rig" if mode == "substitute" else "render-rig-1"
        payload = json.dumps(
            {
                "schema": "kaliv-riggate-status/v1",
                "rig_id": rig_id,
                "operation": "rig_health",
                "state": "ready",
                "observed_at": 120,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_server(mode: str = "success"):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    server.fixture = {"mode": mode, "hits": 0, "path": None, "authorization": None}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def token_file(root: str) -> Path:
    path = Path(root) / "riggate.token"
    path.write_text(TOKEN + "\n", encoding="ascii")
    if os.name == "posix":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def make_authorized(*, start: int = 0):
    grants = HomeRigGrantStore(uuid_factory=UUIDs(start))
    ledger = DataSharingLedger(uuid_factory=UUIDs(start + 100))
    scope = HomeRigScope(
        rig_ids=("render-rig-1",),
        operations=("rig_health", "rig_power_readiness"),
    )
    grant = grants.create(scope, actor="operator", now=100)
    claim = prepare_read(
        grants,
        grant.grant_id,
        target_kind="rig",
        target_id="render-rig-1",
        operation="rig_health",
        now=101,
    )
    authorized = authorize_riggate_request(
        grants,
        ledger,
        claim,
        data_category="public",
        purpose_code="status_brief",
        purpose="Read exact RigGate health.",
        summary="RigGate provider transport fixture",
        now=102,
    )
    return grants, ledger, grant, authorized


def finished_event(ledger: DataSharingLedger, receipt_id: str):
    rows = [
        row
        for row in ledger.recent_events(100)
        if row["receipt_id"] == receipt_id and row["event_type"] == "finished"
    ]
    check(len(rows) == 1, "T-032 receipt reaches exactly one terminal event")
    return rows[0] if rows else {}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    source = (root / "worker" / "app" / "riggate_provider_transport.py").read_text(encoding="utf-8")
    main_source = (root / "worker" / "app" / "main.py").read_text(encoding="utf-8")
    tools_source = (root / "worker" / "app" / "tools.py").read_text(encoding="utf-8")
    check("PRODUCTION_ACTIVATION = False" in source, "RigGate transport is structurally non-production")
    check("os.getenv(" not in source and "os.environ" not in source, "RigGate transport has no environment discovery")
    check("riggate_provider_transport" not in main_source, "worker startup does not mount RigGate transport")
    check("riggate_provider_transport" not in tools_source, "ToolGate registry does not expose RigGate transport")
    for forbidden in ("wake_execute", "control_execute", "subprocess"):
        check(forbidden not in source, f"RigGate transport carries no {forbidden} authority")

    # Real loopback HTTP execution through the already-claimed T-032/T-038 plan.
    server, thread = start_server()
    try:
        with tempfile.TemporaryDirectory() as td:
            grants, ledger, _, authorized = make_authorized()
            try:
                connection = RigGateConnection(
                    origin=f"http://127.0.0.1:{server.server_address[1]}",
                    token_file=token_file(td),
                    allow_insecure_http=True,
                )
                evidence = execute_riggate_status_read(
                    grants,
                    ledger,
                    authorized,
                    connection,
                    now=121,
                )
                check(server.fixture["hits"] == 1, "RigGate transport issues exactly one provider request")
                check(
                    server.fixture["path"] == "/v1/rigs/render-rig-1/health",
                    "provider request uses exact authorized rig/operation path",
                )
                check(server.fixture["authorization"] == f"Bearer {TOKEN}", "bearer is injected only on provider request")
                check(evidence.rig_id == "render-rig-1" and evidence.state == "ready", "strict wire evidence returns exact rig state")
                event = finished_event(ledger, authorized.sharing_receipt.receipt_id)
                check(event.get("outcome") == "completed", "successful provider read completes T-032 receipt")
                rendered = json.dumps([evidence.to_dict(), *ledger.recent_events(100)], sort_keys=True)
                check(TOKEN not in rendered, "bearer does not enter evidence or T-032 audit")
            finally:
                ledger.close()
                grants.close()
    finally:
        stop_server(server, thread)

    # Redirects are not followed; a 302 is a terminal failed read after one hit.
    server, thread = start_server("redirect")
    try:
        with tempfile.TemporaryDirectory() as td:
            grants, ledger, _, authorized = make_authorized(start=1000)
            try:
                connection = RigGateConnection(
                    origin=f"http://127.0.0.1:{server.server_address[1]}",
                    token_file=token_file(td),
                    allow_insecure_http=True,
                )
                rejects(
                    lambda: execute_riggate_status_read(grants, ledger, authorized, connection, now=122),
                    RigGateTransportError,
                    "redirect response is rejected",
                    "HTTP 200",
                )
                check(server.fixture["hits"] == 1, "redirect rejection performs no second request")
                event = finished_event(ledger, authorized.sharing_receipt.receipt_id)
                check(event.get("outcome") == "failed", "redirect rejection terminalizes T-032 as failed")
            finally:
                ledger.close()
                grants.close()
    finally:
        stop_server(server, thread)

    # Wire substitution cannot relabel another rig as the requested rig.
    server, thread = start_server("substitute")
    try:
        with tempfile.TemporaryDirectory() as td:
            grants, ledger, _, authorized = make_authorized(start=2000)
            try:
                connection = RigGateConnection(
                    origin=f"http://127.0.0.1:{server.server_address[1]}",
                    token_file=token_file(td),
                    allow_insecure_http=True,
                )
                rejects(
                    lambda: execute_riggate_status_read(grants, ledger, authorized, connection, now=123),
                    Exception,
                    "wire rig substitution is rejected",
                )
                event = finished_event(ledger, authorized.sharing_receipt.receipt_id)
                check(event.get("outcome") == "failed", "wire substitution terminalizes T-032 as failed")
            finally:
                ledger.close()
                grants.close()
    finally:
        stop_server(server, thread)

    # Durable scope is checked again before resolver, credential file or transport.
    with tempfile.TemporaryDirectory() as td:
        grants, ledger, grant, authorized = make_authorized(start=3000)
        calls = {"resolver": 0, "transport": 0}

        def resolver_bomb(_host: str, _port: int):
            calls["resolver"] += 1
            raise AssertionError("resolver must not run after revoke")

        class TransportBomb:
            def request(self, *_args, **_kwargs):
                calls["transport"] += 1
                raise AssertionError("transport must not run after revoke")

        try:
            grants.revoke(
                grant.grant_id,
                expected_scope_sha256=grant.scope.digest,
                actor="operator",
                now=124,
            )
            connection = RigGateConnection(
                origin="https://riggate.invalid",
                token_file=token_file(td),
            )
            rejects(
                lambda: execute_riggate_status_read(
                    grants,
                    ledger,
                    authorized,
                    connection,
                    now=125,
                    resolver=resolver_bomb,
                    transport=TransportBomb(),
                ),
                HomeRigDenied,
                "revoked exact scope blocks before any provider I/O",
            )
            check(calls == {"resolver": 0, "transport": 0}, "revoke stops before DNS and transport")
            event = finished_event(ledger, authorized.sharing_receipt.receipt_id)
            check(event.get("outcome") == "blocked", "revoked authority terminalizes T-032 as blocked")
        finally:
            ledger.close()
            grants.close()

    # Plaintext can never be widened to a global peer by DNS resolution.
    with tempfile.TemporaryDirectory() as td:
        grants, ledger, _, authorized = make_authorized(start=4000)
        calls = {"transport": 0}

        class TransportCounter:
            def request(self, *_args, **_kwargs):
                calls["transport"] += 1
                return TransportResponse(200, {"content-type": "application/json"}, b"{}", "8.8.8.8")

        try:
            connection = RigGateConnection(
                origin="http://riggate.example",
                token_file=token_file(td),
                allow_insecure_http=True,
            )
            rejects(
                lambda: execute_riggate_status_read(
                    grants,
                    ledger,
                    authorized,
                    connection,
                    now=126,
                    resolver=lambda _host, _port: ("8.8.8.8",),
                    transport=TransportCounter(),
                ),
                RigGateTransportError,
                "plaintext global peer is rejected before request",
                "global peer",
            )
            check(calls["transport"] == 0, "global plaintext rejection sends no request")
            event = finished_event(ledger, authorized.sharing_receipt.receipt_id)
            check(event.get("outcome") == "failed", "network policy failure terminalizes T-032 as failed")
        finally:
            ledger.close()
            grants.close()

    print(f"\n===== T-038 RIGGATE TRANSPORT: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
