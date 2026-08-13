from __future__ import annotations

import ast
import io
import os
import socket
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "worker"))

from app.pinned_http_transport import PinnedHttpTransport  # noqa: E402
from app.read_connector_package_contract import ReadConnectorScope  # noqa: E402
from app.read_connector_provider_execution import exact_request_sha256  # noqa: E402
from app.read_connector_provider_network_transport import (  # noqa: E402
    ProviderNetworkTransportError,
    ReadConnectorPinnedProviderTransport,
)
from app.read_connector_provider_request import (  # noqa: E402
    build_drive_file_metadata,
    build_notion_search,
)
from app.web_fetch import TransportResponse, WebFetchError  # noqa: E402

passed = failed = 0


def check(cond: bool, label: str) -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def raises(exc_type, fn, contains: str = "") -> bool:
    try:
        fn()
    except exc_type as exc:
        return not contains or contains in str(exc)
    return False


class FakeSocket:
    def __init__(self, wire: bytes, *, peer: str = "1.1.1.1") -> None:
        self.wire = wire
        self.peer = peer
        self.timeout = None
        self.sockaddr = None
        self.sent = b""
        self.closed = False

    def settimeout(self, value) -> None:
        self.timeout = value

    def connect(self, sockaddr) -> None:
        self.sockaddr = sockaddr

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
    def __init__(self) -> None:
        self.server_names = []

    def wrap_socket(self, sock, *, server_hostname):
        self.server_names.append(server_hostname)
        return sock


def wire(status="200 OK", headers=(), body=b"") -> bytes:
    lines = [f"HTTP/1.1 {status}"]
    lines.extend(f"{name}: {value}" for name, value in headers)
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


def scope(connector: str, object_scope: str, operation: str) -> ReadConnectorScope:
    return ReadConnectorScope(
        connector=connector,
        account_ref=f"acct-{connector}",
        workspace_ref="workspace-main" if connector == "notion" else None,
        object_scopes=(object_scope,),
        operations=(operation,),
    )


def main() -> int:
    request_path = os.path.join(ROOT, "worker", "app", "read_connector_provider_request.py")
    network_path = os.path.join(ROOT, "worker", "app", "read_connector_provider_network_transport.py")
    pinned_path = os.path.join(ROOT, "worker", "app", "pinned_http_transport.py")
    request_source = open(request_path, encoding="utf-8").read()
    network_source = open(network_path, encoding="utf-8").read()
    pinned_source = open(pinned_path, encoding="utf-8").read()
    tree = ast.parse(request_source)

    imported: set[str] = set()
    imported_full: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".", 1)[0])
                imported_full.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
            imported_full.add(node.module)

    check(
        {"socket", "ssl", "subprocess", "requests", "httpx", "aiohttp"}.isdisjoint(imported),
        "provider request authority imports no network/process client",
    )
    check(
        "urllib.request" not in imported_full,
        "urllib is used only for deterministic URL encoding, never network I/O",
    )
    check("os" not in imported, "provider request authority cannot read environment configuration")

    for needle in (
        "os.getenv(", "os.environ", "Bearer ", "requests.", "httpx.", "aiohttp.",
        "urlopen(", "socket.", "subprocess.", "FastAPI(", "APIRouter(", "REGISTRY[",
        "ToolGate", "chat_tools(",
    ):
        check(needle not in request_source, f"provider request authority remains dormant: no {needle}")

    check(
        '"authorization"' in request_source.casefold()
        and "_CREDENTIAL_HEADERS" in request_source
        and "cannot contain credential headers" in request_source,
        "credential header names exist only as an explicit deny boundary",
    )
    check('PRODUCTION_ACTIVATION = False' in request_source, "provider request module pins production activation false")
    check('credential_mode: str = "bearer_injected_at_execute"' in request_source, "credential material is structurally deferred to executor")
    check('follow_redirects: bool = False' in request_source, "provider request plans structurally disable redirects")

    methods: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name != "ProviderRequestPlan":
            continue
        for kw in node.keywords:
            if kw.arg == "method" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                methods.add(kw.value.value)
    check(methods <= {"GET", "POST"}, "all statically-declared request methods are GET or read-semantic POST")
    check('if self.method == "POST":' in request_source, "POST plans have a dedicated validation branch")
    check('if self.connector != "notion":' in request_source, "POST is structurally Notion-only in v1")
    check('/v1/search' in request_source and '/query' in request_source, "Notion read-semantic POST endpoints are closed and explicit")
    check('api.notion.com' in request_source and 'gmail.googleapis.com' in request_source and 'www.googleapis.com' in request_source, "provider hosts are source-fixed constants")
    check('evil.example' not in request_source, "no arbitrary provider host fixture leaks into production authority")
    check('operation="database_query"' in request_source, "stable T-037 v1 logical Notion database_query authority remains represented")
    check('provider_operation="data_source_query"' in request_source, "stable Notion authority maps explicitly to current data-source API")
    check('/v1/data_sources/' in request_source, "current Notion data-source query path is pinned")
    check('operation="document_read"' in request_source, "Drive document read performs its own exact authority check")
    doc_start = request_source.index("def build_drive_document_read(")
    doc_end = request_source.index("\ndef build_gmail_message_search(", doc_start)
    doc_source = request_source[doc_start:doc_end]
    check("build_drive_file_metadata(" not in doc_source, "Drive document read does not silently require metadata authority")
    check('mimeType", "text/plain"' in doc_source, "Drive v1 document read cannot choose arbitrary export MIME")
    check('/gmail/v1/users/me/messages' in request_source and '/gmail/v1/users/me/threads' in request_source, "Gmail identity is fixed to authenticated users/me")
    check('("format", "full")' in request_source and '"raw"' not in request_source, "Gmail request plans never request raw message format")

    for needle in (
        "os.getenv(", "os.environ", "subprocess.", "requests.", "httpx.", "aiohttp.",
        "FastAPI(", "APIRouter(", "include_router", "ToolGate", "REGISTRY[", "production_activation = True",
    ):
        check(needle not in network_source, f"provider network transport has no activation/config seam: {needle}")
    check("default_resolver" in network_source and "parsed.is_global" in network_source, "provider transport resolves and rejects non-public DNS answers")
    check("PinnedHttpTransport" in network_source and "request_with_trusted_bearer_request" in network_source, "provider transport reuses the pinned TLS/socket boundary")
    check("exact_request_sha256(plan)" in network_source, "provider transport rebinds the immutable request digest before DNS/I/O")
    check("connected != selected" in network_source, "provider transport verifies connected peer equals selected DNS address")
    check('PRODUCTION_ACTIVATION = False' in network_source, "provider network transport stays structurally dormant")

    check("def request_with_trusted_bearer_request(" in pinned_source, "pinned transport exposes one explicit trusted GET/POST seam")
    public_start = pinned_source.index("    def request(")
    public_end = pinned_source.index("    def request_with_trusted_bearer(", public_start)
    check('method="GET"' in pinned_source[public_start:public_end], "ordinary public pinned transport remains GET-only")
    github_start = pinned_source.index("    def request_with_trusted_bearer(")
    github_end = pinned_source.index("    def request_with_trusted_bearer_request(", github_start)
    check('method="GET"' in pinned_source[github_start:github_end], "existing T-036 trusted bearer compatibility seam remains GET-only")
    check("_MAX_TRUSTED_BODY_BYTES = 32 * 1024" in pinned_source, "trusted POST body has a 32 KiB transport ceiling")
    check('method not in {"GET", "POST"}' in pinned_source, "trusted method surface is closed to GET/POST")

    post_body = b'{"query":"ModelRig"}'
    post_sock = FakeSocket(wire(headers=(("Content-Type", "application/json"),), body=b"{}"))
    post_factory = SocketFactory(post_sock)
    tls = FakeTLSContext()
    low_level = PinnedHttpTransport(
        socket_factory=post_factory,
        ssl_context_factory=lambda: tls,
    )
    post_result = low_level.request_with_trusted_bearer_request(
        "https://api.notion.com/v1/search",
        method="POST",
        body=post_body,
        connect_address="1.1.1.1",
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "notion-version": "2026-03-11",
        },
        bearer_token="notion-secret-token-1234567890abcd",
        timeout_seconds=5,
        max_wire_bytes=128,
    )
    check(post_result.status == 200 and post_result.body == b"{}", "trusted POST receives one bounded response")
    check(post_sock.sent.startswith(b"POST /v1/search HTTP/1.1\r\n"), "trusted POST emits exact POST request line")
    check(f"Content-Length: {len(post_body)}\r\n".encode() in post_sock.sent, "trusted POST owns exact Content-Length framing")
    check(post_sock.sent.endswith(b"\r\n\r\n" + post_body), "trusted POST sends exact reviewed body bytes")
    check(b"Authorization: Bearer notion-secret-token-1234567890abcd\r\n" in post_sock.sent, "bearer enters only pinned wire request")
    check(tls.server_names == ["api.notion.com"], "trusted POST preserves provider host for TLS SNI")
    check(post_sock.closed, "trusted POST socket closes after one exchange")

    blocked_factory = SocketFactory(FakeSocket(b""))
    blocked_transport = PinnedHttpTransport(
        socket_factory=blocked_factory,
        ssl_context_factory=lambda: FakeTLSContext(),
    )
    check(
        raises(
            WebFetchError,
            lambda: blocked_transport.request_with_trusted_bearer_request(
                "https://api.notion.com/v1/search",
                method="PUT",
                body=post_body,
                connect_address="1.1.1.1",
                headers={},
                bearer_token="notion-secret-token-1234567890abcd",
                timeout_seconds=5,
                max_wire_bytes=128,
            ),
            "GET or POST",
        ),
        "unsupported trusted method fails before socket open",
    )
    check(blocked_factory.calls == [], "unsupported trusted method causes zero network side effects")

    class CapturingPinned:
        def __init__(self, *, peer="1.1.1.1", fail=False) -> None:
            self.peer = peer
            self.fail = fail
            self.calls = []

        def request_with_trusted_bearer_request(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if self.fail:
                raise WebFetchError("secret provider detail must not escape")
            return TransportResponse(
                status=200,
                headers={"content-type": "application/json"},
                body=b"{}",
                connected_address=self.peer,
            )

    drive_scope = scope("google_drive", "file-1", "file_metadata")
    drive_plan = build_drive_file_metadata(drive_scope, file_id="file-1")
    capturing = CapturingPinned()
    adapter = ReadConnectorPinnedProviderTransport(
        resolver=lambda host, port: ("8.8.8.8", "1.1.1.1", "1.1.1.1"),
        transport=capturing,
    )
    drive_digest = exact_request_sha256(drive_plan)
    drive_exchange = adapter.execute(
        drive_plan,
        bearer_token="google-secret-token-1234567890abcdef",
        request_sha256=drive_digest,
        timeout_seconds=7,
    )
    check(len(capturing.calls) == 1, "provider adapter performs exactly one pinned transport call")
    drive_url, drive_kwargs = capturing.calls[0]
    check(drive_url == drive_plan.url and drive_kwargs["method"] == "GET", "Google plan maps exactly to reviewed GET URL/method")
    check(drive_kwargs["connect_address"] == "1.1.1.1", "provider adapter deterministically selects lowest public DNS address")
    check(drive_kwargs["body"] is None, "Google GET cannot acquire a request body in transport")
    check(drive_exchange.request_sha256 == drive_digest and drive_exchange.host == drive_plan.host, "transport response binds exact request digest and host")

    notion_scope = scope("notion", "workspace-search", "search")
    notion_plan = build_notion_search(
        notion_scope,
        object_scope="workspace-search",
        query_text="ModelRig",
    )
    notion_capture = CapturingPinned()
    notion_adapter = ReadConnectorPinnedProviderTransport(
        resolver=lambda host, port: ("1.1.1.1",),
        transport=notion_capture,
    )
    notion_digest = exact_request_sha256(notion_plan)
    notion_adapter.execute(
        notion_plan,
        bearer_token="notion-secret-token-1234567890abcd",
        request_sha256=notion_digest,
        timeout_seconds=7,
    )
    _, notion_kwargs = notion_capture.calls[0]
    check(notion_kwargs["method"] == "POST", "Notion read-semantic search maps to trusted POST")
    check(notion_kwargs["body"] == notion_plan.body_json.encode("utf-8"), "Notion transport sends exact canonical plan body")
    check(notion_kwargs["headers"]["Content-Type"] == "application/json", "Notion transport preserves reviewed content type")

    no_io = CapturingPinned()
    bad_dns = ReadConnectorPinnedProviderTransport(
        resolver=lambda host, port: ("1.1.1.1", "127.0.0.1"),
        transport=no_io,
    )
    check(
        raises(
            ProviderNetworkTransportError,
            lambda: bad_dns.execute(
                drive_plan,
                bearer_token="google-secret-token-1234567890abcdef",
                request_sha256=drive_digest,
                timeout_seconds=7,
            ),
            "non-public",
        ),
        "one private DNS answer poisons the whole provider resolution",
    )
    check(no_io.calls == [], "non-public DNS fails before pinned transport receives bearer/request")

    mismatch = CapturingPinned(peer="8.8.8.8")
    mismatch_adapter = ReadConnectorPinnedProviderTransport(
        resolver=lambda host, port: ("1.1.1.1",),
        transport=mismatch,
    )
    check(
        raises(
            ProviderNetworkTransportError,
            lambda: mismatch_adapter.execute(
                drive_plan,
                bearer_token="google-secret-token-1234567890abcdef",
                request_sha256=drive_digest,
                timeout_seconds=7,
            ),
            "peer did not match",
        ),
        "connected peer drift fails closed after one exchange",
    )

    secret = "google-secret-token-1234567890abcdef"
    failing = CapturingPinned(fail=True)
    failing_adapter = ReadConnectorPinnedProviderTransport(
        resolver=lambda host, port: ("1.1.1.1",),
        transport=failing,
    )
    try:
        failing_adapter.execute(
            drive_plan,
            bearer_token=secret,
            request_sha256=drive_digest,
            timeout_seconds=7,
        )
    except ProviderNetworkTransportError as exc:
        check(secret not in str(exc) and "secret provider detail" not in str(exc), "provider network errors collapse without secret/private exception echo")
    else:
        check(False, "provider network errors collapse without secret/private exception echo")
    check(len(failing.calls) == 1, "provider network adapter does not retry failed transport")

    digest_guard = CapturingPinned()
    digest_adapter = ReadConnectorPinnedProviderTransport(
        resolver=lambda host, port: ("1.1.1.1",),
        transport=digest_guard,
    )
    check(
        raises(
            ProviderNetworkTransportError,
            lambda: digest_adapter.execute(
                drive_plan,
                bearer_token=secret,
                request_sha256="0" * 64,
                timeout_seconds=7,
            ),
            "digest",
        ),
        "stale/tampered request digest fails before DNS/I/O",
    )
    check(digest_guard.calls == [], "request digest mismatch causes zero transport side effects")

    print(f"\n===== T-037 PROVIDER REQUEST/NETWORK BOUNDARY: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
