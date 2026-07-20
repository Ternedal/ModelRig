#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


validation = load_module(
    "browser_peer_public_validation_test",
    SCRIPTS / "browser_peer_public_validation.py",
)

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def rejects(fn, expected, name: str, contains: str = "") -> None:
    try:
        fn()
    except expected as exc:
        check(not contains or contains in str(exc), name)
    else:
        check(False, name)


CANDIDATE = {
    "version": "1.58.test",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "branch": "agent/test",
    "working_tree_clean": True,
    "dirty_entries": 0,
    "version_stamps_consistent": True,
    "version_check_detail": None,
}
PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"
RAW_URL = "https://example.com/public-validation?token=private#fragment"
RAW_BODY = b"<html><title>Public validation</title><body>bounded fixture</body></html>"
CHALLENGE_NONCE = "1" * 32


def identity(_root: Path) -> dict:
    return dict(CANDIDATE)


def wire(body: bytes) -> bytes:
    return (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body


class FakeSocket:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.sockaddr = None
        self.sent = bytearray()
        self.closed = False

    def settimeout(self, value) -> None:
        del value

    def connect(self, sockaddr) -> None:
        self.sockaddr = sockaddr

    def getpeername(self):
        return (PUBLIC_V4, self.sockaddr[1])

    def send(self, data: bytes) -> int:
        self.sent.extend(data)
        return len(data)

    def makefile(self, mode, buffering=None):
        del buffering
        assert mode == "rb"
        return io.BytesIO(self.raw)

    def close(self) -> None:
        self.closed = True


class SocketFactory:
    def __init__(self, sock: FakeSocket) -> None:
        self.sock = sock
        self.calls = []

    def __call__(self, family, kind):
        self.calls.append((family, kind))
        if len(self.calls) != 1:
            raise AssertionError("unexpected second socket")
        return self.sock


class FakeTLS:
    def __init__(self) -> None:
        self.names = []

    def wrap_socket(self, sock, *, server_hostname):
        self.names.append(server_hostname)
        return sock


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    validation_dir = root / "validation"
    validation_dir.mkdir()
    plan_path = Path("validation/browser-peer-public-validation-plan.json")
    report_path = Path("validation/browser-peer-public-validation-latest.json")

    # Preparing a plan is offline and serializes no raw URL path/query or challenge.
    original_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("prepare attempted DNS")
    )
    try:
        plan, challenge, approval = validation.prepare_plan(
            RAW_URL,
            plan_path,
            root=root,
            now=100,
            identity_provider=identity,
            nonce_factory=lambda: CHALLENGE_NONCE,
        )
    finally:
        socket.getaddrinfo = original_getaddrinfo
    plan_file = root / plan_path
    plan_json = plan_file.read_text(encoding="utf-8")
    check(plan["schema"] == validation.PLAN_SCHEMA, "prepared plan is versioned")
    check(challenge == f"bpv1_{CHALLENGE_NONCE}", "prepare returns the random challenge once")
    check(validation.APPROVAL_ENV not in plan_json, "plan stores no approval environment value")
    check(challenge not in plan_json, "plan stores only the challenge digest")
    check("/public-validation" not in plan_json, "plan excludes raw URL path")
    check("token=private" not in plan_json, "plan excludes raw URL query")
    check(plan["public_network_contacted"] is False, "prepare declares no public contact")

    resolver_calls = []

    def forbidden_resolver(host, port):
        resolver_calls.append((host, port))
        raise AssertionError("precondition failure reached DNS")

    rejects(
        lambda: validation.execute_plan(
            RAW_URL,
            challenge,
            plan_path,
            report_path,
            execute_public_network=False,
            approval_value=approval,
            root=root,
            now=103,
            identity_provider=identity,
            resolver=forbidden_resolver,
        ),
        validation.PublicValidationError,
        "execute flag is required before DNS",
        "execute-public-network",
    )
    rejects(
        lambda: validation.execute_plan(
            RAW_URL,
            challenge,
            plan_path,
            report_path,
            execute_public_network=True,
            approval_value="permanent-enabled-flag",
            root=root,
            now=103,
            identity_provider=identity,
            resolver=forbidden_resolver,
        ),
        validation.PublicValidationError,
        "generic permanent environment flag is insufficient",
        validation.APPROVAL_ENV,
    )
    rejects(
        lambda: validation.execute_plan(
            RAW_URL,
            "bpv1_" + "2" * 32,
            plan_path,
            report_path,
            execute_public_network=True,
            approval_value=approval,
            root=root,
            now=103,
            identity_provider=identity,
            resolver=forbidden_resolver,
        ),
        validation.PublicValidationError,
        "wrong one-use challenge is rejected before DNS",
        "challenge",
    )
    rejects(
        lambda: validation.execute_plan(
            "https://example.com/different",
            challenge,
            plan_path,
            report_path,
            execute_public_network=True,
            approval_value=approval,
            root=root,
            now=103,
            identity_provider=identity,
            resolver=forbidden_resolver,
        ),
        validation.PublicValidationError,
        "different URL is rejected before DNS",
        "does not match",
    )
    drifted = dict(CANDIDATE, git_sha="c" * 40)
    rejects(
        lambda: validation.execute_plan(
            RAW_URL,
            challenge,
            plan_path,
            report_path,
            execute_public_network=True,
            approval_value=approval,
            root=root,
            now=103,
            identity_provider=lambda _root: drifted,
            resolver=forbidden_resolver,
        ),
        validation.PublicValidationError,
        "candidate drift is rejected before DNS",
        "git_sha",
    )
    rejects(
        lambda: validation.execute_plan(
            RAW_URL,
            challenge,
            plan_path,
            report_path,
            execute_public_network=True,
            approval_value=approval,
            root=root,
            now=100 + validation.PLAN_TTL_SECONDS + 1,
            identity_provider=identity,
            resolver=forbidden_resolver,
        ),
        validation.PublicValidationError,
        "expired plan is rejected before DNS",
        "fresh",
    )
    check(resolver_calls == [], "all failed preconditions avoid DNS")
    check(plan_file.exists(), "failed preconditions do not consume the plan")

    # A valid run consumes the exact plan before DNS and performs one pinned GET.
    sock = FakeSocket(wire(RAW_BODY))
    factory = SocketFactory(sock)
    tls = FakeTLS()
    transport = validation.PinnedBrowserPeerTransport(
        socket_factory=factory,
        ssl_context_factory=lambda: tls,
    )
    observed = []

    def resolver(host, port):
        check(not plan_file.exists(), "plan is consumed before the first DNS call")
        observed.append((host, port))
        return [PUBLIC_V6, PUBLIC_V4]

    result = validation.execute_plan(
        RAW_URL,
        challenge,
        plan_path,
        report_path,
        execute_public_network=True,
        approval_value=approval,
        root=root,
        now=103,
        identity_provider=identity,
        resolver=resolver,
        transport=transport,
    )
    consumed = validation_dir / (
        f"browser-peer-public-validation-plan.consumed-{plan['plan_id']}.json"
    )
    report_file = root / report_path
    report_json = report_file.read_text(encoding="utf-8")
    check(consumed.exists(), "successful validation leaves one consumed plan receipt")
    check(result["passed"] is True, "valid gate produces a passing report")
    check(result["public_network_contacted"] is True, "report records resolver/network entry")
    check(observed == [("example.com", 443)], "resolver receives the exact planned authority")
    check(factory.calls == [(socket.AF_INET, socket.SOCK_STREAM)], "one IPv4 socket is opened")
    check(sock.sockaddr == (PUBLIC_V4, 443), "transport connects to deterministic selected peer")
    check(tls.names == ["example.com"], "TLS SNI preserves planned hostname")
    check(sock.closed, "public validation socket closes after the response")
    check(
        bytes(sock.sent).startswith(b"GET /public-validation?token=private HTTP/1.1\r\n"),
        "wire request targets the exact canonical path and query",
    )
    check(result["dns"]["selected_address"] == PUBLIC_V4, "report records selected peer")
    check(result["transport"]["connected_address"] == PUBLIC_V4, "report records actual peer")
    check(
        result["transport"]["response_body_sha256"]
        == hashlib.sha256(RAW_BODY).hexdigest(),
        "report hashes exact response bytes",
    )
    check(
        result["citation"]["content_sha256"]
        == hashlib.sha256(RAW_BODY).hexdigest(),
        "citation receipt hashes the same committed bytes",
    )
    check("/public-validation" not in report_json, "report excludes raw URL path")
    check("token=private" not in report_json, "report excludes raw URL query")
    check(RAW_BODY.decode() not in report_json, "report excludes response content")
    check(challenge not in report_json, "report excludes one-use challenge")
    check(approval not in report_json, "report excludes approval phrase")
    check(result["production_activation"] is False, "validation cannot activate production")

    replay_resolver_calls = []
    rejects(
        lambda: validation.execute_plan(
            RAW_URL,
            challenge,
            plan_path,
            report_path,
            execute_public_network=True,
            approval_value=approval,
            root=root,
            now=104,
            identity_provider=identity,
            resolver=lambda host, port: replay_resolver_calls.append((host, port)),
            transport=transport,
        ),
        validation.PublicValidationError,
        "consumed plan cannot be replayed",
        "missing",
    )
    check(replay_resolver_calls == [], "replay attempt never reaches DNS")

    # Target and filesystem constraints fail closed during offline preparation.
    for bad_url, label in (
        ("http://example.com/", "plain HTTP is rejected"),
        ("https://example.com:444/", "non-443 HTTPS is rejected"),
        ("https://127.0.0.1/", "IP literal is rejected"),
        ("https://user:pass@example.com/", "URL credentials are rejected"),
        ("https://service.internal/", "internal hostname is rejected"),
    ):
        rejects(
            lambda value=bad_url: validation.prepare_plan(
                value,
                Path(f"validation/{hashlib.sha256(value.encode()).hexdigest()}.json"),
                root=root,
                now=200,
                identity_provider=identity,
                nonce_factory=lambda: "3" * 32,
            ),
            validation.PublicValidationError,
            label,
        )
    rejects(
        lambda: validation.prepare_plan(
            "https://example.com/",
            Path("outside-plan.json"),
            root=root,
            now=200,
            identity_provider=identity,
            nonce_factory=lambda: "3" * 32,
        ),
        validation.PublicValidationError,
        "plan path cannot escape validation directory",
        "validation directory",
    )

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
