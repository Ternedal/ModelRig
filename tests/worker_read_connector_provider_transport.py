from __future__ import annotations

import io
import json
import os
import socket
import tempfile
from pathlib import Path

from app.read_connector_package_contract import (
    ReadConnectorDenied,
    ReadConnectorGrantStore,
    ReadConnectorScope,
)
from app.read_connector_provider_transport import (
    AccountBoundReadConnectorClient,
    EnvironmentFileReadConnectorCredentialProvider,
    FileReadConnectorCredentialProvider,
    PinnedBearerJsonPostTransport,
    ProviderPinnedTransport,
    ProviderReadRequest,
    ReadConnectorCredentialError,
    ReadConnectorRemoteError,
    build_provider_plan,
    parse_provider_response,
)
from app.web_fetch import TransportResponse, WebFetchError

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


# Fixed request planning: callers choose typed operation/scope inputs, never an
# origin, arbitrary HTTP method, header, or provider path.
calendar_plan = build_provider_plan(
    ProviderReadRequest(
        connector="google_calendar",
        object_scope="primary",
        operation="event_search",
        query="design review",
        max_results=25,
    )
)
check(calendar_plan.method == "GET", "Calendar search is GET")
check(calendar_plan.url.startswith("https://www.googleapis.com/calendar/v3/calendars/primary/events?"), "Calendar origin/path are fixed")
check("q=design+review" in calendar_plan.url and "singleEvents=true" in calendar_plan.url, "Calendar query is encoded by adapter")

drive_plan = build_provider_plan(
    ProviderReadRequest(
        connector="google_drive",
        object_scope="folder_123",
        operation="file_search",
        query="roadmap 'v2'",
        cursor="next_1",
    )
)
check(drive_plan.method == "GET", "Drive search is GET")
check(drive_plan.url.startswith("https://www.googleapis.com/drive/v3/files?"), "Drive origin/path are fixed")
check("pageToken=next_1" in drive_plan.url and "fields=" in drive_plan.url, "Drive continuation and projection are explicit")

gmail_plan = build_provider_plan(
    ProviderReadRequest(
        connector="gmail",
        object_scope="mailbox",
        operation="message_get",
        child_ref="18f00abc123",
    )
)
check(gmail_plan.url == "https://www.googleapis.com/gmail/v1/users/me/messages/18f00abc123?format=full", "Gmail message path is fixed and exact")

notion_search = build_provider_plan(
    ProviderReadRequest(
        connector="notion",
        object_scope="workspace",
        operation="search",
        query="architecture",
        cursor="cursor_1",
        max_results=30,
    )
)
check(notion_search.method == "POST", "Notion search uses read-only POST seam")
check(notion_search.url == "https://api.notion.com/v1/search", "Notion search origin/path are fixed")
check(notion_search.headers.get("notion-version") == "2026-03-11", "Notion API version is pinned to current documented version")
check(json.loads(notion_search.json_body or b"{}") == {"page_size": 30, "query": "architecture", "start_cursor": "cursor_1"}, "Notion search body is adapter-owned canonical JSON")

notion_query = build_provider_plan(
    ProviderReadRequest(
        connector="notion",
        object_scope="d9824bdc-8445-4327-be8b-5b47500af6ce",
        operation="database_query",
        max_results=20,
    )
)
check(notion_query.url.endswith("/v1/data_sources/d9824bdc-8445-4327-be8b-5b47500af6ce/query"), "legacy contract name maps to current Notion data-source query endpoint")
check(notion_query.method == "POST", "Notion data-source query is constrained POST")

rejects(
    lambda: build_provider_plan(ProviderReadRequest(connector="gmail", object_scope="mailbox", operation="message_send")),
    ReadConnectorRemoteError,
    "write-like Gmail operation is unrepresentable",
    "unsupported",
)
rejects(
    lambda: build_provider_plan(ProviderReadRequest(connector="notion", object_scope="workspace", operation="search", child_ref="page")),
    ReadConnectorRemoteError,
    "Notion search cannot smuggle an arbitrary child path",
)
rejects(
    lambda: build_provider_plan(ProviderReadRequest(connector="gmail", object_scope="other", operation="message_search")),
    ReadConnectorRemoteError,
    "Gmail collection read requires exact mailbox object scope",
)


class CapturingResolver:
    def __init__(self):
        self.calls = []

    def __call__(self, host, port):
        self.calls.append((host, port))
        return ("8.8.8.8", "1.1.1.1", "1.1.1.1")


class CapturingGet:
    def __init__(self, response: TransportResponse):
        self.response = response
        self.calls = []

    def request_with_trusted_bearer(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class CapturingPost:
    def __init__(self, response: TransportResponse):
        self.response = response
        self.calls = []

    def request_with_trusted_bearer_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


with tempfile.TemporaryDirectory(prefix="modelrig-t037-provider-") as td:
    root = Path(td)
    token = "provider_fixture_token_1234567890"
    token_file = root / "token.secret"
    token_file.write_text(token + "\n", encoding="ascii")
    if os.name == "posix":
        token_file.chmod(0o600)

    google_credential = FileReadConnectorCredentialProvider(
        connector="google_calendar",
        account_ref="google_sub_123",
        token_file=token_file,
        expires_at=2000,
    )
    check(google_credential.credential_state(now=1000) == "ready", "Google access token is ready before explicit expiry")
    check(google_credential.credential_state(now=2000) == "expired_credentials", "Google access token fails closed at expiry")
    rejects(lambda: google_credential.bearer_token(now=2000), ReadConnectorCredentialError, "expired Google token cannot be loaded", "expired")
    check(token not in repr(google_credential), "credential provider repr does not expose bearer")

    notion_credential = FileReadConnectorCredentialProvider(
        connector="notion",
        account_ref="notion_account_1",
        workspace_ref="workspace_1",
        token_file=token_file,
    )
    check(notion_credential.credential_state(now=999999) == "ready", "Notion integration token may be configured without synthetic expiry")

    env_provider = EnvironmentFileReadConnectorCredentialProvider(
        "gmail",
        {
            "KALIV_GMAIL_ACCOUNT_REF": "google_sub_123",
            "KALIV_GMAIL_TOKEN_FILE": str(token_file),
            "KALIV_GMAIL_EXPIRES_AT": "2000",
        },
    )
    check(env_provider.account_ref == "google_sub_123" and env_provider.bearer_token(now=1000) == token, "environment carries credential metadata/path, not token value")

    rejects(
        lambda: FileReadConnectorCredentialProvider(
            connector="google_drive",
            account_ref="google_sub_123",
            token_file=token_file,
        ),
        ReadConnectorCredentialError,
        "Google credential requires explicit access-token expiry",
        "expires_at",
    )
    rejects(
        lambda: FileReadConnectorCredentialProvider(
            connector="notion",
            account_ref="notion_account_1",
            token_file=token_file,
        ),
        ReadConnectorCredentialError,
        "Notion credential requires exact workspace identity",
        "workspace_ref",
    )

    if os.name == "posix":
        token_file.chmod(0o644)
        check(google_credential.credential_state(now=1000) == "invalid_credentials", "broad POSIX permissions are non-ready")
        rejects(lambda: google_credential.bearer_token(now=1000), ReadConnectorCredentialError, "broad POSIX permissions cannot return token")
        token_file.chmod(0o600)

    # Exact grant -> credential -> fixed provider composition.
    grants = ReadConnectorGrantStore()
    scope = ReadConnectorScope(
        connector="google_calendar",
        account_ref="google_sub_123",
        object_scopes=("primary",),
        operations=("event_search",),
    )
    grant = grants.create_grant(scope, actor="operator", now=900)
    response = TransportResponse(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps({
            "items": [
                {"id": "event_1", "etag": "event-rev-1", "summary": "Design review"},
            ],
            "nextPageToken": "page_2",
        }).encode(),
        connected_address="1.1.1.1",
    )
    resolver = CapturingResolver()
    get = CapturingGet(response)
    transport = ProviderPinnedTransport(
        credentials=google_credential,
        resolver=resolver,
        get_transport=get,
    )
    client = AccountBoundReadConnectorClient(grants=grants, transport=transport)
    result = client.read(
        grant.grant_id,
        ProviderReadRequest(
            connector="google_calendar",
            object_scope="primary",
            operation="event_search",
            query="design",
        ),
        now=1000,
    )
    check(resolver.calls == [("www.googleapis.com", 443)], "Google DNS host is adapter-owned")
    check(len(get.calls) == 1 and get.calls[0][0].startswith("https://www.googleapis.com/"), "Google request uses only fixed origin")
    check(get.calls[0][1]["connect_address"] == "1.1.1.1", "deterministic public DNS address is pinned")
    check(result.next_cursor == "page_2" and len(result.sources) == 1, "pagination is surfaced without hidden follow-up")
    receipt = result.sources[0]
    check(receipt.connector == "google_calendar" and receipt.object_id == "event_1" and receipt.revision == "event-rev-1", "provider object emits stable source/revision receipt")
    check(receipt.scope_sha256 == grant.scope.digest and receipt.production_activation is False, "source receipt is exact-grant bound and dormant")

    # Revoke must stop before DNS, token access and network. Use fresh captures to
    # prove there is no side effect after durable authority changes.
    grants.revoke(grant.grant_id, expected_scope_sha256=grant.scope.digest, actor="operator", now=1001)
    resolver_after_revoke = CapturingResolver()
    get_after_revoke = CapturingGet(response)
    revoked_transport = ProviderPinnedTransport(
        credentials=google_credential,
        resolver=resolver_after_revoke,
        get_transport=get_after_revoke,
    )
    revoked_client = AccountBoundReadConnectorClient(grants=grants, transport=revoked_transport)
    rejects(
        lambda: revoked_client.read(
            grant.grant_id,
            ProviderReadRequest(connector="google_calendar", object_scope="primary", operation="event_search"),
            now=1002,
        ),
        ReadConnectorDenied,
        "revoked grant blocks later provider read",
        "revoked",
    )
    check(resolver_after_revoke.calls == [] and get_after_revoke.calls == [], "revocation blocks before DNS/transport")

    # Credential/account mismatch is also pre-network.
    mismatch_grants = ReadConnectorGrantStore()
    mismatch = mismatch_grants.create_grant(
        ReadConnectorScope(
            connector="google_calendar",
            account_ref="different_google_sub",
            object_scopes=("primary",),
            operations=("event_search",),
        ),
        actor="operator",
        now=900,
    )
    mismatch_resolver = CapturingResolver()
    mismatch_get = CapturingGet(response)
    mismatch_client = AccountBoundReadConnectorClient(
        grants=mismatch_grants,
        transport=ProviderPinnedTransport(
            credentials=google_credential,
            resolver=mismatch_resolver,
            get_transport=mismatch_get,
        ),
    )
    rejects(
        lambda: mismatch_client.read(
            mismatch.grant_id,
            ProviderReadRequest(connector="google_calendar", object_scope="primary", operation="event_search"),
            now=1000,
        ),
        ReadConnectorDenied,
        "grant account cannot borrow another configured credential",
    )
    check(mismatch_resolver.calls == [] and mismatch_get.calls == [], "account mismatch opens no provider connection")

    # Current Notion 2026-03-11 query shape executes through JSON POST only.
    notion_grants = ReadConnectorGrantStore()
    notion_grant = notion_grants.create_grant(
        ReadConnectorScope(
            connector="notion",
            account_ref="notion_account_1",
            workspace_ref="workspace_1",
            object_scopes=("workspace",),
            operations=("search",),
        ),
        actor="operator",
        now=900,
    )
    notion_response = TransportResponse(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps({
            "object": "list",
            "results": [{"object": "page", "id": "page_1", "last_edited_time": "2026-08-22T06:00:00Z"}],
            "has_more": True,
            "next_cursor": "cursor_2",
        }).encode(),
        connected_address="1.1.1.1",
    )
    notion_resolver = CapturingResolver()
    post = CapturingPost(notion_response)
    notion_client = AccountBoundReadConnectorClient(
        grants=notion_grants,
        transport=ProviderPinnedTransport(
            credentials=notion_credential,
            resolver=notion_resolver,
            post_transport=post,
        ),
    )
    notion_result = notion_client.read(
        notion_grant.grant_id,
        ProviderReadRequest(connector="notion", object_scope="workspace", operation="search", query="architecture"),
        now=1000,
    )
    check(notion_resolver.calls == [("api.notion.com", 443)], "Notion DNS host is fixed")
    check(len(post.calls) == 1 and post.calls[0][0] == "https://api.notion.com/v1/search", "Notion search uses only fixed POST endpoint")
    check(post.calls[0][1]["headers"]["notion-version"] == "2026-03-11", "Notion version header reaches trusted transport")
    check(json.loads(post.calls[0][1]["json_body"])["query"] == "architecture", "Notion JSON body is exact adapter output")
    check(notion_result.next_cursor == "cursor_2" and notion_result.sources[0].object_id == "page_1", "Notion continuation/source evidence is preserved")

    # Provider errors never include the remote body/token in exception text.
    secret_body = token + " remote private body"
    error_response = TransportResponse(500, {"content-type": "application/json"}, secret_body.encode(), "1.1.1.1")
    error_client = AccountBoundReadConnectorClient(
        grants=notion_grants,
        transport=ProviderPinnedTransport(
            credentials=notion_credential,
            resolver=CapturingResolver(),
            post_transport=CapturingPost(error_response),
        ),
    )
    try:
        error_client.read(
            notion_grant.grant_id,
            ProviderReadRequest(connector="notion", object_scope="workspace", operation="search"),
            now=1000,
        )
    except ReadConnectorRemoteError as exc:
        check(token not in str(exc) and "private body" not in str(exc), "provider error redacts bearer and response body")
    else:
        check(False, "provider HTTP error is rejected")

    grants.close()
    mismatch_grants.close()
    notion_grants.close()


# Provider response validation fails closed on mismatched exact single objects.
metadata_plan = build_provider_plan(
    ProviderReadRequest(connector="google_drive", object_scope="file_expected", operation="file_metadata")
)
rejects(
    lambda: parse_provider_response(
        metadata_plan,
        TransportResponse(
            200,
            {"content-type": "application/json"},
            json.dumps({"id": "file_other", "version": "1"}).encode(),
            "1.1.1.1",
        ),
    ),
    ReadConnectorRemoteError,
    "single-object response must match exact requested object",
    "different object",
)

bad_notion = build_provider_plan(
    ProviderReadRequest(connector="notion", object_scope="workspace", operation="search")
)
rejects(
    lambda: parse_provider_response(
        bad_notion,
        TransportResponse(
            200,
            {"content-type": "application/json"},
            json.dumps({"results": [], "has_more": False, "next_cursor": "unexpected"}).encode(),
            "1.1.1.1",
        ),
    ),
    ReadConnectorRemoteError,
    "Notion cursor without has_more fails closed",
    "cursor",
)


# Exercise the concrete connector-only JSON POST seam with a fake pinned socket.
class FakeSocket:
    def __init__(self, wire_bytes: bytes, *, peer: str = "1.1.1.1") -> None:
        self.wire_bytes = wire_bytes
        self.peer = peer
        self.sockaddr = None
        self.sent = b""
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def connect(self, sockaddr):
        self.sockaddr = sockaddr

    def getpeername(self):
        return (self.peer, self.sockaddr[1])

    def sendall(self, data):
        self.sent += data

    def makefile(self, mode, buffering=None):
        return io.BytesIO(self.wire_bytes)

    def close(self):
        self.closed = True


class FakeTLS:
    def __init__(self):
        self.server_names = []

    def wrap_socket(self, sock, *, server_hostname):
        self.server_names.append(server_hostname)
        return sock


def wire(status="200 OK", headers=(), body=b""):
    lines = [f"HTTP/1.1 {status}"] + [f"{k}: {v}" for k, v in headers]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


post_sock = FakeSocket(wire(headers=(("Content-Type", "application/json"), ("Content-Length", "2")), body=b"{}"))
post_tls = FakeTLS()
post_transport = PinnedBearerJsonPostTransport(
    socket_factory=lambda family, kind: post_sock,
    ssl_context_factory=lambda: post_tls,
)
post_response = post_transport.request_with_trusted_bearer_json(
    "https://api.notion.com/v1/search",
    connect_address="1.1.1.1",
    headers={"accept": "application/json", "notion-version": "2026-03-11"},
    bearer_token="notion_fixture_token_1234567890",
    json_body=b'{"page_size":10}',
    timeout_seconds=2,
    max_wire_bytes=64,
)
check(post_response.status == 200 and post_response.body == b"{}", "trusted JSON POST parses pinned response")
check(post_sock.sent.startswith(b"POST /v1/search HTTP/1.1\r\n"), "trusted JSON seam cannot change POST method")
check(b"Host: api.notion.com\r\n" in post_sock.sent and post_tls.server_names == ["api.notion.com"], "trusted JSON POST preserves Host/TLS authority")
check(b"Content-Type: application/json\r\n" in post_sock.sent and b'{"page_size":10}' in post_sock.sent, "trusted JSON POST owns media type/body")
check(b"Authorization: Bearer notion_fixture_token_1234567890\r\n" in post_sock.sent, "bearer is injected only inside pinned POST transport")
check(post_sock.closed, "trusted JSON POST closes pinned socket")

no_socket_calls = []
invalid_post = PinnedBearerJsonPostTransport(socket_factory=lambda *args: no_socket_calls.append(args))
rejects(
    lambda: invalid_post.request_with_trusted_bearer_json(
        "https://api.notion.com/v1/search",
        connect_address="1.1.1.1",
        headers={"authorization": "Bearer caller-controlled"},
        bearer_token="notion_fixture_token_1234567890",
        json_body=b"{}",
        timeout_seconds=2,
        max_wire_bytes=64,
    ),
    WebFetchError,
    "caller-controlled Authorization remains forbidden in POST headers",
    "forbidden",
)
check(no_socket_calls == [], "invalid POST headers fail before socket creation")

# Dormant boundary: this slice must not become runtime-visible by accident.
repo = Path(__file__).resolve().parents[1]
main_source = (repo / "worker" / "app" / "main.py").read_text(encoding="utf-8")
check("read_connector_provider_transport" not in main_source, "provider transport is not imported by normal worker boot")
for forbidden in ("FastAPI(", "@app.", "TOOL_REGISTRY", "production_activation=True"):
    module_source = (repo / "worker" / "app" / "read_connector_provider_transport.py").read_text(encoding="utf-8")
    check(forbidden not in module_source, f"provider slice remains dormant: {forbidden}")

print(f"\n===== T-037 PROVIDER TRANSPORT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
