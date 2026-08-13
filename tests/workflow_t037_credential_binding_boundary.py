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
    path = os.path.join(root, "worker", "app", "read_connector_credential_binding.py")
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
        {
            "socket",
            "ssl",
            "http",
            "urllib",
            "requests",
            "httpx",
            "aiohttp",
            "subprocess",
            "pathlib",
        }.isdisjoint(imported),
        "credential binding imports no network/process/file credential implementation",
    )
    check("os" not in imported, "credential binding cannot read environment configuration")
    check("pinned_http_transport" not in imported_full, "credential slice cannot accidentally become live transport")

    for needle in (
        "os.getenv(",
        "os.environ",
        "Path(",
        "open(",
        "read_bytes(",
        "socket.",
        "requests.",
        "httpx.",
        "aiohttp.",
        "urlopen(",
        "subprocess.",
        "FastAPI(",
        "APIRouter(",
        "REGISTRY[",
        "chat_tools(",
        "Authorization: Bearer",
    ):
        check(needle not in source, f"credential binding remains dormant: no {needle}")

    call_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                call_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                call_names.add(node.func.attr)
    check(
        {"socket", "urlopen", "request", "get", "post", "register", "include_router"}.isdisjoint(call_names),
        "credential module has no live network/registration call site",
    )

    check(
        'PRODUCTION_ACTIVATION = False' in source,
        "credential binding pins production activation false",
    )
    check(
        'credential_mode != "bearer_injected_at_execute"' in source,
        "credential boundary requires execute-time bearer mode from provider plan",
    )
    check(
        "follow_redirects is not False" in source,
        "credential boundary rechecks redirect denial",
    )
    check(
        "self._grants.authorize(" in source,
        "credential binding consumes landed durable grant authority",
    )
    check(
        source.count("self._grants.authorize(") >= 2,
        "grant authority is checked both at prepare and execution boundaries",
    )
    check(
        "self._credentials.bearer_token()" in source,
        "bearer material has one explicit host-owned execution seam",
    )
    execution_start = source.index("def trusted_bearer_for_execution")
    check(
        source.index("self._grants.authorize(", execution_start)
        < source.index("self._credentials.bearer_token()", execution_start),
        "execution re-authorizes grant before reading bearer material",
    )
    check(
        '"www.googleapis.com"' in source
        and '"gmail.googleapis.com"' in source
        and '"api.notion.com"' in source,
        "credential boundary pins connector-specific provider hosts",
    )
    check(
        '"google_oauth_bearer"' in source and '"notion_integration_bearer"' in source,
        "credential kinds are provider-specific and closed",
    )
    check(
        "to_audit_dict" in source
        and '"credential_kind"' in source
        and '"scope_sha256"' in source,
        "non-secret audit binds credential kind and exact scope authority",
    )
    audit_start = source.index("def to_audit_dict")
    audit_end = source.index("class ReadConnectorCredentialBinder")
    check(
        '"token"' not in source[audit_start:audit_end],
        "audit projection contains no token field",
    )
    check(
        "A later transport/secure-storage slice" in source,
        "module does not overclaim secure storage or live transport",
    )

    print(f"\n===== T-037 CREDENTIAL BOUNDARY: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
