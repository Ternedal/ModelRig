from __future__ import annotations

import ast
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESPONSE_TARGET = ROOT / "worker" / "app" / "read_connector_provider_response.py"
EXECUTION_TARGET = ROOT / "worker" / "app" / "read_connector_provider_execution.py"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.read_connector_credential_binding import (  # noqa: E402
    ReadConnectorCredentialBinder,
    ReadConnectorCredentialEvidence,
)
from app.read_connector_package_contract import (  # noqa: E402
    ReadConnectorDenied,
    ReadConnectorGrantStore,
    ReadConnectorScope,
)
from app.read_connector_provider_execution import (  # noqa: E402
    ProviderExecutionError,
    ProviderTransportResponse,
    ReadConnectorProviderExecutor,
    exact_request_sha256,
)
from app.read_connector_provider_request import (  # noqa: E402
    build_drive_document_read,
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


def imported_roots_and_calls(tree: ast.AST) -> tuple[set[str], set[str]]:
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
    return imported_roots, calls


class UUIDs:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


class FakeCredentials:
    def __init__(
        self,
        *,
        connector: str,
        account_ref: str,
        workspace_ref: str | None = None,
        token: str = "trusted-secret-token-1234567890abcdef",
        expires_at: int | None = 10_000,
    ) -> None:
        self.connector = connector
        self.account_ref = account_ref
        self.workspace_ref = workspace_ref
        self.token = token
        self.expires_at = expires_at
        self.token_reads = 0

    def evidence(self, *, now: int) -> ReadConnectorCredentialEvidence:
        return ReadConnectorCredentialEvidence(
            connector=self.connector,
            account_ref=self.account_ref,
            workspace_ref=self.workspace_ref,
            credential_kind=(
                "notion_integration_bearer"
                if self.connector == "notion"
                else "google_oauth_bearer"
            ),
            state="ready",
            checked_at=now,
            expires_at=self.expires_at,
        )

    def bearer_token(self) -> str:
        self.token_reads += 1
        return self.token


class FakeTransport:
    def __init__(
        self,
        *,
        status_code: int = 200,
        content_type: str = "application/json",
        body: bytes = b"{}",
    ) -> None:
        self.status_code = status_code
        self.content_type = content_type
        self.body = body
        self.calls = 0
        self.last_method: str | None = None
        self.last_host: str | None = None
        self.last_request_sha256: str | None = None
        self.bearer_length: int | None = None
        self.override_digest: str | None = None
        self.override_method: str | None = None
        self.override_host: str | None = None
        self.failure: Exception | None = None

    def execute(
        self,
        plan,
        *,
        bearer_token: str,
        request_sha256: str,
        timeout_seconds: float,
    ) -> ProviderTransportResponse:
        self.calls += 1
        self.last_method = plan.method
        self.last_host = plan.host
        self.last_request_sha256 = request_sha256
        self.bearer_length = len(bearer_token)
        if self.failure is not None:
            raise self.failure
        return ProviderTransportResponse(
            request_sha256=self.override_digest or request_sha256,
            method=self.override_method or plan.method,
            host=self.override_host or plan.host,
            status_code=self.status_code,
            content_type=self.content_type,
            body=self.body,
        )


def scope(
    connector: str,
    *,
    account_ref: str,
    object_scope: str,
    operation: str,
    workspace_ref: str | None = None,
) -> ReadConnectorScope:
    return ReadConnectorScope(
        connector=connector,
        account_ref=account_ref,
        workspace_ref=workspace_ref,
        object_scopes=(object_scope,),
        operations=(operation,),
    )


def response_boundary_checks() -> None:
    source = RESPONSE_TARGET.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots, calls = imported_roots_and_calls(tree)

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
        "PRODUCTION_ACTIVATION = False" in source,
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
            if isinstance(node, ast.FunctionDef)
            and node.name == "validate_provider_response"
        ),
        None,
    )
    check(validate_fn is not None, "single reviewed response-validation entrypoint exists")
    if validate_fn is not None:
        names = {
            node.id for node in ast.walk(validate_fn) if isinstance(node, ast.Name)
        }
        check(
            "body" in names and "binding" in names,
            "response entrypoint requires explicit bytes plus authority binding",
        )
        check(
            "token" not in names and "bearer" not in names,
            "response entrypoint never accepts credential material",
        )

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
            '"projection"' not in audit_fn
            and '"body"' not in audit_fn
            and '"items"' not in audit_fn,
            "response audit cannot contain body/projection content",
        )
        check(
            '"account_ref"' not in audit_fn
            and '"workspace_ref"' not in audit_fn,
            "response audit does not repeat raw account/workspace identity",
        )


def execution_static_checks() -> None:
    source = EXECUTION_TARGET.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots, calls = imported_roots_and_calls(tree)

    forbidden_import_roots = {
        "aiohttp",
        "http",
        "httpx",
        "os",
        "pathlib",
        "requests",
        "socket",
        "ssl",
        "subprocess",
        "urllib",
        "urllib3",
    }
    check(
        not (imported_roots & forbidden_import_roots),
        "execution composition imports no concrete network/file/env/process implementation",
    )
    check(
        not (
            {"open", "urlopen", "getenv", "system", "popen", "create_connection"}
            & calls
        ),
        "execution composition performs no file/env/process/socket lookup",
    )

    forbidden_needles = (
        "FastAPI",
        "APIRouter",
        "ToolGate",
        "include_router",
        "REGISTRY",
        "pinned_http_transport",
        "PinnedHttpTransport",
        "requests.",
        "httpx.",
        "urllib.request",
        "socket.",
        "Authorization:",
        "Bearer ",
    )
    check(
        all(needle not in source for needle in forbidden_needles),
        "execution composition has no route or concrete transport activation seam",
    )
    check(
        "PRODUCTION_ACTIVATION = False" in source,
        "execution module pins production activation false",
    )
    check(
        "ReadConnectorProviderTransport(Protocol)" in source,
        "provider transport remains an injected protocol",
    )
    check(
        '"query": [[key, value] for key, value in plan.query]' in source
        and '"body_json": plan.body_json' in source,
        "exact request digest binds private query and body values",
    )

    executor_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "ReadConnectorProviderExecutor"
        ),
        None,
    )
    check(executor_class is not None, "single dormant provider executor exists")
    execute_fn = None
    if executor_class is not None:
        execute_fn = next(
            (
                node
                for node in executor_class.body
                if isinstance(node, ast.FunctionDef) and node.name == "execute"
            ),
            None,
        )
    check(execute_fn is not None, "executor has one explicit execute entrypoint")
    if execute_fn is not None:
        trusted_calls: list[ast.Call] = []
        transport_calls: list[ast.Call] = []
        loops = [
            node
            for node in ast.walk(execute_fn)
            if isinstance(node, (ast.For, ast.While, ast.AsyncFor))
        ]
        for node in ast.walk(execute_fn):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if node.func.attr == "trusted_bearer_for_execution":
                trusted_calls.append(node)
            if node.func.attr == "execute":
                value = node.func.value
                if (
                    isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "self"
                    and value.attr == "_transport"
                ):
                    transport_calls.append(node)
        check(
            len(trusted_calls) == 1,
            "execution reauthorizes and loads bearer exactly once",
        )
        check(
            len(transport_calls) == 1,
            "execution invokes host transport exactly once",
        )
        if len(trusted_calls) == 1 and len(transport_calls) == 1:
            check(
                trusted_calls[0].lineno < transport_calls[0].lineno,
                "reauthorization occurs before transport",
            )
        check(not loops, "executor structurally contains no retry loop")

    transport_response_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "ProviderTransportResponse"
        ),
        None,
    )
    check(
        transport_response_class is not None,
        "typed transient provider transport response exists",
    )
    if transport_response_class is not None:
        methods = {
            node.name
            for node in transport_response_class.body
            if isinstance(node, ast.FunctionDef)
        }
        check(
            "to_dict" not in methods and "to_audit_dict" not in methods,
            "raw transport body has no serializer/audit surface",
        )

    execution_audit = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "to_audit_dict":
            text = ast.get_source_segment(source, node) or ""
            if "request_sha256" in text and "attempts" in text:
                execution_audit = text
                break
    check(execution_audit is not None, "execution audit projection exists")
    if execution_audit is not None:
        check(
            '"bearer"' not in execution_audit
            and '"bearer_token"' not in execution_audit
            and '"query"' not in execution_audit
            and '"body"' not in execution_audit
            and '"url"' not in execution_audit,
            "execution audit cannot contain bearer/query/body/url content",
        )
        check(
            '"account_ref"' not in execution_audit
            and '"workspace_ref"' not in execution_audit,
            "execution audit omits raw account/workspace identity",
        )


def execution_behavior_checks() -> None:
    grants = ReadConnectorGrantStore(uuid_factory=UUIDs())
    drive_scope = scope(
        "google_drive",
        account_ref="google-account-1",
        object_scope="doc-7",
        operation="document_read",
    )
    drive_grant = grants.create_grant(drive_scope, actor="Anders", now=1)
    drive_plan = build_drive_document_read(drive_scope, file_id="doc-7")
    credentials = FakeCredentials(
        connector="google_drive",
        account_ref="google-account-1",
        token="drive-secret-token-1234567890abcdef",
    )
    binder = ReadConnectorCredentialBinder(grants=grants, credentials=credentials)
    binding = binder.prepare(drive_grant.grant_id, drive_plan, now=100)

    transport = FakeTransport(
        content_type="text/plain; charset=UTF-8",
        body="Hej ModelRig\nexecution".encode("utf-8"),
    )
    executor = ReadConnectorProviderExecutor(binder=binder, transport=transport)
    result = executor.execute(binding, now=101, timeout_seconds=12.5)

    check(transport.calls == 1, "execution makes exactly one transport call")
    check(credentials.token_reads == 1, "execution loads bearer exactly once")
    check(
        transport.bearer_length == len(credentials.token),
        "trusted bearer reaches transport without being returned",
    )
    check(
        transport.last_request_sha256 == exact_request_sha256(drive_plan),
        "transport is bound to exact full request digest",
    )
    check(
        transport.last_method == "GET"
        and transport.last_host == "www.googleapis.com",
        "GET method and fixed Google host reach transport unchanged",
    )
    check(
        result.response.items[0].projection == {"text": "Hej ModelRig\nexecution"},
        "transport bytes flow through reviewed provider projection",
    )
    check(result.attempts == 1, "execution result structurally records one attempt")
    check(result.production_activation is False, "execution remains dormant")

    audit = result.to_audit_dict()
    serialized = json.dumps(audit, sort_keys=True)
    check(
        audit["request_sha256"] == exact_request_sha256(drive_plan),
        "execution audit binds exact request digest",
    )
    check(
        audit["grant_id"] == drive_grant.grant_id
        and audit["scope_sha256"] == drive_scope.digest,
        "execution audit binds exact grant and scope",
    )
    check(
        "account_ref" not in audit
        and "workspace_ref" not in audit
        and "query" not in audit
        and "body" not in audit
        and "url" not in audit,
        "execution audit omits raw identity and request/response content",
    )
    check(
        "drive-secret-token" not in serialized
        and not hasattr(result, "bearer_token")
        and not hasattr(result.response, "bearer_token"),
        "bearer material is absent from returned/audited result",
    )

    notion_scope = scope(
        "notion",
        account_ref="notion-account-1",
        workspace_ref="workspace-main",
        object_scope="workspace-search",
        operation="search",
    )
    notion_alpha = build_notion_search(
        notion_scope,
        object_scope="workspace-search",
        query_text="alpha",
    )
    notion_beta = build_notion_search(
        notion_scope,
        object_scope="workspace-search",
        query_text="beta",
    )
    check(
        exact_request_sha256(notion_alpha) != exact_request_sha256(notion_beta),
        "request digest changes when private Notion body changes",
    )

    notion_grant = grants.create_grant(notion_scope, actor="Anders", now=200)
    notion_credentials = FakeCredentials(
        connector="notion",
        account_ref="notion-account-1",
        workspace_ref="workspace-main",
        expires_at=None,
        token="notion-secret-token-1234567890abcdef",
    )
    notion_binder = ReadConnectorCredentialBinder(
        grants=grants,
        credentials=notion_credentials,
    )
    notion_binding = notion_binder.prepare(
        notion_grant.grant_id,
        notion_alpha,
        now=210,
    )
    notion_transport = FakeTransport(
        body=b'{"object":"list","results":[],"has_more":false,"next_cursor":null}'
    )
    notion_executor = ReadConnectorProviderExecutor(
        binder=notion_binder,
        transport=notion_transport,
    )
    notion_result = notion_executor.execute(notion_binding, now=211)
    check(
        notion_transport.last_method == "POST"
        and notion_transport.last_host == "api.notion.com",
        "neutral transport protocol preserves Notion read POST",
    )
    check(
        notion_result.response.items == ()
        and notion_result.response.next_cursor is None,
        "valid empty Notion response composes end-to-end",
    )

    revoke_scope = scope(
        "google_drive",
        account_ref="google-account-2",
        object_scope="doc-revoke",
        operation="document_read",
    )
    revoke_grant = grants.create_grant(revoke_scope, actor="Anders", now=300)
    revoke_plan = build_drive_document_read(revoke_scope, file_id="doc-revoke")
    revoke_credentials = FakeCredentials(
        connector="google_drive",
        account_ref="google-account-2",
        token="revoke-secret-token-1234567890abcdef",
    )
    revoke_binder = ReadConnectorCredentialBinder(
        grants=grants,
        credentials=revoke_credentials,
    )
    revoke_binding = revoke_binder.prepare(
        revoke_grant.grant_id,
        revoke_plan,
        now=310,
    )
    grants.revoke(
        revoke_grant.grant_id,
        expected_scope_sha256=revoke_scope.digest,
        actor="Anders",
        now=311,
    )
    revoke_transport = FakeTransport(content_type="text/plain", body=b"never")
    revoke_executor = ReadConnectorProviderExecutor(
        binder=revoke_binder,
        transport=revoke_transport,
    )
    check(
        raises(
            ReadConnectorDenied,
            lambda: revoke_executor.execute(revoke_binding, now=312),
            "missing or revoked",
        ),
        "revocation after prepare fails before transport",
    )
    check(
        revoke_credentials.token_reads == 0 and revoke_transport.calls == 0,
        "revoked execution reads no bearer and performs no I/O",
    )

    failing_transport = FakeTransport(content_type="text/plain", body=b"")
    failing_transport.failure = RuntimeError(
        "socket failure drive-secret-token-1234567890abcdef"
    )
    failing_executor = ReadConnectorProviderExecutor(
        binder=binder,
        transport=failing_transport,
    )
    try:
        failing_executor.execute(binding, now=102)
    except ProviderExecutionError as exc:
        check(
            str(exc) == "provider transport execution failed",
            "transport exception collapses to one generic category",
        )
        check(
            "drive-secret-token" not in str(exc),
            "transport exception cannot echo bearer material",
        )
    else:
        check(False, "transport exception fails closed")
    check(failing_transport.calls == 1, "transport failure is never retried")

    drift_cases = (
        ("digest", "0" * 64, None, None, "request digest mismatch"),
        ("method", None, "POST", None, "method drifted"),
        ("host", None, None, "api.notion.com", "host drifted"),
    )
    for name, digest, method, host, message in drift_cases:
        drift = FakeTransport(content_type="text/plain", body=b"safe")
        drift.override_digest = digest
        drift.override_method = method
        drift.override_host = host
        drift_executor = ReadConnectorProviderExecutor(binder=binder, transport=drift)
        check(
            raises(
                ProviderExecutionError,
                lambda e=drift_executor: e.execute(binding, now=103),
                message,
            ),
            f"transport cannot substitute {name} evidence",
        )

    baseline_reads = credentials.token_reads
    baseline_calls = transport.calls
    check(
        raises(
            ProviderExecutionError,
            lambda: executor.execute(binding, now=99),
            "prepared in the future",
        ),
        "future-prepared binding is rejected before bearer/I/O",
    )
    check(
        raises(
            ProviderExecutionError,
            lambda: executor.execute(binding, now=104, timeout_seconds=0),
            "within 0..120",
        ),
        "invalid timeout is rejected before bearer/I/O",
    )
    check(
        credentials.token_reads == baseline_reads and transport.calls == baseline_calls,
        "local execution validation causes zero credential/transport side effects",
    )

    grants.close()


def main() -> int:
    response_boundary_checks()
    execution_static_checks()
    execution_behavior_checks()

    print(f"\nT-037 response/execution boundary: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
