from __future__ import annotations

import io
import socket
import ssl

from app.pinned_http_transport import PinnedHttpTransport
from app.research_contract import ReadOnlyBrowserPolicy
from app.web_fetch import DeterministicWebFetcher, WebFetchError

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def rejects(fn, name: str, contains: str = "") -> None:
    try:
        fn()
    except WebFetchError as exc:
        check(not contains or contains in str(exc), name)
    else:
        check(False, name)


class FakeSocket:
    def __init__(self, wire: bytes, *, peer: str = "1.1.1.1", connect_error=None) -> None:
        self.wire = wire
        self.peer = peer
        self.connect_error = connect_error
        self.timeout = None
        self.sockaddr = None
        self.sent = b""
        self.closed = False

    def settimeout(self, value) -> None:
        self.timeout = value

    def connect(self, sockaddr) -> None:
        self.sockaddr = sockaddr
        if self.connect_error:
            raise self.connect_error

    def getpeername(self):
        return (self.peer, self.sockaddr[1])

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def makefile(self, mode, buffering=None):
        assert mode == "rb"
        return io.BytesIO(self.wire)

    def close(self) -> None:
        self.closed = True


class SocketFactory:
    def __init__(self, *sockets: FakeSocket) -> None:
        self.sockets = list(sockets)
        self.calls = []

    def __call__(self, family, kind):
        self.calls.append((family, kind))
        return self.sockets.pop(0)


class FakeTLSContext:
    def __init__(self, *, error=None) -> None:
        self.error = error
        self.server_names = []

    def wrap_socket(self, sock, *, server_hostname):
        self.server_names.append(server_hostname)
        if self.error:
            raise self.error
        return sock


def wire(status="200 OK", headers=(), body=b""):
    lines = [f"HTTP/1.1 {status}"]
    lines.extend(f"{name}: {value}" for name, value in headers)
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


def make_transport(sock: FakeSocket, context=None):
    factory = SocketFactory(sock)
    tls = context or FakeTLSContext()
    return (
        PinnedHttpTransport(
            socket_factory=factory,
            ssl_context_factory=lambda: tls,
        ),
        factory,
        tls,
    )


sock = FakeSocket(wire(
    headers=(("Content-Type", "text/plain"), ("Content-Length", "5")),
    body=b"hello",
))
transport, factory, tls = make_transport(sock)
result = transport.request(
    "https://Example.com:443/a b?q=hello world",
    connect_address="1.1.1.1",
    headers={"user-agent": "ModelRig-WebFetch/1.0", "accept": "text/plain"},
    timeout_seconds=3.5,
    max_wire_bytes=10,
)
check(result.status == 200 and result.body == b"hello", "HTTP response is parsed")
check(result.connected_address == "1.1.1.1", "actual peer address is returned")
check(factory.calls == [(socket.AF_INET, socket.SOCK_STREAM)], "IPv4 socket is selected")
check(sock.sockaddr == ("1.1.1.1", 443), "socket connects to exact pinned address")
check(sock.timeout == 3.5, "timeout is applied")
check(tls.server_names == ["example.com"], "TLS SNI keeps the URL host")
check(sock.sent.startswith(b"GET /a%20b?q=hello%20world HTTP/1.1\r\n"), "request target is encoded")
check(b"Host: example.com\r\n" in sock.sent, "Host header keeps URL authority")
check(b"Connection: close\r\n" in sock.sent, "connection is single-use")
check(b"authorization:" not in sock.sent.lower() and b"cookie:" not in sock.sent.lower(), "no credentials are imported")
check(sock.closed, "socket is closed after success")

plain = FakeSocket(wire("302 Found", (("Location", "/next"),), b""), peer="8.8.8.8")
plain_transport, _, plain_tls = make_transport(plain)
redirect = plain_transport.request(
    "http://example.com:8080/start",
    connect_address="8.8.8.8",
    headers={},
    timeout_seconds=2,
    max_wire_bytes=1,
)
check(redirect.status == 302 and redirect.headers["location"] == "/next", "redirect is returned, not followed")
check(plain_tls.server_names == [], "plain HTTP does not invoke TLS")
check(b"Host: example.com:8080\r\n" in plain.sent, "non-default port is included in Host")

ipv6 = FakeSocket(
    wire(headers=(("Content-Type", "text/plain"),), body=b"x"),
    peer="2606:4700:4700::1111",
)
ipv6_transport, ipv6_factory, _ = make_transport(ipv6)
ipv6_result = ipv6_transport.request(
    "https://example.com/x",
    connect_address="2606:4700:4700::1111",
    headers={},
    timeout_seconds=2,
    max_wire_bytes=2,
)
check(ipv6_factory.calls[0][0] == socket.AF_INET6, "IPv6 socket family is selected")
check(ipv6.sockaddr == ("2606:4700:4700::1111", 443, 0, 0), "IPv6 connects numerically")
check(ipv6_result.connected_address == "2606:4700:4700::1111", "IPv6 peer is canonicalized")

chunked = FakeSocket(wire(
    headers=(("Transfer-Encoding", "chunked"), ("Content-Type", "text/plain")),
    body=b"5\r\nhello\r\n0\r\n\r\n",
))
chunked_transport, _, _ = make_transport(chunked)
chunked_result = chunked_transport.request(
    "https://example.com/x",
    connect_address="1.1.1.1",
    headers={},
    timeout_seconds=2,
    max_wire_bytes=5,
)
check(chunked_result.body == b"hello", "stdlib decodes transfer framing")

cases = [
    ("non-numeric peer is rejected", "https://example.com/", "not-an-ip", {}, FakeSocket(b""), "numeric IP"),
    ("caller Host header is forbidden", "https://example.com/", "1.1.1.1", {"host": "evil"}, FakeSocket(b""), "forbidden"),
    ("caller Cookie header is forbidden", "https://example.com/", "1.1.1.1", {"Cookie": "secret"}, FakeSocket(b""), "forbidden"),
    ("header injection is rejected", "https://example.com/", "1.1.1.1", {"x": "ok\r\nbad"}, FakeSocket(b""), "invalid"),
    ("URL credentials are rejected", "https://user:pass@example.com/", "1.1.1.1", {}, FakeSocket(b""), "credentials"),
    (
        "oversized body is stopped",
        "https://example.com/",
        "1.1.1.1",
        {},
        FakeSocket(wire(headers=(("Content-Type", "text/plain"),), body=b"abcdef")),
        "max_wire_bytes",
    ),
    (
        "duplicate Content-Length is rejected",
        "https://example.com/",
        "1.1.1.1",
        {},
        FakeSocket(wire(headers=(("Content-Length", "1"), ("Content-Length", "1")), body=b"x")),
        "singleton",
    ),
    (
        "Content-Length plus Transfer-Encoding is rejected",
        "https://example.com/",
        "1.1.1.1",
        {},
        FakeSocket(wire(headers=(("Content-Length", "1"), ("Transfer-Encoding", "chunked")), body=b"0\r\n\r\n")),
        "mixed",
    ),
    (
        "unsupported Transfer-Encoding is rejected",
        "https://example.com/",
        "1.1.1.1",
        {},
        FakeSocket(wire(headers=(("Transfer-Encoding", "gzip"),), body=b"x")),
        "unsupported",
    ),
]

for name, url, address, headers, case_sock, expected in cases:
    case_transport, _, _ = make_transport(case_sock)
    rejects(
        lambda t=case_transport, u=url, a=address, h=headers: t.request(
            u,
            connect_address=a,
            headers=h,
            timeout_seconds=2,
            max_wire_bytes=5,
        ),
        name,
        expected,
    )

cert_sock = FakeSocket(b"")
cert_context = FakeTLSContext(error=ssl.SSLCertVerificationError("private detail"))
cert_transport, _, _ = make_transport(cert_sock, cert_context)
rejects(
    lambda: cert_transport.request(
        "https://example.com/",
        connect_address="1.1.1.1",
        headers={},
        timeout_seconds=2,
        max_wire_bytes=5,
    ),
    "certificate errors are normalized",
    "certificate verification failed",
)
check(cert_sock.closed, "raw socket closes after TLS failure")

timeout_sock = FakeSocket(b"", connect_error=socket.timeout("private detail"))
timeout_transport, _, _ = make_transport(timeout_sock)
rejects(
    lambda: timeout_transport.request(
        "https://example.com/",
        connect_address="1.1.1.1",
        headers={},
        timeout_seconds=2,
        max_wire_bytes=5,
    ),
    "socket timeouts are normalized",
    "transport timeout",
)
check(timeout_sock.closed, "socket closes after timeout")

end_sock = FakeSocket(wire(
    headers=(("Content-Type", "text/html; charset=utf-8"),),
    body=b"<html><title>Pinned</title><body>Trusted body</body></html>",
))
end_transport, _, _ = make_transport(end_sock)
trace = DeterministicWebFetcher(
    end_transport,
    resolver=lambda host, port: ("1.1.1.1",),
).fetch(
    "https://example.com/report",
    ReadOnlyBrowserPolicy(
        allowed_domains=("example.com",),
        max_source_bytes=4096,
        timeout_seconds=10,
    ),
)
check(trace.receipt.title == "Pinned", "transport composes with fetch engine")
check("Trusted body" in trace.receipt.excerpt, "end-to-end receipt uses fetched entity")
check(trace.receipt.adapter == "deterministic-web-fetch", "adapter identity stays stable")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
