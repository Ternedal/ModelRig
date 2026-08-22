"""T-037 provider-bound transport for dormant Google/Notion read connectors.

This module is intentionally not registered in ToolGate, FastAPI, or normal
worker startup.  It consumes the exact T-037 grant contract and adds the next
security boundary only:

* credential metadata is bound to one connector/account/workspace while the
  bearer itself lives in a local secret file and is loaded only at execution;
* Google access tokens must carry explicit expiry metadata; Notion integration
  tokens may be non-expiring but remain file-backed;
* the model/caller cannot choose scheme, host, HTTP method or headers;
* Google calls are pinned to ``www.googleapis.com`` and Notion calls to
  ``api.notion.com``;
* Notion's read-only search/data-source query POSTs use a dedicated JSON-only
  trusted-bearer seam.  The generic public pinned transport remains GET-only;
* no hidden pagination is performed; provider continuation is returned;
* provider responses are bounded and validated before source receipts are
  emitted;
* durable grant authorization is re-read before DNS, credential loading or
  transport, so a revoked grant produces zero outbound work.

``production_activation`` remains false in the authority/source receipts.  This
module does not implement OAuth refresh or any write-capability surface.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import quote, urlencode

from .pinned_http_transport import (
    PinnedHttpTransport,
    _normalize_response_headers,
    _request_target,
    _validated_bearer_token,
    _validated_headers,
)
from .read_connector_package_contract import (
    Connector,
    ReadConnectorDenied,
    ReadConnectorGrant,
    ReadConnectorGrantStore,
    ReadConnectorSourceReceipt,
    normalize_connector,
)
from .web_fetch import TransportResponse, WebFetchError, default_resolver

_GOOGLE_ORIGIN = "https://www.googleapis.com"
_NOTION_ORIGIN = "https://api.notion.com"
_NOTION_VERSION = "2026-03-11"
_HTTPS_PORT = 443
_DEFAULT_TIMEOUT_SECONDS = 15.0
_DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_TOKEN_FILE_BYTES = 4096
_MAX_REQUEST_JSON_BYTES = 64 * 1024
_MAX_QUERY_CHARS = 500
_MAX_CURSOR_CHARS = 2048
_MAX_RESULTS = 100
_READ_CHUNK = 64 * 1024
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}$")
_SAFE_RECEIPT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}$")


class ReadConnectorCredentialError(RuntimeError):
    """Credential metadata/material is missing, expired or malformed."""


class ReadConnectorRemoteError(RuntimeError):
    """Provider transport or response was invalid without exposing body data."""


class ReadConnectorNotFound(ReadConnectorRemoteError):
    pass


class ReadConnectorRateLimited(ReadConnectorRemoteError):
    pass


def _stable_ref(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ReadConnectorCredentialError(f"{name} must be a string")
    value = value.strip()
    if not _REF.fullmatch(value):
        raise ReadConnectorCredentialError(f"{name} is not a stable provider identifier")
    return value


def _non_negative_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReadConnectorCredentialError(f"{name} must be a non-negative integer")
    return value


def _safe_text(value: str | None, name: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReadConnectorRemoteError(f"{name} must be a string")
    value = value.strip()
    if not value or len(value) > maximum or any(ord(ch) < 0x20 for ch in value):
        raise ReadConnectorRemoteError(f"{name} is invalid")
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _receipt_id(raw: str) -> str:
    if isinstance(raw, str) and _SAFE_RECEIPT_ID.fullmatch(raw):
        return raw
    if not isinstance(raw, str) or not raw:
        raise ReadConnectorRemoteError("provider object id is missing")
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _revision(raw: Any, fallback: Any) -> str:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = str(raw)
    if isinstance(raw, str) and raw.strip():
        value = raw.strip()
        if _SAFE_RECEIPT_ID.fullmatch(value):
            return value
        return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
    return "sha256:" + hashlib.sha256(_canonical_json(fallback)).hexdigest()


class ReadConnectorCredentialProvider(Protocol):
    @property
    def connector(self) -> Connector: ...

    @property
    def account_ref(self) -> str: ...

    @property
    def workspace_ref(self) -> str | None: ...

    def credential_state(self, *, now: int) -> str: ...

    def bearer_token(self, *, now: int) -> str: ...


class FileReadConnectorCredentialProvider:
    """Connector-bound bearer loaded from a local secret file on demand.

    The token never enters environment variables through this class.  On POSIX
    the token file must not be group/world accessible.  As with the established
    T-036 file provider, Windows ACL enforcement belongs to deployment until a
    dedicated host secret-store layer is selected.
    """

    def __init__(
        self,
        *,
        connector: Connector,
        account_ref: str,
        token_file: str | os.PathLike[str],
        workspace_ref: str | None = None,
        expires_at: int | None = None,
    ) -> None:
        self._connector = normalize_connector(connector)
        self._account_ref = _stable_ref(account_ref, "account_ref")
        self._workspace_ref = (
            _stable_ref(workspace_ref, "workspace_ref") if workspace_ref is not None else None
        )
        if self._connector == "notion" and self._workspace_ref is None:
            raise ReadConnectorCredentialError("Notion credential requires workspace_ref")
        if self._connector != "notion" and self._workspace_ref is not None:
            raise ReadConnectorCredentialError("Google credential must not carry workspace_ref")
        if self._connector != "notion" and expires_at is None:
            raise ReadConnectorCredentialError("Google OAuth access token requires expires_at")
        self._expires_at = (
            _non_negative_int(expires_at, "expires_at") if expires_at is not None else None
        )
        self._path = Path(token_file)

    @property
    def connector(self) -> Connector:
        return self._connector

    @property
    def account_ref(self) -> str:
        return self._account_ref

    @property
    def workspace_ref(self) -> str | None:
        return self._workspace_ref

    def _read_token(self) -> str:
        try:
            info = self._path.stat()
        except OSError as exc:
            raise ReadConnectorCredentialError("connector credential file is unavailable") from exc
        if not stat.S_ISREG(info.st_mode):
            raise ReadConnectorCredentialError("connector credential path is not a regular file")
        if info.st_size < 1 or info.st_size > _MAX_TOKEN_FILE_BYTES:
            raise ReadConnectorCredentialError("connector credential file size is invalid")
        if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
            raise ReadConnectorCredentialError("connector credential file permissions are too broad")
        try:
            raw = self._path.read_bytes()
        except OSError as exc:
            raise ReadConnectorCredentialError("connector credential file cannot be read") from exc
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ReadConnectorCredentialError("connector credential token must be ASCII") from exc
        token = text[:-2] if text.endswith("\r\n") else text[:-1] if text.endswith("\n") else text
        if "\r" in token or "\n" in token or token != token.strip():
            raise ReadConnectorCredentialError("connector credential token format is invalid")
        if not 20 <= len(token) <= _MAX_TOKEN_FILE_BYTES:
            raise ReadConnectorCredentialError("connector credential token length is invalid")
        if any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in token):
            raise ReadConnectorCredentialError("connector credential token format is invalid")
        return token

    def credential_state(self, *, now: int) -> str:
        now = _non_negative_int(now, "now")
        if self._expires_at is not None and now >= self._expires_at:
            return "expired_credentials"
        try:
            self._read_token()
        except ReadConnectorCredentialError as exc:
            if "unavailable" in str(exc):
                return "missing_credentials"
            return "invalid_credentials"
        return "ready"

    def bearer_token(self, *, now: int) -> str:
        state = self.credential_state(now=now)
        if state != "ready":
            raise ReadConnectorCredentialError(f"connector credential is not ready: {state}")
        return self._read_token()


class EnvironmentFileReadConnectorCredentialProvider(FileReadConnectorCredentialProvider):
    """Deployment config carries identity/path/expiry, never the bearer itself."""

    def __init__(self, connector: Connector, env: Mapping[str, str] | None = None) -> None:
        connector = normalize_connector(connector)
        values = os.environ if env is None else env
        prefix = "KALIV_" + connector.upper()
        account = values.get(prefix + "_ACCOUNT_REF", "")
        token_file = values.get(prefix + "_TOKEN_FILE", "")
        workspace = values.get(prefix + "_WORKSPACE_REF") or None
        expiry_raw = values.get(prefix + "_EXPIRES_AT") or None
        if not account or not token_file:
            raise ReadConnectorCredentialError("connector account/token-file configuration is missing")
        try:
            expiry = int(expiry_raw) if expiry_raw is not None else None
        except ValueError as exc:
            raise ReadConnectorCredentialError("connector expires_at configuration is invalid") from exc
        super().__init__(
            connector=connector,
            account_ref=account,
            workspace_ref=workspace,
            token_file=token_file,
            expires_at=expiry,
        )


@dataclass(frozen=True)
class ProviderReadRequest:
    connector: Connector
    object_scope: str
    operation: str
    child_ref: str | None = None
    query: str | None = None
    cursor: str | None = None
    max_results: int = 50

    def __post_init__(self) -> None:
        connector = normalize_connector(self.connector)
        object_scope = _stable_ref(self.object_scope, "object_scope")
        child = _stable_ref(self.child_ref, "child_ref") if self.child_ref is not None else None
        query = _safe_text(self.query, "query", maximum=_MAX_QUERY_CHARS)
        cursor = _safe_text(self.cursor, "cursor", maximum=_MAX_CURSOR_CHARS)
        if isinstance(self.max_results, bool) or not isinstance(self.max_results, int) or not 1 <= self.max_results <= _MAX_RESULTS:
            raise ReadConnectorRemoteError("max_results must be within 1..100")
        object.__setattr__(self, "connector", connector)
        object.__setattr__(self, "object_scope", object_scope)
        object.__setattr__(self, "child_ref", child)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "cursor", cursor)


@dataclass(frozen=True)
class ProviderHttpPlan:
    connector: Connector
    object_scope: str
    operation: str
    method: str
    url: str
    headers: Mapping[str, str]
    json_body: bytes | None
    max_response_bytes: int


@dataclass(frozen=True)
class ProviderObjectEvidence:
    object_id: str
    source_id: str
    revision: str


@dataclass(frozen=True)
class ProviderReadResult:
    connector: Connector
    operation: str
    object_scope: str
    value: Any
    next_cursor: str | None
    sources: tuple[ReadConnectorSourceReceipt, ...]


def _path_ref(value: str) -> str:
    return quote(value, safe="")


def _drive_q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def build_provider_plan(request: ProviderReadRequest) -> ProviderHttpPlan:
    c = request.connector
    op = request.operation
    scope = request.object_scope
    child = request.child_ref
    params: list[tuple[str, str]] = []
    body: dict[str, Any] | None = None
    method = "GET"
    origin = _GOOGLE_ORIGIN if c != "notion" else _NOTION_ORIGIN
    headers: dict[str, str] = {"accept": "application/json"}

    if c == "google_calendar":
        if op == "calendar_list":
            if scope != "calendar_list" or child is not None or request.query is not None:
                raise ReadConnectorRemoteError("calendar_list requires exact calendar_list scope")
            path = "/calendar/v3/users/me/calendarList"
            params.append(("maxResults", str(request.max_results)))
        elif op == "event_get":
            if child is None or request.query is not None or request.cursor is not None:
                raise ReadConnectorRemoteError("event_get requires one exact child_ref")
            path = f"/calendar/v3/calendars/{_path_ref(scope)}/events/{_path_ref(child)}"
        elif op == "event_search":
            if child is not None:
                raise ReadConnectorRemoteError("event_search does not accept child_ref")
            path = f"/calendar/v3/calendars/{_path_ref(scope)}/events"
            params.extend((("singleEvents", "true"), ("orderBy", "startTime"), ("maxResults", str(request.max_results))))
            if request.query is not None:
                params.append(("q", request.query))
        else:
            raise ReadConnectorRemoteError("unsupported google_calendar read operation")
    elif c == "google_drive":
        if op == "file_search":
            if child is not None:
                raise ReadConnectorRemoteError("file_search does not accept child_ref")
            path = "/drive/v3/files"
            q = f"'{_drive_q(scope)}' in parents and trashed = false"
            if request.query is not None:
                q += f" and name contains '{_drive_q(request.query)}'"
            params.extend((("q", q), ("pageSize", str(request.max_results)), ("fields", "nextPageToken,files(id,name,mimeType,modifiedTime,version,md5Checksum)")))
        elif op == "file_metadata":
            if child is not None or request.query is not None or request.cursor is not None:
                raise ReadConnectorRemoteError("file_metadata accepts only exact file scope")
            path = f"/drive/v3/files/{_path_ref(scope)}"
            params.append(("fields", "id,name,mimeType,modifiedTime,version,md5Checksum"))
        elif op == "document_read":
            if child is not None or request.query is not None or request.cursor is not None:
                raise ReadConnectorRemoteError("document_read accepts only exact file scope")
            path = f"/drive/v3/files/{_path_ref(scope)}/export"
            params.append(("mimeType", "text/plain"))
            headers["accept"] = "text/plain"
        else:
            raise ReadConnectorRemoteError("unsupported google_drive read operation")
    elif c == "gmail":
        if op == "message_search":
            if scope != "mailbox" or child is not None:
                raise ReadConnectorRemoteError("message_search requires exact mailbox scope")
            path = "/gmail/v1/users/me/messages"
            params.append(("maxResults", str(request.max_results)))
            if request.query is not None:
                params.append(("q", request.query))
        elif op in {"message_get", "thread_get"}:
            if scope != "mailbox" or child is None or request.query is not None or request.cursor is not None:
                raise ReadConnectorRemoteError(f"{op} requires mailbox scope and one exact child_ref")
            resource = "messages" if op == "message_get" else "threads"
            path = f"/gmail/v1/users/me/{resource}/{_path_ref(child)}"
            params.append(("format", "full"))
        else:
            raise ReadConnectorRemoteError("unsupported gmail read operation")
    else:
        headers["notion-version"] = _NOTION_VERSION
        if op == "search":
            if scope != "workspace" or child is not None:
                raise ReadConnectorRemoteError("Notion search requires exact workspace object scope")
            path = "/v1/search"
            method = "POST"
            body = {"page_size": request.max_results}
            if request.query is not None:
                body["query"] = request.query
            if request.cursor is not None:
                body["start_cursor"] = request.cursor
        elif op == "page_get":
            if child is not None or request.query is not None or request.cursor is not None:
                raise ReadConnectorRemoteError("Notion page_get accepts only exact page scope")
            path = f"/v1/pages/{_path_ref(scope)}"
        elif op == "database_query":
            if child is not None or request.query is not None:
                raise ReadConnectorRemoteError("Notion data-source query accepts no free-form filter in v1")
            path = f"/v1/data_sources/{_path_ref(scope)}/query"
            method = "POST"
            body = {"page_size": request.max_results}
            if request.cursor is not None:
                body["start_cursor"] = request.cursor
        else:
            raise ReadConnectorRemoteError("unsupported notion read operation")

    if request.cursor is not None and method == "GET":
        params.append(("pageToken", request.cursor))
    query_string = urlencode(params)
    url = origin + path + ("?" + query_string if query_string else "")
    json_body = _canonical_json(body) if body is not None else None
    if json_body is not None and len(json_body) > _MAX_REQUEST_JSON_BYTES:
        raise ReadConnectorRemoteError("provider request JSON exceeds limit")
    return ProviderHttpPlan(
        connector=c,
        object_scope=scope,
        operation=op,
        method=method,
        url=url,
        headers=headers,
        json_body=json_body,
        max_response_bytes=_DEFAULT_MAX_RESPONSE_BYTES,
    )


class PinnedBearerJsonPostTransport:
    """Dedicated HTTPS JSON POST seam for read-only provider query endpoints."""

    def __init__(self, *, socket_factory=socket.socket, ssl_context_factory=ssl.create_default_context, response_factory=http.client.HTTPResponse) -> None:
        self._socket_factory = socket_factory
        self._ssl_context_factory = ssl_context_factory
        self._response_factory = response_factory

    def request_with_trusted_bearer_json(
        self,
        url: str,
        *,
        connect_address: str,
        headers: Mapping[str, str],
        bearer_token: str,
        json_body: bytes,
        timeout_seconds: float,
        max_wire_bytes: int,
    ) -> TransportResponse:
        if not isinstance(json_body, bytes) or not json_body or len(json_body) > _MAX_REQUEST_JSON_BYTES:
            raise WebFetchError("trusted JSON request body is invalid")
        bearer = _validated_bearer_token(bearer_token)
        scheme, host, port, target, host_header = _request_target(url)
        if scheme != "https":
            raise WebFetchError("trusted bearer JSON POST requires HTTPS")
        clean_headers = _validated_headers(headers)
        if any(name == "content-type" for name, _ in clean_headers):
            raise WebFetchError("trusted JSON POST owns Content-Type")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise WebFetchError("transport timeout must be positive")
        if isinstance(max_wire_bytes, bool) or not isinstance(max_wire_bytes, int) or max_wire_bytes < 1:
            raise WebFetchError("transport max_wire_bytes must be positive")
        try:
            numeric = ipaddress.ip_address(connect_address)
        except ValueError as exc:
            raise WebFetchError("transport connect_address must be a numeric IP") from exc
        family = socket.AF_INET6 if numeric.version == 6 else socket.AF_INET
        sockaddr = (numeric.compressed, port, 0, 0) if family == socket.AF_INET6 else (numeric.compressed, port)
        raw_socket = active_socket = response = None
        try:
            raw_socket = self._socket_factory(family, socket.SOCK_STREAM)
            raw_socket.settimeout(float(timeout_seconds))
            raw_socket.connect(sockaddr)
            active_socket = raw_socket
            context = self._ssl_context_factory()
            active_socket = context.wrap_socket(raw_socket, server_hostname=host)
            active_socket.settimeout(float(timeout_seconds))
            peer = ipaddress.ip_address(active_socket.getpeername()[0]).compressed
            lines = [
                f"POST {target} HTTP/1.1",
                f"Host: {host_header}",
                "Connection: close",
            ]
            lines.extend(f"{name}: {value}" for name, value in clean_headers)
            lines.extend((
                "Content-Type: application/json",
                f"Content-Length: {len(json_body)}",
                f"Authorization: Bearer {bearer}",
            ))
            active_socket.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + json_body)
            response = self._response_factory(active_socket, method="POST")
            response.begin()
            response_headers = _normalize_response_headers(response.getheaders())
            data = bytearray()
            while True:
                remaining = max_wire_bytes + 1 - len(data)
                if remaining <= 0:
                    raise WebFetchError("transport exceeded max_wire_bytes")
                chunk = response.read(min(_READ_CHUNK, remaining))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > max_wire_bytes:
                    raise WebFetchError("transport exceeded max_wire_bytes")
            return TransportResponse(response.status, response_headers, bytes(data), peer)
        except WebFetchError:
            raise
        except ssl.SSLCertVerificationError as exc:
            raise WebFetchError("TLS certificate verification failed") from exc
        except ssl.SSLError as exc:
            raise WebFetchError("TLS handshake failed") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise WebFetchError("transport timeout") from exc
        except (http.client.HTTPException, ValueError) as exc:
            raise WebFetchError("invalid HTTP response") from exc
        except OSError as exc:
            raise WebFetchError("transport connection failed") from exc
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            if active_socket is not None:
                try:
                    active_socket.close()
                except Exception:
                    pass
            if raw_socket is not None and raw_socket is not active_socket:
                try:
                    raw_socket.close()
                except Exception:
                    pass


class ProviderPinnedTransport:
    def __init__(
        self,
        *,
        credentials: ReadConnectorCredentialProvider,
        resolver=default_resolver,
        get_transport: PinnedHttpTransport | None = None,
        post_transport: PinnedBearerJsonPostTransport | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < float(timeout_seconds) <= 60:
            raise ReadConnectorCredentialError("provider transport timeout must be within 60 seconds")
        self._credentials = credentials
        self._resolver = resolver
        self._get = get_transport or PinnedHttpTransport()
        self._post = post_transport or PinnedBearerJsonPostTransport()
        self._timeout = float(timeout_seconds)

    @property
    def credentials(self) -> ReadConnectorCredentialProvider:
        return self._credentials

    def execute(self, plan: ProviderHttpPlan, *, now: int) -> TransportResponse:
        if plan.connector != self._credentials.connector:
            raise ReadConnectorDenied("provider plan connector does not match configured credential")
        origin = _GOOGLE_ORIGIN if plan.connector != "notion" else _NOTION_ORIGIN
        if not plan.url.startswith(origin + "/"):
            raise ReadConnectorRemoteError("provider plan origin mismatch")
        host = "www.googleapis.com" if plan.connector != "notion" else "api.notion.com"
        addresses = self._resolve_public(host)
        selected = addresses[0]
        token = self._credentials.bearer_token(now=now)
        try:
            if plan.method == "GET":
                response = self._get.request_with_trusted_bearer(
                    plan.url,
                    connect_address=selected,
                    headers=plan.headers,
                    bearer_token=token,
                    timeout_seconds=self._timeout,
                    max_wire_bytes=plan.max_response_bytes,
                )
            elif plan.method == "POST" and plan.json_body is not None:
                response = self._post.request_with_trusted_bearer_json(
                    plan.url,
                    connect_address=selected,
                    headers=plan.headers,
                    bearer_token=token,
                    json_body=plan.json_body,
                    timeout_seconds=self._timeout,
                    max_wire_bytes=plan.max_response_bytes,
                )
            else:
                raise ReadConnectorRemoteError("provider plan method is not permitted")
        except WebFetchError as exc:
            raise ReadConnectorRemoteError("provider pinned transport failed") from exc
        try:
            peer = ipaddress.ip_address(response.connected_address).compressed
        except ValueError as exc:
            raise ReadConnectorRemoteError("provider transport returned invalid peer evidence") from exc
        if peer != selected:
            raise ReadConnectorRemoteError("provider transport peer did not match pinned DNS address")
        return response

    def _resolve_public(self, host: str) -> tuple[str, ...]:
        try:
            raw: Sequence[str] = self._resolver(host, _HTTPS_PORT)
        except Exception as exc:
            raise ReadConnectorRemoteError("provider DNS resolution failed") from exc
        if not raw:
            raise ReadConnectorRemoteError("provider DNS resolution returned no addresses")
        values: set[str] = set()
        for item in raw:
            try:
                parsed = ipaddress.ip_address(item)
            except ValueError as exc:
                raise ReadConnectorRemoteError("provider DNS returned an invalid address") from exc
            if not parsed.is_global:
                raise ReadConnectorRemoteError("provider DNS returned a non-public address")
            values.add(parsed.compressed)
        return tuple(sorted(values, key=lambda value: (ipaddress.ip_address(value).version, ipaddress.ip_address(value).packed)))


def _status(response: TransportResponse) -> None:
    if response.status == 200:
        return
    if response.status in {401, 403}:
        raise ReadConnectorCredentialError("provider rejected connector credential or scope")
    if response.status == 404:
        raise ReadConnectorNotFound("provider object is unavailable")
    if response.status == 429:
        raise ReadConnectorRateLimited("provider rate limit reached")
    raise ReadConnectorRemoteError(f"provider returned HTTP {response.status}")


def _json_object(response: TransportResponse) -> dict[str, Any]:
    _status(response)
    content_type = response.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        raise ReadConnectorRemoteError("provider JSON response has invalid Content-Type")
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadConnectorRemoteError("provider JSON response is invalid") from exc
    if not isinstance(value, dict):
        raise ReadConnectorRemoteError("provider JSON response must be an object")
    return value


def _list(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ReadConnectorRemoteError(f"provider {name} is not an object list")
    return value


def _object_evidence(item: dict[str, Any], connector: Connector, *, revision_key: str | None = None) -> ProviderObjectEvidence:
    raw_id = item.get("id")
    if not isinstance(raw_id, str) or not raw_id:
        raise ReadConnectorRemoteError("provider object id is missing")
    object_id = _receipt_id(raw_id)
    raw_revision = item.get(revision_key) if revision_key else item.get("etag")
    if raw_revision is None:
        raw_revision = item.get("last_edited_time") or item.get("historyId") or item.get("version") or item.get("modifiedTime")
    return ProviderObjectEvidence(
        object_id=object_id,
        source_id=f"{connector}:{object_id}",
        revision=_revision(raw_revision, item),
    )


def parse_provider_response(plan: ProviderHttpPlan, response: TransportResponse) -> tuple[Any, str | None, tuple[ProviderObjectEvidence, ...]]:
    if plan.connector == "google_drive" and plan.operation == "document_read":
        _status(response)
        if not response.headers.get("content-type", "").lower().startswith("text/plain"):
            raise ReadConnectorRemoteError("Drive document export is not text/plain")
        try:
            text = response.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReadConnectorRemoteError("Drive document export is not UTF-8 text") from exc
        evidence = ProviderObjectEvidence(
            object_id=_receipt_id(plan.object_scope),
            source_id=f"google_drive:{_receipt_id(plan.object_scope)}",
            revision=_revision(response.headers.get("etag"), {"sha256": hashlib.sha256(response.body).hexdigest()}),
        )
        return text, None, (evidence,)

    value = _json_object(response)
    continuation: str | None = None
    items: list[dict[str, Any]]
    single = False

    if plan.connector == "google_calendar":
        if plan.operation in {"calendar_list", "event_search"}:
            items = _list(value.get("items", []), "items")
            continuation = _safe_text(value.get("nextPageToken"), "nextPageToken", maximum=_MAX_CURSOR_CHARS) if value.get("nextPageToken") is not None else None
        else:
            items = [value]
            single = True
    elif plan.connector == "google_drive":
        if plan.operation == "file_search":
            items = _list(value.get("files", []), "files")
            continuation = _safe_text(value.get("nextPageToken"), "nextPageToken", maximum=_MAX_CURSOR_CHARS) if value.get("nextPageToken") is not None else None
        else:
            items = [value]
            single = True
    elif plan.connector == "gmail":
        if plan.operation == "message_search":
            items = _list(value.get("messages", []), "messages")
            continuation = _safe_text(value.get("nextPageToken"), "nextPageToken", maximum=_MAX_CURSOR_CHARS) if value.get("nextPageToken") is not None else None
        else:
            items = [value]
            single = True
    else:
        if plan.operation in {"search", "database_query"}:
            items = _list(value.get("results", []), "results")
            has_more = value.get("has_more")
            if type(has_more) is not bool:
                raise ReadConnectorRemoteError("Notion has_more must be boolean")
            if has_more:
                continuation = _safe_text(value.get("next_cursor"), "next_cursor", maximum=_MAX_CURSOR_CHARS)
                if continuation is None:
                    raise ReadConnectorRemoteError("Notion continuation is missing")
            elif value.get("next_cursor") is not None:
                raise ReadConnectorRemoteError("Notion returned cursor without has_more")
        else:
            items = [value]
            single = True

    evidence = tuple(_object_evidence(item, plan.connector) for item in items)
    if single and evidence:
        expected = plan.object_scope
        if plan.operation in {"event_get", "message_get", "thread_get"}:
            # Child identifiers are represented by the provider object itself;
            # the authorized container remains plan.object_scope.
            pass
        elif _receipt_id(expected) != evidence[0].object_id:
            raise ReadConnectorRemoteError("provider returned a different object than requested")
    return value, continuation, evidence


class AccountBoundReadConnectorClient:
    """Exact grant + exact credential + pinned provider request composition."""

    def __init__(self, *, grants: ReadConnectorGrantStore, transport: ProviderPinnedTransport) -> None:
        self._grants = grants
        self._transport = transport

    def read(self, grant_id: str, request: ProviderReadRequest, *, now: int) -> ProviderReadResult:
        now = _non_negative_int(now, "now")
        credentials = self._transport.credentials
        if request.connector != credentials.connector:
            raise ReadConnectorDenied("connector request does not match configured credential")
        grant: ReadConnectorGrant = self._grants.authorize(
            grant_id,
            connector=request.connector,
            account_ref=credentials.account_ref,
            workspace_ref=credentials.workspace_ref,
            object_scope=request.object_scope,
            operation=request.operation,
        )
        if credentials.credential_state(now=now) != "ready":
            raise ReadConnectorCredentialError("connector credential is not ready")
        plan = build_provider_plan(request)
        response = self._transport.execute(plan, now=now)
        value, continuation, objects = parse_provider_response(plan, response)
        receipts = tuple(
            ReadConnectorSourceReceipt(
                connector=request.connector,
                grant_id=grant.grant_id,
                scope_sha256=grant.scope.digest,
                account_ref=grant.scope.account_ref,
                workspace_ref=grant.scope.workspace_ref,
                object_scope=request.object_scope,
                operation=request.operation,
                source_id=item.source_id,
                object_id=item.object_id,
                revision=item.revision,
                retrieved_at=now,
            )
            for item in objects
        )
        return ProviderReadResult(
            connector=request.connector,
            operation=request.operation,
            object_scope=request.object_scope,
            value=value,
            next_cursor=continuation,
            sources=receipts,
        )
