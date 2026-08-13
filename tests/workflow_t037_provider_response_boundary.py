from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "worker" / "app" / "read_connector_provider_response.py"

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
    source = TARGET.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_import_roots = {
        "aiohttp",
        "http",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
        "urllib3",
    }
    imported_roots: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)

    check(
        not (imported_roots & forbidden_import_roots),
        "provider response boundary imports no HTTP/socket/process client",
    )
    check(
        not ({"open", "urlopen", "getenv", "system", "popen"} & calls),
        "provider response boundary performs no file/env/process/network lookup",
    )

    forbidden_needles = (
        "FastAPI",
        "APIRouter",
        "ToolGate",
        "trusted_bearer_for_execution",
        "bearer_token(",
        "Authorization",
        "include_router",
        "REGISTRY",
        "requests.",
        "httpx.",
        "urllib.request",
        "pinned_http_transport",
    )
    check(
        all(needle not in source for needle in forbidden_needles),
        "provider response boundary has no credential/runtime/transport activation seam",
    )
    check(
        'PRODUCTION_ACTIVATION = False' in source,
        "provider response module pins production activation false",
    )
    check(
        "CredentialBoundProviderRequest" in source
        and "ReadConnectorSourceReceipt" in source
        and "ProviderRequestPlan" in source,
        "response projection binds exact credential authority, request plan and source receipt",
    )

    validate_fn = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "validate_provider_response"
        ),
        None,
    )
    check(validate_fn is not None, "single reviewed response-validation entrypoint exists")
    if validate_fn is not None:
        names = {node.id for node in ast.walk(validate_fn) if isinstance(node, ast.Name)}
        check("body" in names and "binding" in names, "entrypoint requires explicit bytes plus authority binding")
        check("token" not in names and "bearer" not in names, "response entrypoint never accepts credential material")

    audit_fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "to_audit_dict":
            text = ast.get_source_segment(source, node) or ""
            if "body_sha256" in text and "item_count" in text:
                audit_fn = text
                break
    check(audit_fn is not None, "response audit projection exists")
    if audit_fn is not None:
        check(
            '"projection"' not in audit_fn and '"body"' not in audit_fn and '"items"' not in audit_fn,
            "response audit cannot contain body/projection content",
        )
        check(
            '"account_ref"' not in audit_fn and '"workspace_ref"' not in audit_fn,
            "response audit does not repeat raw account/workspace identity",
        )

    print(f"\nProvider response boundary: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
