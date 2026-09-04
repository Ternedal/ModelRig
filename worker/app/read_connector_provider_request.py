"""T-037 dormant provider request plans for Google + Notion read connectors.

This module is intentionally *not* an HTTP client.  It converts an already
validated :class:`ReadConnectorScope` into one closed provider request plan.
The later transport layer may inject a credential at execution time, but a
model/tool request cannot choose a host, scheme, method, Authorization header,
redirect policy or arbitrary provider path through this contract.

The endpoint shapes are pinned to the provider APIs verified for 2026-08-12:

* Google Calendar v3: calendarList.list, events.get, events.list
* Google Drive v3: files.list, files.get, files.export
* Gmail v1: users.messages.list/get, users.threads.get (always ``users/me``)
* Notion: search, page retrieve, block children and data-source query using
  ``Notion-Version: 2026-03-11``

The T-037 authority v1 shipped with the logical Notion operation id
``database_query``.  That id remains stable here so an existing v1 scope digest
is never silently rewritten, but its provider operation is explicitly
``data_source_query`` and the request targets ``/v1/data_sources/{id}/query``.
No deprecated Notion database-query endpoint is representable.

``production_activation`` is structurally false throughout.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import quote, urlencode

from .read_connector_package_contract import (
    ReadConnectorContractError,
    ReadConnectorScope,
    capability_id,
)

REQUEST_SCHEMA = "kaliv-read-connector-provider-request/v1"
NOTION_VERSION = "2026-03-11"
PRODUCTION_ACTIVATION = False

Method = Literal["GET", "POST"]
ResponseKind = Literal["json", "text"]

_GOOGLE_HOST = "www.googleapis.com"
_GMAIL_HOST = "gmail.googleapis.com"
_NOTION_HOST = "api.notion.com"
_ALLOWED_HOSTS = frozenset({_GOOGLE_HOST, _GMAIL_HOST, _NOTION_HOST})
_ALLOWED_HEADERS = frozenset({"accept", "content-type", "notion-version"})
_CREDENTIAL_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "proxy-authorization",
        "x-api-key",
        "x-goog-api-key",
    }
)

_JSON_TYPES = ("application/json",)
_TEXT_TYPES = ("text/plain",)

_CALENDAR_LIST_FIELDS = "nextPageToken,items(id,etag,summary,timeZone,primary,accessRole)"
_CALENDAR_EVENT_FIELDS = "id,etag,status,summary,start,end,updated,recurringEventId,originalStartTime"
_CALENDAR_EVENT_LIST_FIELDS = f"nextPageToken,items({_CALENDAR_EVENT_FIELDS})"
_DRIVE_FILE_FIELDS = "id,name,mimeType,modifiedTime,version,md5Checksum,trashed,parents,size"
_DRIVE_FILE_LIST_FIELDS = f"nextPageToken,incompleteSearch,files({_DRIVE_FILE_FIELDS})"
_GMAIL_MESSAGE_LIST_FIELDS = "nextPageToken,resultSizeEstimate,messages(id,threadId)"
_GMAIL_MESSAGE_FIELDS = "id,threadId,labelIds,snippet,historyId,internalDate,payload"
_GMAIL_THREAD_FIELDS = (
    "id,historyId,messages(id,threadId,labelIds,snippet,historyId,internalDate,payload)"
)


class ProviderRequestError(ReadConnectorContractError):
    """A provider request cannot be represented inside the closed read contract."""


def _bounded_text(value: str, name: str, maximum: int, *, allow_blank: bool = False) -> str:
    if not isinstance(value, str):
        raise ProviderRequestError(f"{name} must be a string")
    value = value.strip()
    if (not value and not allow_blank) or len(value) > maximum:
        lower = 0 if allow_blank else 1
        raise ProviderRequestError(f"{name} must contain {lower}..{maximum} characters")
    if any(ord(ch) < 0x20 for ch in value):
        raise ProviderRequestError(f"{name} contains control characters")
    return value


def _page_size(value: int, *, maximum: int, name: str = "page_size") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ProviderRequestError(f"{name} must be between 1 and {maximum}")
    return value


def _cursor(value: str | None) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, "cursor", 1024)


def _segment(value: str, name: str) -> str:
    value = _bounded_text(value, name, 256)
    return quote(value, safe="")


def _canonical_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _rfc3339(value: str, name: str) -> tuple[str, datetime]:
    value = _bounded_text(value, name, 64)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProviderRequestError(f"{name} must be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderRequestError(f"{name} must include a timezone")
    return value, parsed


def _drive_literal(value: str) -> str:
    # Drive query literals escape backslash first, then single quote.
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _require_scope(
    scope: ReadConnectorScope,
    *,
    connector: str,
    operation: str,
    object_scope: str,
) -> str:
    if not isinstance(scope, ReadConnectorScope):
        raise ProviderRequestError("scope must be ReadConnectorScope")
    if scope.connector != connector:
        raise ProviderRequestError(f"scope is not for {connector}")
    object_scope = _bounded_text(object_scope, "object_scope", 256)
    if not scope.allows(object_scope=object_scope, operation=operation):
        raise ProviderRequestError("provider request is outside exact connector scope")
    return object_scope


@dataclass(frozen=True)
class ProviderRequestPlan:
    connector: str
    authority_operation: str
    provider_operation: str
    object_scope: str
    method: Method
    host: str
    path: str
    query: tuple[tuple[str, str], ...]
    headers: tuple[tuple[str, str], ...]
    body_json: str | None
    response_kind: ResponseKind
    expected_content_types: tuple[str, ...]
    max_response_bytes: int
    schema: str = REQUEST_SCHEMA
    credential_mode: str = "bearer_injected_at_execute"
    follow_redirects: bool = False
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != REQUEST_SCHEMA:
            raise ProviderRequestError("unsupported provider request schema")
        if self.production_activation is not False:
            raise ProviderRequestError("production activation must remain false")
        if self.credential_mode != "bearer_injected_at_execute":
            raise ProviderRequestError("provider request cannot carry credential material")
        if self.follow_redirects is not False:
            raise ProviderRequestError("provider request redirects must remain disabled")
        if self.connector not in {"google_calendar", "google_drive", "gmail", "notion"}:
            raise ProviderRequestError("unsupported provider request connector")
        if self.method not in {"GET", "POST"}:
            raise ProviderRequestError("provider request method is unsupported")
        if self.host not in _ALLOWED_HOSTS:
            raise ProviderRequestError("provider request host is not allowlisted")
        if not self.path.startswith("/") or "?" in self.path or "#" in self.path:
            raise ProviderRequestError("provider request path must be an absolute path without query")
        if "\\" in self.path or "/../" in self.path or self.path.endswith("/.."):
            raise ProviderRequestError("provider request path contains traversal syntax")
        keys = [key for key, _ in self.query]
        if len(keys) != len(set(keys)):
            raise ProviderRequestError("provider request query contains duplicate keys")
        for key, value in self.query:
            _bounded_text(key, "query key", 64)
            _bounded_text(value, f"query value {key}", 4096, allow_blank=True)
        header_names = [name.casefold() for name, _ in self.headers]
        if len(header_names) != len(set(header_names)):
            raise ProviderRequestError("provider request headers contain duplicates")
        if any(name in _CREDENTIAL_HEADERS for name in header_names):
            raise ProviderRequestError("provider request cannot contain credential headers")
        if any(name not in _ALLOWED_HEADERS for name in header_names):
            raise ProviderRequestError("provider request contains an unsupported header")
        for name, value in self.headers:
            _bounded_text(name, "header name", 64)
            _bounded_text(value, f"header {name}", 256)
        if self.method == "GET" and self.body_json is not None:
            raise ProviderRequestError("GET provider request cannot contain a body")
        if self.method == "POST":
            if self.connector != "notion":
                raise ProviderRequestError("v1 POST provider requests are Notion-only reads")
            if self.body_json is None:
                raise ProviderRequestError("Notion POST provider request requires canonical JSON")
            try:
                parsed = json.loads(self.body_json)
            except json.JSONDecodeError as exc:
                raise ProviderRequestError("provider request body is invalid JSON") from exc
            if not isinstance(parsed, dict) or _canonical_json(parsed) != self.body_json:
                raise ProviderRequestError("provider request body must be canonical JSON object")
            if len(self.body_json.encode("utf-8")) > 32 * 1024:
                raise ProviderRequestError("provider request body exceeds 32 KiB")
        if self.response_kind not in {"json", "text"}:
            raise ProviderRequestError("provider response kind is unsupported")
        if not self.expected_content_types:
            raise ProviderRequestError("provider request requires expected content types")
        if any(
            not isinstance(item, str) or not item or len(item) > 100
            for item in self.expected_content_types
        ):
            raise ProviderRequestError("provider content type allowlist is invalid")
        if (
            isinstance(self.max_response_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
            or not 1 <= self.max_response_bytes <= 8 * 1024 * 1024
        ):
            raise ProviderRequestError("provider response budget is invalid")
        if self.connector == "notion":
            headers = {name.casefold(): value for name, value in self.headers}
            if headers.get("notion-version") != NOTION_VERSION:
                raise ProviderRequestError("Notion request must pin the current API version")
        elif any(name.casefold() == "notion-version" for name, _ in self.headers):
            raise ProviderRequestError("Notion-Version cannot be sent to Google")

    @property
    def url(self) -> str:
        suffix = urlencode(self.query, doseq=False)
        return f"https://{self.host}{self.path}" + (f"?{suffix}" if suffix else "")

    @property
    def body_sha256(self) -> str | None:
        if self.body_json is None:
            return None
        return hashlib.sha256(self.body_json.encode("utf-8")).hexdigest()

    def to_audit_dict(self) -> dict:
        """Return request identity without query/body content or credentials."""
        return {
            "schema": self.schema,
            "connector": self.connector,
            "capability_id": capability_id(self.connector),
            "authority_operation": self.authority_operation,
            "provider_operation": self.provider_operation,
            "object_scope": self.object_scope,
            "method": self.method,
            "host": self.host,
            "path": self.path,
            "query_keys": [key for key, _ in self.query],
            "header_names": [name for name, _ in self.headers],
            "body_sha256": self.body_sha256,
            "response_kind": self.response_kind,
            "max_response_bytes": self.max_response_bytes,
            "credential_mode": self.credential_mode,
            "follow_redirects": False,
            "production_activation": False,
        }


def _google_json_plan(
    *,
    scope: ReadConnectorScope,
    connector: str,
    authority_operation: str,
    provider_operation: str,
    object_scope: str,
    host: str,
    path: str,
    query: list[tuple[str, str]],
    max_response_bytes: int,
) -> ProviderRequestPlan:
    object_scope = _require_scope(
        scope,
        connector=connector,
        operation=authority_operation,
        object_scope=object_scope,
    )
    return ProviderRequestPlan(
        connector=connector,
        authority_operation=authority_operation,
        provider_operation=provider_operation,
        object_scope=object_scope,
        method="GET",
        host=host,
        path=path,
        query=tuple(query),
        headers=(("Accept", "application/json"),),
        body_json=None,
        response_kind="json",
        expected_content_types=_JSON_TYPES,
        max_response_bytes=max_response_bytes,
    )


def build_calendar_list(
    scope: ReadConnectorScope,
    *,
    object_scope: str = "calendar-list",
    page_size: int = 50,
    page_token: str | None = None,
) -> ProviderRequestPlan:
    page_size = _page_size(page_size, maximum=100)
    page_token = _cursor(page_token)
    query = [
        ("maxResults", str(page_size)),
        ("minAccessRole", "reader"),
        ("fields", _CALENDAR_LIST_FIELDS),
    ]
    if page_token is not None:
        query.append(("pageToken", page_token))
    return _google_json_plan(
        scope=scope,
        connector="google_calendar",
        authority_operation="calendar_list",
        provider_operation="calendarList.list",
        object_scope=object_scope,
        host=_GOOGLE_HOST,
        path="/calendar/v3/users/me/calendarList",
        query=query,
        max_response_bytes=512 * 1024,
    )


def build_calendar_event_get(
    scope: ReadConnectorScope,
    *,
    calendar_id: str,
    event_id: str,
) -> ProviderRequestPlan:
    calendar_id = _require_scope(
        scope,
        connector="google_calendar",
        operation="event_get",
        object_scope=calendar_id,
    )
    return ProviderRequestPlan(
        connector="google_calendar",
        authority_operation="event_get",
        provider_operation="events.get",
        object_scope=calendar_id,
        method="GET",
        host=_GOOGLE_HOST,
        path=f"/calendar/v3/calendars/{_segment(calendar_id, 'calendar_id')}/events/{_segment(event_id, 'event_id')}",
        query=(("fields", _CALENDAR_EVENT_FIELDS),),
        headers=(("Accept", "application/json"),),
        body_json=None,
        response_kind="json",
        expected_content_types=_JSON_TYPES,
        max_response_bytes=256 * 1024,
    )


def build_calendar_event_search(
    scope: ReadConnectorScope,
    *,
    calendar_id: str,
    time_min: str,
    time_max: str,
    query_text: str | None = None,
    page_size: int = 50,
    page_token: str | None = None,
) -> ProviderRequestPlan:
    calendar_id = _require_scope(
        scope,
        connector="google_calendar",
        operation="event_search",
        object_scope=calendar_id,
    )
    time_min, parsed_min = _rfc3339(time_min, "time_min")
    time_max, parsed_max = _rfc3339(time_max, "time_max")
    if parsed_min >= parsed_max:
        raise ProviderRequestError("time_min must be before time_max")
    if (parsed_max - parsed_min).total_seconds() > 366 * 24 * 60 * 60:
        raise ProviderRequestError("calendar search window must not exceed 366 days")
    page_size = _page_size(page_size, maximum=100)
    page_token = _cursor(page_token)
    query = [
        ("timeMin", time_min),
        ("timeMax", time_max),
        ("singleEvents", "true"),
        ("orderBy", "startTime"),
        ("maxResults", str(page_size)),
        ("fields", _CALENDAR_EVENT_LIST_FIELDS),
    ]
    if query_text is not None:
        query.append(("q", _bounded_text(query_text, "calendar query", 200)))
    if page_token is not None:
        query.append(("pageToken", page_token))
    return ProviderRequestPlan(
        connector="google_calendar",
        authority_operation="event_search",
        provider_operation="events.list",
        object_scope=calendar_id,
        method="GET",
        host=_GOOGLE_HOST,
        path=f"/calendar/v3/calendars/{_segment(calendar_id, 'calendar_id')}/events",
        query=tuple(query),
        headers=(("Accept", "application/json"),),
        body_json=None,
        response_kind="json",
        expected_content_types=_JSON_TYPES,
        max_response_bytes=1024 * 1024,
    )


def build_drive_file_search(
    scope: ReadConnectorScope,
    *,
    parent_id: str,
    name_contains: str,
    page_size: int = 50,
    page_token: str | None = None,
) -> ProviderRequestPlan:
    parent_id = _require_scope(
        scope,
        connector="google_drive",
        operation="file_search",
        object_scope=parent_id,
    )
    term = _bounded_text(name_contains, "Drive name search", 120)
    page_size = _page_size(page_size, maximum=100)
    page_token = _cursor(page_token)
    q = (
        f"'{_drive_literal(parent_id)}' in parents and trashed = false "
        f"and name contains '{_drive_literal(term)}'"
    )
    query = [
        ("q", q),
        ("pageSize", str(page_size)),
        ("spaces", "drive"),
        ("fields", _DRIVE_FILE_LIST_FIELDS),
    ]
    if page_token is not None:
        query.append(("pageToken", page_token))
    return _google_json_plan(
        scope=scope,
        connector="google_drive",
        authority_operation="file_search",
        provider_operation="files.list",
        object_scope=parent_id,
        host=_GOOGLE_HOST,
        path="/drive/v3/files",
        query=query,
        max_response_bytes=1024 * 1024,
    )


def build_drive_file_metadata(
    scope: ReadConnectorScope,
    *,
    file_id: str,
) -> ProviderRequestPlan:
    file_id = _require_scope(
        scope,
        connector="google_drive",
        operation="file_metadata",
        object_scope=file_id,
    )
    return _google_json_plan(
        scope=scope,
        connector="google_drive",
        authority_operation="file_metadata",
        provider_operation="files.get",
        object_scope=file_id,
        host=_GOOGLE_HOST,
        path=f"/drive/v3/files/{_segment(file_id, 'file_id')}",
        query=[("supportsAllDrives", "true"), ("fields", _DRIVE_FILE_FIELDS)],
        max_response_bytes=256 * 1024,
    )


def build_drive_document_read(
    scope: ReadConnectorScope,
    *,
    file_id: str,
) -> ProviderRequestPlan:
    """Plan a bounded text export for a native Google Docs document.

    Stored/binary Drive downloads and Sheets/Slides exports are intentionally not
    representable in provider request v1.  Later format-specific read operations
    can add their own reviewed projection rather than widening this one.
    """
    file_id = _require_scope(
        scope,
        connector="google_drive",
        operation="document_read",
        object_scope=file_id,
    )
    return ProviderRequestPlan(
        connector="google_drive",
        authority_operation="document_read",
        provider_operation="files.export:text/plain",
        object_scope=file_id,
        method="GET",
        host=_GOOGLE_HOST,
        path=f"/drive/v3/files/{_segment(file_id, 'file_id')}/export",
        query=(("mimeType", "text/plain"),),
        headers=(("Accept", "text/plain"),),
        body_json=None,
        response_kind="text",
        expected_content_types=_TEXT_TYPES,
        max_response_bytes=2 * 1024 * 1024,
    )


def build_gmail_message_search(
    scope: ReadConnectorScope,
    *,
    object_scope: str,
    query_text: str,
    page_size: int = 50,
    page_token: str | None = None,
) -> ProviderRequestPlan:
    object_scope = _require_scope(
        scope,
        connector="gmail",
        operation="message_search",
        object_scope=object_scope,
    )
    page_size = _page_size(page_size, maximum=100)
    page_token = _cursor(page_token)
    query = [
        ("q", _bounded_text(query_text, "Gmail query", 300)),
        ("maxResults", str(page_size)),
        ("includeSpamTrash", "false"),
        ("fields", _GMAIL_MESSAGE_LIST_FIELDS),
    ]
    if page_token is not None:
        query.append(("pageToken", page_token))
    return _google_json_plan(
        scope=scope,
        connector="gmail",
        authority_operation="message_search",
        provider_operation="users.messages.list",
        object_scope=object_scope,
        host=_GMAIL_HOST,
        path="/gmail/v1/users/me/messages",
        query=query,
        max_response_bytes=512 * 1024,
    )


def build_gmail_message_get(
    scope: ReadConnectorScope,
    *,
    message_id: str,
) -> ProviderRequestPlan:
    message_id = _require_scope(
        scope,
        connector="gmail",
        operation="message_get",
        object_scope=message_id,
    )
    return _google_json_plan(
        scope=scope,
        connector="gmail",
        authority_operation="message_get",
        provider_operation="users.messages.get",
        object_scope=message_id,
        host=_GMAIL_HOST,
        path=f"/gmail/v1/users/me/messages/{_segment(message_id, 'message_id')}",
        query=[("format", "full"), ("fields", _GMAIL_MESSAGE_FIELDS)],
        max_response_bytes=2 * 1024 * 1024,
    )


def build_gmail_thread_get(
    scope: ReadConnectorScope,
    *,
    thread_id: str,
) -> ProviderRequestPlan:
    thread_id = _require_scope(
        scope,
        connector="gmail",
        operation="thread_get",
        object_scope=thread_id,
    )
    return _google_json_plan(
        scope=scope,
        connector="gmail",
        authority_operation="thread_get",
        provider_operation="users.threads.get",
        object_scope=thread_id,
        host=_GMAIL_HOST,
        path=f"/gmail/v1/users/me/threads/{_segment(thread_id, 'thread_id')}",
        query=[("format", "full"), ("fields", _GMAIL_THREAD_FIELDS)],
        max_response_bytes=4 * 1024 * 1024,
    )


def _notion_headers(*, body: bool) -> tuple[tuple[str, str], ...]:
    values = [("Accept", "application/json"), ("Notion-Version", NOTION_VERSION)]
    if body:
        values.append(("Content-Type", "application/json"))
    return tuple(values)


def build_notion_search(
    scope: ReadConnectorScope,
    *,
    object_scope: str,
    query_text: str,
    page_size: int = 50,
    start_cursor: str | None = None,
) -> ProviderRequestPlan:
    object_scope = _require_scope(
        scope,
        connector="notion",
        operation="search",
        object_scope=object_scope,
    )
    body: dict[str, object] = {
        "query": _bounded_text(query_text, "Notion query", 200),
        "page_size": _page_size(page_size, maximum=100),
    }
    start_cursor = _cursor(start_cursor)
    if start_cursor is not None:
        body["start_cursor"] = start_cursor
    return ProviderRequestPlan(
        connector="notion",
        authority_operation="search",
        provider_operation="search",
        object_scope=object_scope,
        method="POST",
        host=_NOTION_HOST,
        path="/v1/search",
        query=(),
        headers=_notion_headers(body=True),
        body_json=_canonical_json(body),
        response_kind="json",
        expected_content_types=_JSON_TYPES,
        max_response_bytes=1024 * 1024,
    )


def build_notion_page_get(
    scope: ReadConnectorScope,
    *,
    page_id: str,
) -> ProviderRequestPlan:
    page_id = _require_scope(
        scope,
        connector="notion",
        operation="page_get",
        object_scope=page_id,
    )
    return ProviderRequestPlan(
        connector="notion",
        authority_operation="page_get",
        provider_operation="pages.retrieve",
        object_scope=page_id,
        method="GET",
        host=_NOTION_HOST,
        path=f"/v1/pages/{_segment(page_id, 'page_id')}",
        query=(),
        headers=_notion_headers(body=False),
        body_json=None,
        response_kind="json",
        expected_content_types=_JSON_TYPES,
        max_response_bytes=1024 * 1024,
    )


def build_notion_block_children(
    scope: ReadConnectorScope,
    *,
    block_id: str,
    page_size: int = 50,
    start_cursor: str | None = None,
) -> ProviderRequestPlan:
    """Read Notion page/block content under the v1 ``page_get`` authority.

    Notion exposes page properties through ``GET /v1/pages/{id}``, while page
    content is read as block children.  Keeping both request forms under the
    same exact object scope avoids pretending a metadata-only page request is a
    content read, without creating a write-capable or cross-page authority.
    """
    block_id = _require_scope(
        scope,
        connector="notion",
        operation="page_get",
        object_scope=block_id,
    )
    query = [("page_size", str(_page_size(page_size, maximum=100)))]
    start_cursor = _cursor(start_cursor)
    if start_cursor is not None:
        query.append(("start_cursor", start_cursor))
    return ProviderRequestPlan(
        connector="notion",
        authority_operation="page_get",
        provider_operation="blocks.children.list",
        object_scope=block_id,
        method="GET",
        host=_NOTION_HOST,
        path=f"/v1/blocks/{_segment(block_id, 'block_id')}/children",
        query=tuple(query),
        headers=_notion_headers(body=False),
        body_json=None,
        response_kind="json",
        expected_content_types=_JSON_TYPES,
        max_response_bytes=2 * 1024 * 1024,
    )


def build_notion_data_source_query(
    scope: ReadConnectorScope,
    *,
    data_source_id: str,
    page_size: int = 50,
    start_cursor: str | None = None,
) -> ProviderRequestPlan:
    """Map stable T-037 authority v1 to Notion's current data-source query API."""
    data_source_id = _require_scope(
        scope,
        connector="notion",
        operation="database_query",
        object_scope=data_source_id,
    )
    body: dict[str, object] = {"page_size": _page_size(page_size, maximum=100)}
    start_cursor = _cursor(start_cursor)
    if start_cursor is not None:
        body["start_cursor"] = start_cursor
    return ProviderRequestPlan(
        connector="notion",
        authority_operation="database_query",
        provider_operation="data_source_query",
        object_scope=data_source_id,
        method="POST",
        host=_NOTION_HOST,
        path=f"/v1/data_sources/{_segment(data_source_id, 'data_source_id')}/query",
        query=(),
        headers=_notion_headers(body=True),
        body_json=_canonical_json(body),
        response_kind="json",
        expected_content_types=_JSON_TYPES,
        max_response_bytes=2 * 1024 * 1024,
    )
