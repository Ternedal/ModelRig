"""T-037 dormant provider response validation for Google/Notion read connectors.

This module is intentionally not an HTTP transport.  It accepts response bytes
only after a host transport has executed one already-authorized
``CredentialBoundProviderRequest`` and converts the provider payload into a
closed projection plus source receipts.

The boundary is defensive on purpose:

* only HTTP 200 is accepted for v1 read operations;
* content type and byte budget must match the immutable request plan;
* UTF-8 and JSON are strict (duplicate object keys and non-finite numbers fail);
* provider-specific top-level shapes are validated before projection;
* model-visible projections contain only reviewed top-level fields;
* every projected item receives stable source/object/revision evidence;
* response audit contains hashes/metadata only, never body or projection data;
* there is no socket/HTTP client, credential lookup, route or runtime activation.

``production_activation`` remains structurally false.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .read_connector_credential_binding import CredentialBoundProviderRequest
from .read_connector_package_contract import (
    ReadConnectorContractError,
    ReadConnectorSourceReceipt,
    capability_id,
)
from .read_connector_provider_request import ProviderRequestPlan

RESPONSE_SCHEMA = "kaliv-read-connector-provider-response/v1"
ITEM_SCHEMA = "kaliv-read-connector-provider-item/v1"
PRODUCTION_ACTIVATION = False

_MAX_ITEMS = 1_000
_MAX_JSON_DEPTH = 40
_MAX_JSON_NODES = 50_000
_PROVIDER_ID = re.compile(r"^[^\x00-\x1f\x7f]{1,512}$")
_RECEIPT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProviderResponseError(ReadConnectorContractError):
    """Provider bytes cannot be trusted/projected inside the T-037 read contract."""


def _now(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderResponseError("retrieved_at must be a non-negative integer")
    return value


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProviderResponseError("provider projection is not canonical JSON") from exc


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _provider_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not _PROVIDER_ID.fullmatch(value):
        raise ProviderResponseError(f"{name} is not a stable provider identifier")
    return value


def _receipt_object_id(value: str) -> str:
    if _RECEIPT_ID.fullmatch(value):
        return value
    return f"sha256:{_sha_text(value)}"


def _source_id(connector: str, kind: str, provider_id: str) -> str:
    # Hash the raw provider id so e-mail-like Calendar ids stay out of the
    # privacy-minimized receipt identity while the connector/kind remain
    # human-auditable and stable.
    return f"{connector}:{kind}:{_sha_text(provider_id)}"


def _revision(prefix: str, value: Any, projection: dict[str, Any]) -> str:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        text = str(value)
        if text and len(text) <= 180:
            candidate = f"{prefix}:{text}"
            if _RECEIPT_ID.fullmatch(candidate):
                return candidate
            return f"{prefix}:sha256:{_sha_text(text)}"
    return f"sha256:{_sha_text(_canonical(projection))}"


def _content_type(value: str) -> str:
    if not isinstance(value, str):
        raise ProviderResponseError("provider content type must be a string")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ProviderResponseError("provider content type is invalid")
    mime = value.split(";", 1)[0].strip().casefold()
    if not mime or len(mime) > 100:
        raise ProviderResponseError("provider content type is invalid")
    return mime


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProviderResponseError("provider JSON contains duplicate object keys")
        result[key] = value
    return result


def _parse_json(body: bytes) -> dict[str, Any]:
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProviderResponseError("provider JSON is not valid UTF-8") from exc

    def reject_constant(_: str) -> None:
        raise ProviderResponseError("provider JSON contains a non-finite number")

    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=reject_constant,
        )
    except ProviderResponseError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProviderResponseError("provider response is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ProviderResponseError("provider JSON root must be an object")
    _guard_json_complexity(value)
    return value


def _guard_json_complexity(value: Any) -> None:
    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise ProviderResponseError("provider JSON exceeds structural node budget")
        if depth > _MAX_JSON_DEPTH:
            raise ProviderResponseError("provider JSON exceeds nesting depth budget")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderResponseError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProviderResponseError(f"{name} must be an array")
    if len(value) > _MAX_ITEMS:
        raise ProviderResponseError(f"{name} exceeds item budget")
    return value


def _str(value: Any, name: str, *, required: bool = True, maximum: int = 8192) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > maximum:
        raise ProviderResponseError(f"{name} must be a bounded string")
    if required and not value:
        raise ProviderResponseError(f"{name} must not be empty")
    if any(ord(ch) < 0x20 and ch not in "\r\n\t" for ch in value):
        raise ProviderResponseError(f"{name} contains invalid control characters")
    return value


def _cursor(payload: dict[str, Any], *, google_key: str | None = None) -> str | None:
    if google_key is not None:
        raw = payload.get(google_key)
        if raw is None:
            return None
        return _provider_id(raw, google_key)
    has_more = payload.get("has_more")
    raw = payload.get("next_cursor")
    if has_more is None:
        raise ProviderResponseError("Notion list response is missing has_more")
    if not isinstance(has_more, bool):
        raise ProviderResponseError("Notion has_more must be boolean")
    if has_more:
        if raw is None:
            raise ProviderResponseError("Notion paginated response is missing next_cursor")
        return _provider_id(raw, "next_cursor")
    if raw is not None:
        raise ProviderResponseError("Notion non-paginated response cannot carry next_cursor")
    return None


def _pick(source: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {name: source[name] for name in fields if name in source}


def _calendar_event(source: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    provider_id = _provider_id(source.get("id"), "calendar event id")
    projection = _pick(
        source,
        (
            "id",
            "etag",
            "status",
            "summary",
            "start",
            "end",
            "updated",
            "recurringEventId",
            "originalStartTime",
        ),
    )
    return provider_id, projection, _revision("etag", source.get("etag") or source.get("updated"), projection)


def _calendar_entry(source: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    provider_id = _provider_id(source.get("id"), "calendar id")
    projection = _pick(source, ("id", "etag", "summary", "timeZone", "primary", "accessRole"))
    return provider_id, projection, _revision("etag", source.get("etag"), projection)


def _drive_file(source: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    provider_id = _provider_id(source.get("id"), "Drive file id")
    projection = _pick(
        source,
        ("id", "name", "mimeType", "modifiedTime", "version", "md5Checksum", "trashed", "parents", "size"),
    )
    marker = source.get("version")
    prefix = "version"
    if marker is None:
        marker, prefix = source.get("md5Checksum"), "md5"
    if marker is None:
        marker, prefix = source.get("modifiedTime"), "modified"
    return provider_id, projection, _revision(prefix, marker, projection)


def _gmail_message(source: dict[str, Any], *, detailed: bool, page_digest: str) -> tuple[str, dict[str, Any], str]:
    provider_id = _provider_id(source.get("id"), "Gmail message id")
    fields = ("id", "threadId") if not detailed else (
        "id",
        "threadId",
        "labelIds",
        "snippet",
        "historyId",
        "internalDate",
        "payload",
    )
    projection = _pick(source, fields)
    if detailed:
        marker = source.get("historyId")
        prefix = "history"
        if marker is None:
            marker, prefix = source.get("internalDate"), "internal"
        revision = _revision(prefix, marker, projection)
    else:
        revision = f"listing:{page_digest}"
    return provider_id, projection, revision


def _notion_object(source: dict[str, Any], *, name: str) -> tuple[str, dict[str, Any], str]:
    provider_id = _provider_id(source.get("id"), f"{name} id")
    projection = _pick(
        source,
        (
            "object",
            "id",
            "created_time",
            "last_edited_time",
            "archived",
            "in_trash",
            "url",
            "parent",
            "properties",
            "type",
        ),
    )
    block_type = source.get("type")
    if isinstance(block_type, str) and block_type in source:
        projection[block_type] = source[block_type]
    marker = source.get("last_edited_time") or source.get("created_time")
    return provider_id, projection, _revision("edited", marker, projection)


@dataclass(frozen=True)
class ProjectedProviderItem:
    connector: str
    authority_operation: str
    provider_operation: str
    object_scope: str
    source_id: str
    object_id: str
    revision: str
    projection_json: str
    retrieved_at: int
    schema: str = ITEM_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != ITEM_SCHEMA:
            raise ProviderResponseError("unsupported provider item schema")
        if self.production_activation is not False:
            raise ProviderResponseError("provider item production activation must remain false")
        if not isinstance(self.source_id, str) or not _RECEIPT_ID.fullmatch(self.source_id):
            raise ProviderResponseError("projected source_id has invalid format")
        if not isinstance(self.object_id, str) or not _RECEIPT_ID.fullmatch(self.object_id):
            raise ProviderResponseError("projected object_id has invalid format")
        if not isinstance(self.revision, str) or not _RECEIPT_ID.fullmatch(self.revision):
            raise ProviderResponseError("projected revision has invalid format")
        _now(self.retrieved_at)
        try:
            parsed = json.loads(self.projection_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProviderResponseError("projection_json must be canonical JSON") from exc
        if not isinstance(parsed, dict) or _canonical(parsed) != self.projection_json:
            raise ProviderResponseError("projection_json must be canonical JSON object")

    @property
    def projection(self) -> dict[str, Any]:
        value = json.loads(self.projection_json)
        assert isinstance(value, dict)
        return value

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "connector": self.connector,
            "capability_id": capability_id(self.connector),
            "authority_operation": self.authority_operation,
            "provider_operation": self.provider_operation,
            "object_scope": self.object_scope,
            "source_id": self.source_id,
            "object_id": self.object_id,
            "revision": self.revision,
            "projection": self.projection,
            "retrieved_at": _iso(self.retrieved_at),
            "production_activation": False,
        }


@dataclass(frozen=True)
class ValidatedProviderResponse:
    connector: str
    authority_operation: str
    provider_operation: str
    object_scope: str
    grant_id: str
    scope_sha256: str
    account_ref: str
    workspace_ref: str | None
    status_code: int
    content_type: str
    response_bytes: int
    body_sha256: str
    retrieved_at: int
    items: tuple[ProjectedProviderItem, ...]
    source_receipts: tuple[ReadConnectorSourceReceipt, ...]
    next_cursor: str | None
    schema: str = RESPONSE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != RESPONSE_SCHEMA:
            raise ProviderResponseError("unsupported provider response schema")
        if self.production_activation is not False:
            raise ProviderResponseError("provider response production activation must remain false")
        if self.status_code != 200:
            raise ProviderResponseError("validated provider response must be HTTP 200")
        if not isinstance(self.response_bytes, int) or self.response_bytes < 0:
            raise ProviderResponseError("response_bytes must be non-negative")
        if not _SHA256.fullmatch(self.body_sha256):
            raise ProviderResponseError("body_sha256 is invalid")
        _now(self.retrieved_at)
        if len(self.items) != len(self.source_receipts):
            raise ProviderResponseError("every projected item requires one source receipt")
        if self.next_cursor is not None:
            _provider_id(self.next_cursor, "next_cursor")

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "connector": self.connector,
            "capability_id": capability_id(self.connector),
            "authority_operation": self.authority_operation,
            "provider_operation": self.provider_operation,
            "object_scope": self.object_scope,
            "grant_id": self.grant_id,
            "scope_sha256": self.scope_sha256,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "response_bytes": self.response_bytes,
            "body_sha256": self.body_sha256,
            "item_count": len(self.items),
            "has_next_cursor": self.next_cursor is not None,
            "retrieved_at": _iso(self.retrieved_at),
            "production_activation": False,
        }


def _project(
    plan: ProviderRequestPlan,
    payload: dict[str, Any] | str,
    *,
    body_sha256: str,
) -> tuple[list[tuple[str, str, dict[str, Any], str]], str | None]:
    op = plan.provider_operation
    rows: list[tuple[str, str, dict[str, Any], str]] = []

    if op == "calendarList.list":
        root = _dict(payload, "calendar list response")
        for raw in _list(root.get("items", []), "calendar items"):
            provider_id, projection, revision = _calendar_entry(_dict(raw, "calendar item"))
            rows.append(("calendar", provider_id, projection, revision))
        return rows, _cursor(root, google_key="nextPageToken")

    if op == "events.get":
        root = _dict(payload, "calendar event response")
        provider_id, projection, revision = _calendar_event(root)
        return [("event", provider_id, projection, revision)], None

    if op == "events.list":
        root = _dict(payload, "calendar event list response")
        for raw in _list(root.get("items", []), "calendar event items"):
            provider_id, projection, revision = _calendar_event(_dict(raw, "calendar event"))
            rows.append(("event", provider_id, projection, revision))
        return rows, _cursor(root, google_key="nextPageToken")

    if op == "files.list":
        root = _dict(payload, "Drive file list response")
        incomplete = root.get("incompleteSearch")
        if incomplete not in (None, False):
            raise ProviderResponseError("Drive incompleteSearch responses are not accepted")
        for raw in _list(root.get("files", []), "Drive files"):
            provider_id, projection, revision = _drive_file(_dict(raw, "Drive file"))
            rows.append(("file", provider_id, projection, revision))
        return rows, _cursor(root, google_key="nextPageToken")

    if op == "files.get":
        root = _dict(payload, "Drive file response")
        provider_id, projection, revision = _drive_file(root)
        if provider_id != plan.object_scope:
            raise ProviderResponseError("Drive file response id does not match request object scope")
        return [("file", provider_id, projection, revision)], None

    if op == "files.export:text/plain":
        if not isinstance(payload, str):
            raise ProviderResponseError("Drive document export must be text")
        projection = {"text": payload}
        provider_id = _provider_id(plan.object_scope, "Drive document object scope")
        return [("document", provider_id, projection, f"sha256:{body_sha256}")], None

    if op == "users.messages.list":
        root = _dict(payload, "Gmail message list response")
        for raw in _list(root.get("messages", []), "Gmail messages"):
            provider_id, projection, revision = _gmail_message(
                _dict(raw, "Gmail message"),
                detailed=False,
                page_digest=body_sha256,
            )
            rows.append(("message", provider_id, projection, revision))
        return rows, _cursor(root, google_key="nextPageToken")

    if op == "users.messages.get":
        root = _dict(payload, "Gmail message response")
        provider_id, projection, revision = _gmail_message(
            root,
            detailed=True,
            page_digest=body_sha256,
        )
        if provider_id != plan.object_scope:
            raise ProviderResponseError("Gmail message response id does not match request object scope")
        return [("message", provider_id, projection, revision)], None

    if op == "users.threads.get":
        root = _dict(payload, "Gmail thread response")
        provider_id = _provider_id(root.get("id"), "Gmail thread id")
        if provider_id != plan.object_scope:
            raise ProviderResponseError("Gmail thread response id does not match request object scope")
        messages = _list(root.get("messages", []), "Gmail thread messages")
        projection = _pick(root, ("id", "historyId"))
        projection["messages"] = [
            _gmail_message(_dict(raw, "Gmail thread message"), detailed=True, page_digest=body_sha256)[1]
            for raw in messages
        ]
        revision = _revision("history", root.get("historyId"), projection)
        return [("thread", provider_id, projection, revision)], None

    if op == "search":
        root = _dict(payload, "Notion search response")
        for raw in _list(root.get("results", []), "Notion search results"):
            provider_id, projection, revision = _notion_object(_dict(raw, "Notion search item"), name="Notion search item")
            rows.append(("object", provider_id, projection, revision))
        return rows, _cursor(root)

    if op == "pages.retrieve":
        root = _dict(payload, "Notion page response")
        provider_id, projection, revision = _notion_object(root, name="Notion page")
        if provider_id != plan.object_scope:
            raise ProviderResponseError("Notion page response id does not match request object scope")
        return [("page", provider_id, projection, revision)], None

    if op == "blocks.children.list":
        root = _dict(payload, "Notion block children response")
        for raw in _list(root.get("results", []), "Notion blocks"):
            provider_id, projection, revision = _notion_object(_dict(raw, "Notion block"), name="Notion block")
            rows.append(("block", provider_id, projection, revision))
        return rows, _cursor(root)

    if op == "data_source_query":
        root = _dict(payload, "Notion data source query response")
        for raw in _list(root.get("results", []), "Notion query results"):
            provider_id, projection, revision = _notion_object(_dict(raw, "Notion query item"), name="Notion query item")
            rows.append(("page", provider_id, projection, revision))
        return rows, _cursor(root)

    raise ProviderResponseError("provider operation has no reviewed response projector")


def validate_provider_response(
    binding: CredentialBoundProviderRequest,
    *,
    status_code: int,
    content_type: str,
    body: bytes,
    retrieved_at: int,
) -> ValidatedProviderResponse:
    """Validate and project provider bytes after transport execution.

    This function does not perform I/O and never receives a bearer.  Passing the
    credential binding rather than a free-standing request plan binds the
    resulting source receipts to the exact grant/scope/account that authorized
    the request.
    """
    if not isinstance(binding, CredentialBoundProviderRequest):
        raise ProviderResponseError("response requires CredentialBoundProviderRequest")
    plan = binding.plan
    if plan.production_activation is not False or binding.production_activation is not False:
        raise ProviderResponseError("provider response path must remain dormant")
    if isinstance(status_code, bool) or not isinstance(status_code, int) or not 100 <= status_code <= 599:
        raise ProviderResponseError("provider HTTP status is invalid")
    if status_code != 200:
        raise ProviderResponseError(f"provider read failed with HTTP {status_code}")
    retrieved_at = _now(retrieved_at)
    mime = _content_type(content_type)
    expected = {item.casefold() for item in plan.expected_content_types}
    if mime not in expected:
        raise ProviderResponseError("provider response content type is not allowlisted")
    if not isinstance(body, bytes):
        raise ProviderResponseError("provider response body must be bytes")
    if len(body) > plan.max_response_bytes:
        raise ProviderResponseError("provider response exceeds request byte budget")

    body_sha256 = _sha_bytes(body)
    if plan.response_kind == "json":
        payload: dict[str, Any] | str = _parse_json(body)
    elif plan.response_kind == "text":
        try:
            payload = body.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ProviderResponseError("provider text is not valid UTF-8") from exc
    else:
        raise ProviderResponseError("provider response kind is unsupported")

    projected_rows, next_cursor = _project(plan, payload, body_sha256=body_sha256)
    items: list[ProjectedProviderItem] = []
    receipts: list[ReadConnectorSourceReceipt] = []
    for kind, provider_id, projection, revision in projected_rows:
        source_id = _source_id(plan.connector, kind, provider_id)
        object_id = _receipt_object_id(provider_id)
        item = ProjectedProviderItem(
            connector=plan.connector,
            authority_operation=plan.authority_operation,
            provider_operation=plan.provider_operation,
            object_scope=plan.object_scope,
            source_id=source_id,
            object_id=object_id,
            revision=revision,
            projection_json=_canonical(projection),
            retrieved_at=retrieved_at,
        )
        receipt = ReadConnectorSourceReceipt(
            connector=plan.connector,
            grant_id=binding.grant_id,
            scope_sha256=binding.scope_sha256,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            object_scope=plan.object_scope,
            operation=plan.authority_operation,
            source_id=source_id,
            object_id=object_id,
            revision=revision,
            retrieved_at=retrieved_at,
        )
        items.append(item)
        receipts.append(receipt)

    return ValidatedProviderResponse(
        connector=plan.connector,
        authority_operation=plan.authority_operation,
        provider_operation=plan.provider_operation,
        object_scope=plan.object_scope,
        grant_id=binding.grant_id,
        scope_sha256=binding.scope_sha256,
        account_ref=binding.account_ref,
        workspace_ref=binding.workspace_ref,
        status_code=status_code,
        content_type=mime,
        response_bytes=len(body),
        body_sha256=body_sha256,
        retrieved_at=retrieved_at,
        items=tuple(items),
        source_receipts=tuple(receipts),
        next_cursor=next_cursor,
    )
