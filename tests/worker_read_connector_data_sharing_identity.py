from __future__ import annotations

from app.read_connector_package_contract import (
    ReadConnectorScope,
    build_cross_connector_sharing_request,
)


def check(ok: bool, label: str) -> None:
    if not ok:
        raise AssertionError(label)
    print(f"  PASS: {label}")


def main() -> int:
    scope = ReadConnectorScope(
        connector="notion",
        account_ref="NotionUser+ABC",
        workspace_ref="Workspace=42",
        object_scopes=("PageRoot+One",),
        operations=("search", "page_get"),
    )
    destination = scope.data_sharing_destination
    check(destination == f"notion/{scope.digest}", "destination binds exact canonical scope digest")
    check(scope.account_ref not in destination, "destination does not expose raw account identity")
    check(scope.workspace_ref not in destination, "destination does not expose raw workspace identity")
    check(len(destination) == len("notion/") + 64, "destination has bounded deterministic shape")

    same = ReadConnectorScope(
        connector="notion",
        account_ref="NotionUser+ABC",
        workspace_ref="Workspace=42",
        object_scopes=("PageRoot+One",),
        operations=("page_get", "search"),
    )
    check(same.digest == scope.digest, "scope digest ignores caller operation ordering")
    check(same.data_sharing_destination == destination, "destination is stable for canonical-equivalent scope")

    widened = ReadConnectorScope(
        connector="notion",
        account_ref="NotionUser+ABC",
        workspace_ref="Workspace=42",
        object_scopes=("PageRoot+One", "PageRoot+Two"),
        operations=("search", "page_get"),
    )
    check(widened.digest != scope.digest, "scope widening changes digest")
    check(widened.data_sharing_destination != destination, "scope widening changes T-032 destination identity")

    request = build_cross_connector_sharing_request(
        source_connector="gmail",
        destination_scope=scope,
        data_category="private",
        purpose_code="notion_summary",
        purpose="Use selected Gmail context for a user-requested Notion lookup.",
        summary="Selected Gmail context for Notion lookup",
        content_sha256="a" * 64,
        max_bytes=4096,
    )
    check(request.destination == destination, "T-032 request consumes privacy-minimized scope destination")
    check(request.provider == "notion", "T-032 request preserves provider identity separately")
    check("NotionUser" not in request.destination, "request destination contains no raw account alias")
    check("Workspace" not in request.destination, "request destination contains no raw workspace alias")

    print("\n===== T-037 DATA-SHARING IDENTITY: 12 passed, 0 failed =====")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
