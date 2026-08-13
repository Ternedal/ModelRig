from __future__ import annotations

import json
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.data_sharing import DataSharingLedger
from app.home_assistant_local_transport import (
    HomeAssistantLocalEndpoint,
    HomeAssistantLocalTransport,
    HomeAssistantLocalTransportError,
)
from app.home_assistant_state_execution import HomeAssistantStateExecutionError, HomeAssistantStateExecutor
from app.home_assistant_state_request import build_home_assistant_state_request
from app.home_rig_connector_contract import HomeRigAuditLog, HomeRigGrantStore, HomeRigScope
from app.home_rig_read_boundary import prepare_read
from app.home_rig_read_lease import HomeRigReadSharingBoundary


class UUIDs:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


class BearerProvider:
    def __init__(self) -> None:
        self.calls = 0

    def bearer_for_execution(self) -> str:
        self.calls += 1
        return "fixture-access-token"


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:
        fixture = self.server.fixture
        fixture["hits"] += 1
        fixture["path"] = self.path
        fixture["authorization"] = self.headers.get("Authorization")
        fixture["accept"] = self.headers.get("Accept")
        mode = fixture["mode"]
        if mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/must-not-follow")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mode == "oversized":
            payload = b"x" * (128 * 1024 + 64)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payload = json.dumps(
            {
                "entity_id": "sensor.gpu_temp",
                "state": "61.0",
                "attributes": {"friendly_name": "GPU temperature", "canary": "NO_EXPORT"},
                "last_changed": stamp,
                "last_updated": stamp,
            },
            separators=(",", ":"),
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_server(mode: str = "success"):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    server.fixture = {
        "mode": mode,
        "hits": 0,
        "path": None,
        "authorization": None,
        "accept": None,
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def make_execution(transport):
    now = int(time.time())
    grants = HomeRigGrantStore(uuid_factory=UUIDs())
    ledger = DataSharingLedger(uuid_factory=UUIDs())
    audit = HomeRigAuditLog()
    scope = HomeRigScope(entity_ids=("sensor.gpu_temp",), operations=("entity_state",))
    grant = grants.create(scope, actor="operator", now=now)
    claim = prepare_read(
        grants,
        grant.grant_id,
        target_kind="entity",
        target_id="sensor.gpu_temp",
        operation="entity_state",
        now=now,
    )
    sharing = HomeRigReadSharingBoundary(grants, ledger)
    proposal = sharing.propose(claim, now=now)
    ledger.approve(proposal.permission_id, actor="operator", now=now)
    lease = sharing.prepare(
        claim,
        permission_id=proposal.permission_id,
        now=now,
        receipt_ttl_seconds=60,
    )
    executor = HomeAssistantStateExecutor(
        grants=grants,
        sharing=sharing,
        audit=audit,
        transport=transport,
    )
    return now, grants, ledger, audit, claim, lease, executor


def finished(ledger, lease):
    rows = [
        row
        for row in ledger.recent_events(100)
        if row["receipt_id"] == lease.receipt.receipt_id and row["event_type"] == "finished"
    ]
    assert len(rows) == 1, rows
    return rows[0]


def expect_endpoint_denied(address, **kwargs) -> None:
    try:
        HomeAssistantLocalEndpoint(address=address, **kwargs)
    except HomeAssistantLocalTransportError:
        pass
    else:
        raise AssertionError(f"endpoint unexpectedly accepted: {address}")


def main() -> None:
    # No DNS names/public/link-local/ambiguous mapped peers.
    for address in (
        "homeassistant.local",
        "8.8.8.8",
        "169.254.169.254",
        "0.0.0.0",
        "::ffff:127.0.0.1",
        "fe80::1",
    ):
        expect_endpoint_denied(address)

    # Plain HTTP outside loopback requires an explicit operator decision.
    expect_endpoint_denied("192.168.1.20", scheme="http")
    assert HomeAssistantLocalEndpoint(
        address="192.168.1.20",
        scheme="http",
        allow_insecure_http=True,
    ).address == "192.168.1.20"
    assert HomeAssistantLocalEndpoint(address="10.0.0.5", scheme="https").address == "10.0.0.5"
    assert HomeAssistantLocalEndpoint(
        address="100.64.0.9",
        scheme="http",
        allow_insecure_http=True,
    ).address == "100.64.0.9"
    assert HomeAssistantLocalEndpoint(address="fd00::1", scheme="https").address == "fd00::1"

    # Real loopback HTTP fixture through the full T-032 -> T-038 composition.
    server, thread = start_server()
    try:
        provider = BearerProvider()
        endpoint = HomeAssistantLocalEndpoint(
            address="127.0.0.1",
            port=server.server_address[1],
            scheme="http",
        )
        transport = HomeAssistantLocalTransport(
            endpoint=endpoint,
            bearer_provider=provider,
            timeout_seconds=5,
        )
        now, grants, ledger, audit, claim, lease, executor = make_execution(transport)
        result = executor.execute(lease, claim, now=now)
        assert server.fixture["hits"] == 1
        assert server.fixture["path"] == "/api/states/sensor.gpu_temp"
        assert server.fixture["authorization"] == "Bearer fixture-access-token"
        assert server.fixture["accept"] == "application/json"
        assert provider.calls == 1
        assert not hasattr(transport, "_bearer")
        assert result.read_receipt.observation.state == "61.0"
        assert result.read_receipt.observation.freshness == "fresh"
        rendered = json.dumps(result.to_dict(), sort_keys=True)
        events = json.dumps(ledger.recent_events(100), sort_keys=True)
        audit_rows = json.dumps(audit.recent(), sort_keys=True)
        for value in (rendered, events, audit_rows):
            assert "fixture-access-token" not in value
            assert "NO_EXPORT" not in value
        event = finished(ledger, lease)
        assert event["outcome"] == "completed"
        assert 1 <= event["bytes_sent"] <= 4096
        audit.close(); ledger.close(); grants.close()
    finally:
        stop_server(server, thread)

    # 302 is returned as data; there is no redirect following or second request.
    server, thread = start_server("redirect")
    try:
        provider = BearerProvider()
        transport = HomeAssistantLocalTransport(
            endpoint=HomeAssistantLocalEndpoint(
                address="127.0.0.1",
                port=server.server_address[1],
            ),
            bearer_provider=provider,
        )
        now, grants, ledger, audit, claim, lease, executor = make_execution(transport)
        try:
            executor.execute(lease, claim, now=now)
        except HomeAssistantStateExecutionError:
            pass
        else:
            raise AssertionError("redirect response was accepted")
        assert server.fixture["hits"] == 1
        event = finished(ledger, lease)
        assert event["outcome"] == "failed" and event["error_code"] == "provider_status"
        audit.close(); ledger.close(); grants.close()
    finally:
        stop_server(server, thread)

    # Oversized response is cut at the transport boundary and never parsed.
    server, thread = start_server("oversized")
    try:
        provider = BearerProvider()
        transport = HomeAssistantLocalTransport(
            endpoint=HomeAssistantLocalEndpoint(
                address="127.0.0.1",
                port=server.server_address[1],
            ),
            bearer_provider=provider,
        )
        now, grants, ledger, audit, claim, lease, executor = make_execution(transport)
        try:
            executor.execute(lease, claim, now=now)
        except HomeAssistantStateExecutionError:
            pass
        else:
            raise AssertionError("oversized response was accepted")
        assert server.fixture["hits"] == 1
        event = finished(ledger, lease)
        assert event["outcome"] == "failed" and event["error_code"] == "response_too_large"
        audit.close(); ledger.close(); grants.close()
    finally:
        stop_server(server, thread)

    # Connect failure occurs before request bytes can leave; exact count is zero.
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    unused_port = blocker.getsockname()[1]
    try:
        provider = BearerProvider()
        transport = HomeAssistantLocalTransport(
            endpoint=HomeAssistantLocalEndpoint(address="127.0.0.1", port=unused_port),
            bearer_provider=provider,
            timeout_seconds=1,
        )
        now, grants, ledger, audit, claim, lease, executor = make_execution(transport)
        plan = build_home_assistant_state_request(grants, lease, claim, now=now)
        result = transport.execute(plan)
        assert result.error_code == "transport_io"
        assert result.request_bytes_sent == 0
        audit.close(); ledger.close(); grants.close()
    finally:
        blocker.close()

    print("T-038 local Home Assistant transport fixture: PASS")


if __name__ == "__main__":
    main()
