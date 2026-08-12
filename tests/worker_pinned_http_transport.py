from __future__ import annotations

import io
import json
import os
import socket
import ssl
import tempfile
import uuid
from pathlib import Path

from app.github_connector_client import (
    GitHubReadRemoteError,
    GitHubTransportRequest,
)
from app.github_connector_contract import (
    GitHubConnectorDenied,
    GitHubConnectorGrantStore,
    GitHubConnectorScope,
)
from app.github_connector_transport import (
    AccountBoundGitHubReadClient,
    EnvironmentFileGitHubCredentialProvider,
    FileGitHubCredentialProvider,
    GitHubCredentialError,
    GitHubPinnedTransport,
)
from app.pinned_http_transport import PinnedHttpTransport
from app.research_contract import ReadOnlyBrowserPolicy
from app.web_fetch import DeterministicWebFetcher, TransportResponse, WebFetchError

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


def rejects_type(fn, expected, name: str, contains: str = "") -> None:
    try:
        fn()
    except expected as exc:
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
    ("caller Authorization header is forbidden", "https://example.com/", "1.1.1.1", {"Authorization": "Bearer model-data"}, FakeSocket(b""), "forbidden"),
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

# T-036 trusted bearer seam. Public/untrusted headers are still closed, while a
# connector-loaded secret can be appended only through the explicit method.
bearer = "github_pat_fixture_1234567890"
auth_sock = FakeSocket(wire(headers=(("Content-Type", "application/json"),), body=b"{}"))
auth_transport, auth_factory, _ = make_transport(auth_sock)
auth_transport.request_with_trusted_bearer(
    "https://api.github.com/repos/ternedal/modelrig",
    connect_address="1.1.1.1",
    headers={"accept": "application/vnd.github+json"},
    bearer_token=bearer,
    timeout_seconds=2,
    max_wire_bytes=64,
)
check(b"Authorization: Bearer " + bearer.encode("ascii") + b"\r\n" in auth_sock.sent, "trusted bearer is injected at pinned transport only")
check(bearer.encode("ascii") not in b"application/vnd.github+json", "bearer is separate from ordinary request headers")

invalid_bearer_sock = FakeSocket(b"")
invalid_bearer_transport, invalid_bearer_factory, _ = make_transport(invalid_bearer_sock)
rejects(
    lambda: invalid_bearer_transport.request_with_trusted_bearer(
        "https://api.github.com/",
        connect_address="1.1.1.1",
        headers={},
        bearer_token="short",
        timeout_seconds=2,
        max_wire_bytes=64,
    ),
    "invalid trusted bearer fails closed",
    "length",
)
check(invalid_bearer_factory.calls == [], "invalid bearer opens no socket")

with tempfile.TemporaryDirectory() as temp:
    token_path = Path(temp) / "github.token"
    token_path.write_text(bearer + "\n", encoding="ascii")
    if os.name == "posix":
        token_path.chmod(0o600)
    provider = FileGitHubCredentialProvider(account="Ternedal", token_file=token_path)
    check(provider.account == "ternedal", "credential provider canonicalizes account")
    check(provider.bearer_token() == bearer, "credential provider loads token on demand")
    check(bearer not in repr(provider), "credential provider repr does not expose bearer")

    env_provider = EnvironmentFileGitHubCredentialProvider(
        {"KALIV_GITHUB_ACCOUNT": "TERNEDAL", "KALIV_GITHUB_TOKEN_FILE": str(token_path)}
    )
    check(env_provider.account == "ternedal", "environment config carries account, not token")
    check(env_provider.bearer_token() == bearer, "environment file provider resolves configured secret file")

    if os.name == "posix":
        token_path.chmod(0o644)
        rejects_type(
            provider.bearer_token,
            GitHubCredentialError,
            "POSIX credential file rejects group/world-readable permissions",
            "permissions",
        )
        token_path.chmod(0o600)

    class CapturingPinned:
        def __init__(self, *, peer="1.1.1.1"):
            self.peer = peer
            self.calls = []

        def request_with_trusted_bearer(self, url, **kwargs):
            self.calls.append((url, kwargs))
            document = {"id": 1287914122, "full_name": "Ternedal/ModelRig"}
            return TransportResponse(
                status=200,
                headers={
                    "etag": 'W/"github-fixture-v1"',
                    "x-ratelimit-remaining": "4999",
                    "x-ratelimit-reset": "2000",
                },
                body=json.dumps(document, separators=(",", ":")).encode(),
                connected_address=self.peer,
            )

    pinned = CapturingPinned()
    github_transport = GitHubPinnedTransport(
        credentials=provider,
        resolver=lambda host, port: ("8.8.8.8", "1.1.1.1", "1.1.1.1"),
        transport=pinned,
        timeout_seconds=7,
    )
    request = GitHubTransportRequest(
        path="/repos/ternedal/modelrig",
        headers=(
            ("accept", "application/vnd.github+json"),
            ("x-github-api-version", "2022-11-28"),
        ),
        max_response_bytes=4096,
    )
    gh_response = github_transport.get(request)
    url, call = pinned.calls[0]
    check(url == "https://api.github.com/repos/ternedal/modelrig", "GitHub adapter never changes fixed API origin")
    check(call["connect_address"] == "1.1.1.1", "GitHub adapter deterministically pins first public DNS address")
    check(call["bearer_token"] == bearer, "bearer crosses only trusted transport seam")
    check("authorization" not in call["headers"], "GitHub client headers still contain no Authorization")
    check(call["timeout_seconds"] == 7 and call["max_wire_bytes"] == 4096, "GitHub adapter preserves bounded execution settings")
    check(gh_response.status == 200, "GitHub adapter maps pinned response without following redirects")

    rejects_type(
        lambda: GitHubPinnedTransport(
            credentials=provider,
            resolver=lambda host, port: ("127.0.0.1",),
            transport=CapturingPinned(),
        ).get(request),
        GitHubReadRemoteError,
        "GitHub adapter rejects non-public DNS answers before socket",
        "non-public",
    )

    wrong_peer = CapturingPinned(peer="8.8.8.8")
    rejects_type(
        lambda: GitHubPinnedTransport(
            credentials=provider,
            resolver=lambda host, port: ("1.1.1.1",),
            transport=wrong_peer,
        ).get(request),
        GitHubReadRemoteError,
        "GitHub adapter rejects peer mismatch after pinned connect",
        "did not match",
    )

    # Account-bound facade proves a grant for another credential account cannot
    # reach DNS, credential loading or transport.
    grant_ids = iter((uuid.UUID(int=99), uuid.UUID(int=100)))
    grants = GitHubConnectorGrantStore(":memory:", uuid_factory=lambda: next(grant_ids))
    matching = grants.create(
        GitHubConnectorScope(
            account="Ternedal",
            repositories=("Ternedal/ModelRig",),
            operations=("repository",),
        ),
        actor="Anders",
        now=1,
    )
    runtime_pinned = CapturingPinned()
    runtime_transport = GitHubPinnedTransport(
        credentials=provider,
        resolver=lambda host, port: ("1.1.1.1",),
        transport=runtime_pinned,
    )
    runtime = AccountBoundGitHubReadClient(grants=grants, transport=runtime_transport)
    runtime_result = runtime.read(
        matching.grant_id,
        repository="Ternedal/ModelRig",
        operation="repository",
        now=2,
    )
    check(runtime_result.source.repository_id == 1287914122, "account-bound runtime composes grant + pinned transport + source")
    check(len(runtime_pinned.calls) == 1, "matching account reaches pinned transport exactly once")

    wrong = grants.create(
        GitHubConnectorScope(
            account="OtherAccount",
            repositories=("Ternedal/ModelRig",),
            operations=("repository",),
        ),
        actor="Anders",
        now=3,
    )
    before = len(runtime_pinned.calls)
    rejects_type(
        lambda: runtime.read(
            wrong.grant_id,
            repository="Ternedal/ModelRig",
            operation="repository",
            now=4,
        ),
        GitHubConnectorDenied,
        "grant account must match configured GitHub credential",
        "account",
    )
    check(len(runtime_pinned.calls) == before, "account mismatch makes zero transport calls")
    grants.close()

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)