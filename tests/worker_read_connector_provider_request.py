from __future__ import annotations

import hashlib
import json
import os
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.read_connector_package_contract import ReadConnectorScope  # noqa: E402
from app.read_connector_provider_request import (  # noqa: E402
    NOTION_VERSION,
    ProviderRequestError,
    ProviderRequestPlan,
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


def scope(connector: str, object_scope: str, *operations: str) -> ReadConnectorScope:
    return ReadConnectorScope(
        connector=connector,
        account_ref=f"acct-{connector}",
        workspace_ref="workspace-main" if connector == "notion" else None,
        object_scopes=(object_scope,),
        operations=tuple(operations),
    )


def query(plan: ProviderRequestPlan) -> dict[str, list[str]]:
    return parse_qs(urlsplit(plan.url).query, keep_blank_values=True)


def common(plan: ProviderRequestPlan, *, connector: str, host: str) -> None:
    check(plan.connector == connector, f"{connector}: connector identity is fixed")
    check(plan.host == host, f"{connector}: provider host is fixed")
    check(plan.url.startswith(f"https://{host}/"), f"{connector}: URL is HTTPS-only")
    check(plan.credential_mode == "bearer_injected_at_execute", f"{connector}: credentials are execute-time only")
    check(plan.follow_redirects is False, f"{connector}: redirects stay disabled")
    check(plan.production_activation is False, f"{connector}: production activation stays false")
    check(plan.max_response_bytes <= 8 * 1024 * 1024, f"{connector}: response budget is globally bounded")
    names = {name.casefold() for name, _ in plan.headers}
    check("authorization" not in names and "cookie" not in names, f"{connector}: plan carries no credential headers")
    audit = plan.to_audit_dict()
    check("body_json" not in audit and "url" not in audit, f"{connector}: audit projection omits body/query content")


def main() -> int:
    calendar_list = build_calendar_list(scope("google_calendar", "calendar-list", "calendar_list"))
    common(calendar_list, connector="google_calendar", host="www.googleapis.com")
    check(calendar_list.method == "GET", "calendar list is GET")
    check(calendar_list.path == "/calendar/v3/users/me/calendarList", "calendar list path is pinned")
    check(query(calendar_list)["minAccessRole"] == ["reader"], "calendar list requests read-level access only")

    event = build_calendar_event_get(
        scope("google_calendar", "team-calendar", "event_get"),
        calendar_id="team-calendar",
        event_id="event/with space",
    )
    common(event, connector="google_calendar", host="www.googleapis.com")
    check(event.path.endswith("/events/event%2Fwith%20space"), "calendar event id is encoded as one path segment")

    search = build_calendar_event_search(
        scope("google_calendar", "team-calendar", "event_search"),
        calendar_id="team-calendar",
        time_min="2026-08-12T00:00:00+02:00",
        time_max="2026-08-13T00:00:00+02:00",
        query_text="ModelRig review",
        page_size=50,
    )
    common(search, connector="google_calendar", host="www.googleapis.com")
    q = query(search)
    check(q["singleEvents"] == ["true"] and q["orderBy"] == ["startTime"], "calendar search expands instances in stable time order")
    check(q["maxResults"] == ["50"], "calendar search page size is explicitly bounded")
    check(
        raises(
            ProviderRequestError,
            lambda: build_calendar_event_search(
                scope("google_calendar", "team-calendar", "event_search"),
                calendar_id="team-calendar",
                time_min="2026-08-13T00:00:00Z",
                time_max="2026-08-12T00:00:00Z",
            ),
            "time_min must be before time_max",
        ),
        "calendar search rejects reversed windows",
    )
    check(
        raises(
            ProviderRequestError,
            lambda: build_calendar_event_search(
                scope("google_calendar", "team-calendar", "event_search"),
                calendar_id="team-calendar",
                time_min="2026-01-01T00:00:00Z",
                time_max="2027-01-03T00:00:00Z",
            ),
            "calendar search window",
        ),
        "calendar search rejects unbounded multi-year windows",
    )

    drive_search = build_drive_file_search(
        scope("google_drive", "folder-1", "file_search"),
        parent_id="folder-1",
        name_contains="Anders' plan",
    )
    common(drive_search, connector="google_drive", host="www.googleapis.com")
    dq = query(drive_search)["q"][0]
    check("'folder-1' in parents" in dq and "trashed = false" in dq, "Drive search is pinned to the exact parent and excludes trash")
    check("Anders\\' plan" in dq, "Drive q literals escape apostrophes")

    metadata = build_drive_file_metadata(
        scope("google_drive", "file-7", "file_metadata"),
        file_id="file-7",
    )
    common(metadata, connector="google_drive", host="www.googleapis.com")
    check(metadata.path == "/drive/v3/files/file-7", "Drive metadata path is pinned")

    document = build_drive_document_read(
        scope("google_drive", "doc-7", "document_read"),
        file_id="doc-7",
    )
    common(document, connector="google_drive", host="www.googleapis.com")
    check(document.authority_operation == "document_read", "Drive document export consumes only document_read authority")
    check(document.provider_operation == "files.export:text/plain", "Drive v1 document read is native Docs text export only")
    check(document.path == "/drive/v3/files/doc-7/export", "Drive document export path is pinned")
    check(query(document) == {"mimeType": ["text/plain"]}, "Drive document export cannot select arbitrary MIME")
    check(document.response_kind == "text" and document.max_response_bytes == 2 * 1024 * 1024, "Drive document text response is bounded")

    gmail_search = build_gmail_message_search(
        scope("gmail", "inbox", "message_search"),
        object_scope="inbox",
        query_text="newer_than:7d from:buildbot",
        page_size=50,
    )
    common(gmail_search, connector="gmail", host="gmail.googleapis.com")
    check(gmail_search.path == "/gmail/v1/users/me/messages", "Gmail search always binds authenticated users/me")
    gq = query(gmail_search)
    check(gq["maxResults"] == ["50"] and gq["includeSpamTrash"] == ["false"], "Gmail search is bounded and excludes spam/trash")

    message = build_gmail_message_get(scope("gmail", "msg-1", "message_get"), message_id="msg-1")
    common(message, connector="gmail", host="gmail.googleapis.com")
    check(message.path == "/gmail/v1/users/me/messages/msg-1", "Gmail message get always uses users/me")
    check(query(message)["format"] == ["full"], "Gmail message read never requests raw wire format")

    thread = build_gmail_thread_get(scope("gmail", "thread-1", "thread_get"), thread_id="thread-1")
    common(thread, connector="gmail", host="gmail.googleapis.com")
    check(thread.path == "/gmail/v1/users/me/threads/thread-1", "Gmail thread get always uses users/me")
    check(query(thread)["format"] == ["full"], "Gmail thread read never requests raw wire format")

    notion_search = build_notion_search(
        scope("notion", "workspace-search", "search"),
        object_scope="workspace-search",
        query_text="ModelRig",
        page_size=50,
    )
    common(notion_search, connector="notion", host="api.notion.com")
    nheaders = {name.casefold(): value for name, value in notion_search.headers}
    check(nheaders["notion-version"] == NOTION_VERSION, "Notion requests pin the current API version")
    check(notion_search.method == "POST" and notion_search.path == "/v1/search", "Notion search is fixed read-semantic POST")
    check(notion_search.body_json == json.dumps(json.loads(notion_search.body_json), ensure_ascii=False, sort_keys=True, separators=(",", ":")), "Notion search body is canonical JSON")

    page = build_notion_page_get(scope("notion", "page-1", "page_get"), page_id="page-1")
    common(page, connector="notion", host="api.notion.com")
    check(page.path == "/v1/pages/page-1" and page.method == "GET", "Notion page properties use fixed retrieve path")

    children = build_notion_block_children(scope("notion", "page-1", "page_get"), block_id="page-1")
    common(children, connector="notion", host="api.notion.com")
    check(children.authority_operation == "page_get", "Notion page content stays under exact page_get authority")
    check(children.provider_operation == "blocks.children.list", "Notion page content maps to block children read")

    data_source = build_notion_data_source_query(
        scope("notion", "source-1", "database_query"),
        data_source_id="source-1",
        page_size=50,
    )
    common(data_source, connector="notion", host="api.notion.com")
    check(data_source.authority_operation == "database_query", "stable v1 Notion authority id is retained")
    check(data_source.provider_operation == "data_source_query", "legacy logical authority maps to current provider data-source operation")
    check(data_source.path == "/v1/data_sources/source-1/query", "no deprecated Notion database-query endpoint is representable")
    check(data_source.body_json == '{"page_size":50}', "Notion data-source query body is canonical and minimal")
    check(data_source.body_sha256 == hashlib.sha256(data_source.body_json.encode()).hexdigest(), "request body audit digest is deterministic")

    wrong_scope = scope("google_drive", "other-file", "document_read")
    check(
        raises(
            ProviderRequestError,
            lambda: build_drive_document_read(wrong_scope, file_id="doc-7"),
            "outside exact connector scope",
        ),
        "provider plans fail closed outside exact object scope",
    )
    check(
        raises(
            ProviderRequestError,
            lambda: build_gmail_message_get(scope("gmail", "msg-1", "message_search"), message_id="msg-1"),
            "outside exact connector scope",
        ),
        "provider plans fail closed outside exact operation scope",
    )

    check(
        raises(
            ProviderRequestError,
            lambda: ProviderRequestPlan(
                connector="gmail",
                authority_operation="message_get",
                provider_operation="users.messages.get",
                object_scope="msg-1",
                method="GET",
                host="evil.example",
                path="/gmail/v1/users/me/messages/msg-1",
                query=(),
                headers=(("Accept", "application/json"),),
                body_json=None,
                response_kind="json",
                expected_content_types=("application/json",),
                max_response_bytes=1024,
            ),
            "host is not allowlisted",
        ),
        "arbitrary provider hosts are structurally impossible",
    )
    check(
        raises(
            ProviderRequestError,
            lambda: ProviderRequestPlan(
                connector="gmail",
                authority_operation="message_get",
                provider_operation="users.messages.get",
                object_scope="msg-1",
                method="GET",
                host="gmail.googleapis.com",
                path="/gmail/v1/users/me/messages/msg-1",
                query=(),
                headers=(("Authorization", "secret-value"),),
                body_json=None,
                response_kind="json",
                expected_content_types=("application/json",),
                max_response_bytes=1024,
            ),
            "credential headers",
        ),
        "credential headers cannot be embedded in a plan",
    )

    print(f"\n===== T-037 PROVIDER REQUESTS: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
