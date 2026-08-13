from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.read_connector_credential_binding import CredentialBoundProviderRequest  # noqa: E402
from app.read_connector_package_contract import ReadConnectorScope  # noqa: E402
from app.read_connector_provider_request import (  # noqa: E402
    build_calendar_event_get,
    build_calendar_event_search,
    build_calendar_list,
    build_drive_document_read,
    build_drive_file_metadata,
    build_drive_file_search,
    build_gmail_message_get,
    build_gmail_message_search,
    build_gmail_thread_get,
    build_notion_block_children,
    build_notion_data_source_query,
    build_notion_page_get,
    build_notion_search,
)
from app.read_connector_provider_response import (  # noqa: E402
    ProviderResponseError,
    validate_provider_response,
)

passed = failed = 0


def check(cond: bool, label: str) -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def raises(exc_type, fn, contains: str) -> bool:
    try:
        fn()
    except exc_type as exc:
        return contains in str(exc)
    return False


def scope(connector: str, object_scope: str, operation: str) -> ReadConnectorScope:
    return ReadConnectorScope(
        connector=connector,
        account_ref=f"acct-{connector}",
        workspace_ref="workspace-main" if connector == "notion" else None,
        object_scopes=(object_scope,),
        operations=(operation,),
    )


def binding(plan, sc: ReadConnectorScope) -> CredentialBoundProviderRequest:
    return CredentialBoundProviderRequest(
        grant_id="rcg_" + "a" * 32,
        scope_sha256=sc.digest,
        account_ref=sc.account_ref,
        workspace_ref=sc.workspace_ref,
        credential_kind=(
            "notion_integration_bearer" if sc.connector == "notion" else "google_oauth_bearer"
        ),
        plan=plan,
        prepared_at=1_800_000_000,
    )


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def validate(plan, sc, payload, *, content_type="application/json; charset=utf-8", now=1_800_000_010):
    body = payload if isinstance(payload, bytes) else encoded(payload)
    return validate_provider_response(
        binding(plan, sc),
        status_code=200,
        content_type=content_type,
        body=body,
        retrieved_at=now,
    )


def main() -> int:
    sc = scope("google_calendar", "calendar-list", "calendar_list")
    plan = build_calendar_list(sc)
    calendar_payload = {
        "nextPageToken": "page-2",
        "items": [
            {
                "id": "primary@example.com",
                "etag": '"cal-1"',
                "summary": "Primary",
                "timeZone": "Europe/Copenhagen",
                "primary": True,
                "accessRole": "owner",
                "secretCanary": "must-not-project",
            }
        ],
    }
    result = validate(plan, sc, calendar_payload)
    check(result.next_cursor == "page-2", "calendar pagination cursor is projected")
    check(len(result.items) == 1 and len(result.source_receipts) == 1, "calendar item gets one source receipt")
    item = result.items[0]
    check(item.projection["id"] == "primary@example.com", "calendar provider id remains model-visible data")
    check("secretCanary" not in item.projection, "calendar unknown top-level provider field is dropped")
    check(item.object_id.startswith("sha256:"), "receipt object id hashes provider ids outside receipt alphabet")
    check(item.source_id.startswith("gcal:calendar:"), "calendar source id uses reviewed receipt-safe alias")
    check(result.source_receipts[0].grant_id == "rcg_" + "a" * 32, "source receipt binds exact grant")
    check(result.source_receipts[0].scope_sha256 == sc.digest, "source receipt binds exact scope digest")

    stable_again = validate(plan, sc, calendar_payload, now=1_800_000_099)
    check(
        stable_again.items[0].source_id == item.source_id
        and stable_again.items[0].object_id == item.object_id
        and stable_again.items[0].revision == item.revision,
        "source/object/revision identities are stable across retrieval time",
    )

    event_sc = scope("google_calendar", "team-calendar", "event_get")
    event_plan = build_calendar_event_get(event_sc, calendar_id="team-calendar", event_id="evt-1")
    event_payload = {
        "id": "evt-1",
        "etag": '"evt-rev-7"',
        "status": "confirmed",
        "summary": "Standup",
        "start": {"dateTime": "2026-08-13T08:00:00+02:00"},
        "end": {"dateTime": "2026-08-13T08:30:00+02:00"},
        "updated": "2026-08-12T19:00:00Z",
        "attendees": [{"email": "should-not-project@example.com"}],
    }
    event_result = validate(event_plan, event_sc, event_payload)
    check(event_result.items[0].revision.startswith("etag:"), "calendar event revision prefers provider etag")
    check("attendees" not in event_result.items[0].projection, "calendar event projection drops non-reviewed fields")

    search_sc = scope("google_calendar", "team-calendar", "event_search")
    search_plan = build_calendar_event_search(
        search_sc,
        calendar_id="team-calendar",
        time_min="2026-08-13T00:00:00Z",
        time_max="2026-08-14T00:00:00Z",
    )
    search_result = validate(search_plan, search_sc, {"items": [event_payload]})
    check(search_result.items[0].source_id.startswith("gcal:event:"), "calendar event list uses event source identity")

    drive_sc = scope("google_drive", "file-1", "file_metadata")
    drive_plan = build_drive_file_metadata(drive_sc, file_id="file-1")
    drive_payload = {
        "id": "file-1",
        "name": "Roadmap",
        "mimeType": "application/vnd.google-apps.document",
        "modifiedTime": "2026-08-12T10:00:00Z",
        "version": "42",
        "trashed": False,
        "owners": [{"emailAddress": "must-not-project@example.com"}],
    }
    drive_result = validate(drive_plan, drive_sc, drive_payload)
    check(drive_result.items[0].revision == "version:42", "Drive file revision uses provider version")
    check("owners" not in drive_result.items[0].projection, "Drive metadata drops non-requested owner data")

    drive_search_sc = scope("google_drive", "folder-1", "file_search")
    drive_search_plan = build_drive_file_search(
        drive_search_sc,
        parent_id="folder-1",
        name_contains="road",
    )
    check(
        raises(
            ProviderResponseError,
            lambda: validate(drive_search_plan, drive_search_sc, {"incompleteSearch": True, "files": []}),
            "incompleteSearch",
        ),
        "Drive incomplete search fails closed instead of presenting partial results as complete",
    )

    doc_sc = scope("google_drive", "doc-1", "document_read")
    doc_plan = build_drive_document_read(doc_sc, file_id="doc-1")
    doc_bytes = "Hej ModelRig\nLinje 2".encode("utf-8")
    doc_result = validate_provider_response(
        binding(doc_plan, doc_sc),
        status_code=200,
        content_type="text/plain; charset=UTF-8",
        body=doc_bytes,
        retrieved_at=1_800_000_010,
    )
    check(doc_result.items[0].projection == {"text": "Hej ModelRig\nLinje 2"}, "Drive text export preserves exact decoded text")
    check(
        doc_result.items[0].revision == "sha256:" + hashlib.sha256(doc_bytes).hexdigest(),
        "Drive text export gets content-derived revision without extra metadata authority",
    )

    gmail_search_sc = scope("gmail", "mailbox-primary", "message_search")
    gmail_search_plan = build_gmail_message_search(
        gmail_search_sc,
        object_scope="mailbox-primary",
        query_text="subject:ModelRig",
    )
    gmail_list = validate(
        gmail_search_plan,
        gmail_search_sc,
        {
            "nextPageToken": "gmail-next",
            "resultSizeEstimate": 2,
            "messages": [
                {"id": "18fabc", "threadId": "thr-1", "snippet": "not requested by list fields"},
                {"id": "18fabd", "threadId": "thr-2"},
            ],
        },
    )
    check(gmail_list.next_cursor == "gmail-next" and len(gmail_list.items) == 2, "Gmail search validates pagination and items")
    check(set(gmail_list.items[0].projection) == {"id", "threadId"}, "Gmail search projection cannot smuggle message content")
    check(gmail_list.items[0].revision.startswith("listing:"), "Gmail search item revision binds page snapshot")

    gmail_get_sc = scope("gmail", "18fabc", "message_get")
    gmail_get_plan = build_gmail_message_get(gmail_get_sc, message_id="18fabc")
    gmail_message = {
        "id": "18fabc",
        "threadId": "thr-1",
        "labelIds": ["INBOX"],
        "snippet": "Preview",
        "historyId": "9001",
        "internalDate": "1786586400000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "Subject", "value": "ModelRig"}],
            "body": {"size": 5, "data": "SGVsbG8"},
        },
        "raw": "must-never-project",
    }
    gmail_get = validate(gmail_get_plan, gmail_get_sc, gmail_message)
    check(gmail_get.items[0].revision == "history:9001", "Gmail message revision uses historyId")
    check("payload" in gmail_get.items[0].projection, "Gmail detailed read keeps requested MIME payload")
    check("raw" not in gmail_get.items[0].projection, "Gmail raw RFC822 data is never projected")

    thread_sc = scope("gmail", "thr-1", "thread_get")
    thread_plan = build_gmail_thread_get(thread_sc, thread_id="thr-1")
    thread_result = validate(thread_plan, thread_sc, {"id": "thr-1", "historyId": "9002", "messages": [gmail_message]})
    check(thread_result.items[0].revision == "history:9002", "Gmail thread revision uses thread historyId")
    check(len(thread_result.items[0].projection["messages"]) == 1, "Gmail thread projects bounded detailed messages")

    notion_search_sc = scope("notion", "workspace-search", "search")
    notion_search_plan = build_notion_search(
        notion_search_sc,
        object_scope="workspace-search",
        query_text="ModelRig",
    )
    notion_item = {
        "object": "page",
        "id": "11111111-2222-3333-4444-555555555555",
        "created_time": "2026-08-01T10:00:00.000Z",
        "last_edited_time": "2026-08-12T10:00:00.000Z",
        "url": "https://www.notion.so/example",
        "properties": {"Name": {"type": "title", "title": []}},
        "created_by": {"id": "must-not-project"},
    }
    notion_search = validate(
        notion_search_plan,
        notion_search_sc,
        {"object": "list", "results": [notion_item], "has_more": True, "next_cursor": "cursor-2"},
    )
    check(notion_search.next_cursor == "cursor-2", "Notion search cursor is accepted only with has_more")
    check("created_by" not in notion_search.items[0].projection, "Notion page projection drops unreviewed identity fields")
    check(notion_search.items[0].revision.startswith("edited:"), "Notion revision uses last_edited_time")

    check(
        raises(
            ProviderResponseError,
            lambda: validate(notion_search_plan, notion_search_sc, {"results": [], "has_more": True, "next_cursor": None}),
            "missing next_cursor",
        ),
        "Notion has_more=true without cursor fails closed",
    )
    check(
        raises(
            ProviderResponseError,
            lambda: validate(notion_search_plan, notion_search_sc, {"results": [], "has_more": False, "next_cursor": "surprise"}),
            "cannot carry next_cursor",
        ),
        "Notion has_more=false with cursor fails closed",
    )

    notion_page_sc = scope("notion", notion_item["id"], "page_get")
    notion_page_plan = build_notion_page_get(notion_page_sc, page_id=notion_item["id"])
    notion_page = validate(notion_page_plan, notion_page_sc, notion_item)
    check(notion_page.items[0].projection["properties"] == notion_item["properties"], "Notion page keeps reviewed properties")

    block_id = "block-1"
    block_sc = scope("notion", block_id, "page_get")
    block_plan = build_notion_block_children(block_sc, block_id=block_id)
    block_payload = {
        "results": [
            {
                "object": "block",
                "id": "child-1",
                "type": "paragraph",
                "last_edited_time": "2026-08-12T11:00:00.000Z",
                "paragraph": {"rich_text": [{"type": "text", "plain_text": "Hello"}]},
                "created_by": {"id": "must-not-project"},
            }
        ],
        "has_more": False,
        "next_cursor": None,
    }
    block_result = validate(block_plan, block_sc, block_payload)
    check("paragraph" in block_result.items[0].projection, "Notion block keeps only its declared dynamic type payload")
    check("created_by" not in block_result.items[0].projection, "Notion block drops unrelated sibling fields")

    ds_id = "data-source-1"
    ds_sc = scope("notion", ds_id, "database_query")
    ds_plan = build_notion_data_source_query(ds_sc, data_source_id=ds_id)
    ds_result = validate(ds_plan, ds_sc, {"results": [notion_item], "has_more": False, "next_cursor": None})
    check(ds_result.provider_operation == "data_source_query", "stable database authority maps through current Notion data-source operation")
    check(ds_result.authority_operation == "database_query", "v1 logical authority id remains unchanged")

    check(
        raises(
            ProviderResponseError,
            lambda: validate_provider_response(
                binding(event_plan, event_sc),
                status_code=401,
                content_type="application/json",
                body=b'{"error":"token-secret-should-not-echo"}',
                retrieved_at=1_800_000_010,
            ),
            "HTTP 401",
        ),
        "provider non-200 fails categorically",
    )
    try:
        validate_provider_response(
            binding(event_plan, event_sc),
            status_code=401,
            content_type="application/json",
            body=b'{"error":"token-secret-should-not-echo"}',
            retrieved_at=1_800_000_010,
        )
    except ProviderResponseError as exc:
        check("token-secret-should-not-echo" not in str(exc), "provider error body is never echoed")
    else:
        check(False, "provider error body is never echoed")

    check(
        raises(
            ProviderResponseError,
            lambda: validate_provider_response(
                binding(event_plan, event_sc),
                status_code=200,
                content_type="text/html",
                body=b"<html></html>",
                retrieved_at=1_800_000_010,
            ),
            "content type",
        ),
        "unexpected content type fails before projection",
    )

    check(
        raises(
            ProviderResponseError,
            lambda: validate_provider_response(
                binding(event_plan, event_sc),
                status_code=200,
                content_type="application/json",
                body=b"{" + b'"x":"' + b"a" * (event_plan.max_response_bytes + 1) + b'"}',
                retrieved_at=1_800_000_010,
            ),
            "byte budget",
        ),
        "response larger than immutable request budget fails closed",
    )

    check(
        raises(
            ProviderResponseError,
            lambda: validate_provider_response(
                binding(event_plan, event_sc),
                status_code=200,
                content_type="application/json",
                body=b'{"id":"evt-1","id":"evt-2"}',
                retrieved_at=1_800_000_010,
            ),
            "duplicate object keys",
        ),
        "duplicate JSON keys are rejected",
    )
    check(
        raises(
            ProviderResponseError,
            lambda: validate_provider_response(
                binding(event_plan, event_sc),
                status_code=200,
                content_type="application/json",
                body=b'{"id":"evt-1","score":NaN}',
                retrieved_at=1_800_000_010,
            ),
            "non-finite",
        ),
        "non-finite JSON numbers are rejected",
    )
    check(
        raises(
            ProviderResponseError,
            lambda: validate_provider_response(
                binding(event_plan, event_sc),
                status_code=200,
                content_type="application/json",
                body=b"\xff\xfe",
                retrieved_at=1_800_000_010,
            ),
            "UTF-8",
        ),
        "invalid JSON UTF-8 is rejected",
    )
    check(
        raises(
            ProviderResponseError,
            lambda: validate_provider_response(
                binding(doc_plan, doc_sc),
                status_code=200,
                content_type="text/plain",
                body=b"\xff",
                retrieved_at=1_800_000_010,
            ),
            "UTF-8",
        ),
        "invalid text UTF-8 is rejected",
    )
    check(
        raises(
            ProviderResponseError,
            lambda: validate_provider_response(
                binding(event_plan, event_sc),
                status_code=200,
                content_type="application/json",
                body=b"[]",
                retrieved_at=1_800_000_010,
            ),
            "root must be an object",
        ),
        "JSON array root is rejected",
    )
    check(
        raises(ProviderResponseError, lambda: validate(event_plan, event_sc, {"etag": '"x"'}), "calendar event id"),
        "missing provider object id fails closed",
    )

    audit = gmail_get.to_audit_dict()
    check("items" not in audit and "projection" not in audit, "response audit omits provider content")
    check("account_ref" not in audit and "workspace_ref" not in audit, "response audit omits raw account/workspace identity")
    check(audit["body_sha256"] == gmail_get.body_sha256, "response audit retains content hash evidence")
    check(gmail_get.production_activation is False, "provider response activation remains structurally false")
    check(all(r.production_activation is False for r in gmail_get.source_receipts), "source receipts remain dormant")

    print(f"\nProvider response tests: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
