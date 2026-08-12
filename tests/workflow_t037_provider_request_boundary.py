from __future__ import annotations

import ast
import os

passed = failed = 0


def check(cond: bool, label: str) -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def main() -> int:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root, "worker", "app", "read_connector_provider_request.py")
    source = open(path, encoding="utf-8").read()
    tree = ast.parse(source)

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
        "os.getenv(",
        "os.environ",
        "Bearer ",
        "requests.",
        "httpx.",
        "aiohttp.",
        "urlopen(",
        "socket.",
        "subprocess.",
        "FastAPI(",
        "APIRouter(",
        "REGISTRY[",
        "ToolGate",
        "chat_tools(",
    ):
        check(needle not in source, f"provider request authority remains dormant: no {needle}")

    check(
        '"authorization"' in source.casefold()
        and "_CREDENTIAL_HEADERS" in source
        and "cannot contain credential headers" in source,
        "credential header names exist only as an explicit deny boundary",
    )
    check('PRODUCTION_ACTIVATION = False' in source, "provider request module pins production activation false")
    check('credential_mode: str = "bearer_injected_at_execute"' in source, "credential material is structurally deferred to executor")
    check('follow_redirects: bool = False' in source, "provider request plans structurally disable redirects")

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

    check('if self.method == "POST":' in source, "POST plans have a dedicated validation branch")
    check('if self.connector != "notion":' in source, "POST is structurally Notion-only in v1")
    check('/v1/search' in source and '/query' in source, "Notion read-semantic POST endpoints are closed and explicit")
    check('api.notion.com' in source and 'gmail.googleapis.com' in source and 'www.googleapis.com' in source, "provider hosts are source-fixed constants")
    check('evil.example' not in source, "no arbitrary provider host fixture leaks into production authority")

    check('operation="database_query"' in source, "stable T-037 v1 logical Notion database_query authority remains represented")
    check('provider_operation="data_source_query"' in source, "stable Notion authority maps explicitly to current data-source API")
    check('/v1/data_sources/' in source, "current Notion data-source query path is pinned")

    check('operation="document_read"' in source, "Drive document read performs its own exact authority check")
    doc_start = source.index("def build_drive_document_read(")
    doc_end = source.index("\ndef build_gmail_message_search(", doc_start)
    doc_source = source[doc_start:doc_end]
    check("build_drive_file_metadata(" not in doc_source, "Drive document read does not silently require metadata authority")
    check('mimeType", "text/plain"' in doc_source, "Drive v1 document read cannot choose arbitrary export MIME")

    check('/gmail/v1/users/me/messages' in source and '/gmail/v1/users/me/threads' in source, "Gmail identity is fixed to authenticated users/me")
    check('("format", "full")' in source and '"raw"' not in source, "Gmail request plans never request raw message format")

    print(f"\n===== T-037 PROVIDER REQUEST BOUNDARY: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
