from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import read_connector_tool as runtime_mod
from app import tools as tools_mod
from app.read_connector_package_contract import (
    ReadConnectorAuditLog,
    ReadConnectorGrantStore,
    ReadConnectorScope,
    ReadConnectorSourceReceipt,
    allowed_operations,
    capability_id,
    connectors,
)
from app.read_connector_provider_transport import (
    ProviderReadResult,
    ReadConnectorRemoteError,
)

passed = failed = 0
ROOT = Path(__file__).resolve().parents[1]
TOOL_NAMES = {
    "google_calendar": "google_calendar_read",
    "google_drive": "google_drive_read",
    "gmail": "gmail_read",
    "notion": "notion_read",
}
DESTINATIONS = {
    "google_calendar": ("www.googleapis.com",),
    "google_drive": ("www.googleapis.com",),
    "gmail": ("www.googleapis.com",),
    "notion": ("api.notion.com",),
}


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def rejects(fn, expected, name: str, contains: str = "") -> None:
    try:
        fn()
    except expected as exc:
        check(not contains or contains in str(exc), name)
    else:
        check(False, name)


class FakeCredential:
    def __init__(self, connector: str, *, state: str = "ready") -> None:
        self.connector = connector
        self.account_ref = "acct_123"
        self.workspace_ref = "workspace_123" if connector == "notion" else None
        self._state = state

    def credential_state(self, *, now: int) -> str:
        del now
        return self._state


# The normal worker must not gain these network capabilities unless the literal
# default-off switch is explicitly enabled. Keep the literal in main.py so both
# generated readiness pages discover it from source.
main_source = (ROOT / "worker" / "app" / "main.py").read_text(encoding="utf-8")
check(
    'getenv("KALIV_READ_CONNECTOR_PILOT", "0")' in main_source,
    "worker entrypoint declares T-037 pilot default-off",
)
check(
    "register_read_connector_pilot" in main_source,
    "worker entrypoint owns explicit T-037 registration",
)

# Descriptor registration: absent when off; exactly four fixed read tools when
# on. Preserve the process-global registry so this standalone suite is hermetic.
saved_env = os.environ.get("KALIV_READ_CONNECTOR_PILOT")
saved_tools = {name: tools_mod.REGISTRY.get(name) for name in TOOL_NAMES.values()}
for name in TOOL_NAMES.values():
    tools_mod.REGISTRY.pop(name, None)
try:
    os.environ.pop("KALIV_READ_CONNECTOR_PILOT", None)
    off_app = FastAPI()
    check(
        runtime_mod.register_read_connector_pilot(off_app) is False,
        "T-037 registration is absent by default",
    )
    check(
        all(name not in tools_mod.REGISTRY for name in TOOL_NAMES.values()),
        "default-off registration exposes zero connector tools",
    )

    os.environ["KALIV_READ_CONNECTOR_PILOT"] = "1"
    app = FastAPI()
    initial_routes = len(app.routes)
    check(
        runtime_mod.register_read_connector_pilot(app) is True,
        "explicit pilot switch registers connector package",
    )
    check(
        set(TOOL_NAMES.values()).issubset(tools_mod.REGISTRY),
        "all four connector tools register together",
    )
    for connector, name in TOOL_NAMES.items():
        tool = tools_mod.REGISTRY[name]
        check(tool.risk == "read" and tool.impact == "read", f"{connector} is read-only")
        check(tool.network == "public", f"{connector} declares public network boundary")
        check(
            tool.network_destinations == DESTINATIONS[connector],
            f"{connector} destination is fixed",
        )
        check(tool.schedulable is False, f"{connector} is not unattended-schedulable")
        enum = tuple(tool.params["properties"]["operation"]["enum"])
        check(enum == allowed_operations(connector), f"{connector} operation enum matches authority")
        check(
            all(token not in " ".join(enum).lower() for token in ("create", "update", "delete", "write", "send")),
            f"{connector} exposes no provider mutation operation",
        )

    once_routes = len(app.routes)
    check(
        runtime_mod.register_read_connector_pilot(app) is False,
        "repeat registration is idempotent",
    )
    check(len(app.routes) == once_routes, "repeat registration does not duplicate operator routes")
    check(once_routes > initial_routes, "first registration mounts operator routes")

    missing_name = TOOL_NAMES["notion"]
    missing_tool = tools_mod.REGISTRY.pop(missing_name)
    partial_snapshot = set(tools_mod.REGISTRY)
    rejects(
        lambda: runtime_mod.register_read_connector_pilot(FastAPI()),
        RuntimeError,
        "partial registry fails closed",
        "partially populated",
    )
    check(missing_name not in tools_mod.REGISTRY, "partial registry failure adds no missing tool")
    check(set(tools_mod.REGISTRY) == partial_snapshot, "partial registry failure mutates nothing")
    tools_mod.REGISTRY[missing_name] = missing_tool
finally:
    for name in TOOL_NAMES.values():
        tools_mod.REGISTRY.pop(name, None)
    for name, value in saved_tools.items():
        if value is not None:
            tools_mod.REGISTRY[name] = value
    if saved_env is None:
        os.environ.pop("KALIV_READ_CONNECTOR_PILOT", None)
    else:
        os.environ["KALIV_READ_CONNECTOR_PILOT"] = saved_env


# Invalid operations must fail before even credential metadata is touched.
invalid_store = ReadConnectorGrantStore()
invalid_audit = ReadConnectorAuditLog()
credential_reads = 0


def credential_bomb(connector: str):
    global credential_reads
    del connector
    credential_reads += 1
    raise AssertionError("credential seam must not be reached")


invalid_runtime = runtime_mod.ReadConnectorRuntime(
    grants=invalid_store,
    audit=invalid_audit,
    credential_factory=credential_bomb,
)
rejects(
    lambda: invalid_runtime.run(
        "google_calendar",
        {"object_scope": "primary", "operation": "event_delete"},
    ),
    tools_mod.ToolDenied,
    "unknown operation is denied",
    "ikke tilladt",
)
check(credential_reads == 0, "unknown operation is denied before credential read")
invalid_store.close()
invalid_audit.close()


# No grant, revoked grant and ambiguous grants all stop before transport.
def transport_bomb(*args, **kwargs):
    del args, kwargs
    raise AssertionError("transport must not be constructed")


original_transport = runtime_mod.ProviderPinnedTransport
original_client = runtime_mod.AccountBoundReadConnectorClient
runtime_mod.ProviderPinnedTransport = transport_bomb
try:
    no_store = ReadConnectorGrantStore()
    no_audit = ReadConnectorAuditLog()
    no_runtime = runtime_mod.ReadConnectorRuntime(
        grants=no_store,
        audit=no_audit,
        credential_factory=lambda connector: FakeCredential(connector),
    )
    rejects(
        lambda: no_runtime.run(
            "google_calendar",
            {"object_scope": "primary", "operation": "event_search"},
        ),
        tools_mod.ToolDenied,
        "missing exact grant fails before transport",
    )
    no_entries = no_audit.recent(connector="google_calendar")
    check(no_entries[0]["detail"] == "no_active_exact_grant", "missing grant is categorically audited")
    no_store.close()
    no_audit.close()

    revoked_store = ReadConnectorGrantStore()
    revoked_scope = ReadConnectorScope(
        connector="google_calendar",
        account_ref="acct_123",
        object_scopes=("primary",),
        operations=("event_search",),
    )
    revoked = revoked_store.create_grant(revoked_scope, actor="test", now=10)
    revoked_store.revoke(
        revoked.grant_id,
        expected_scope_sha256=revoked.scope.digest,
        actor="test",
        now=11,
    )
    revoked_audit = ReadConnectorAuditLog()
    revoked_runtime = runtime_mod.ReadConnectorRuntime(
        grants=revoked_store,
        audit=revoked_audit,
        credential_factory=lambda connector: FakeCredential(connector),
    )
    rejects(
        lambda: revoked_runtime.run(
            "google_calendar",
            {"object_scope": "primary", "operation": "event_search"},
        ),
        tools_mod.ToolDenied,
        "revoked exact grant fails before transport",
    )
    check(
        revoked_audit.recent(connector="google_calendar")[0]["detail"] == "no_active_exact_grant",
        "revoked grant is no longer active authority",
    )
    revoked_store.close()
    revoked_audit.close()

    ambiguous_store = ReadConnectorGrantStore()
    ambiguous_scope = ReadConnectorScope(
        connector="google_calendar",
        account_ref="acct_123",
        object_scopes=("primary",),
        operations=("event_search",),
    )
    ambiguous_store.create_grant(ambiguous_scope, actor="one", now=20)
    ambiguous_store.create_grant(ambiguous_scope, actor="two", now=21)
    ambiguous_audit = ReadConnectorAuditLog()
    ambiguous_runtime = runtime_mod.ReadConnectorRuntime(
        grants=ambiguous_store,
        audit=ambiguous_audit,
        credential_factory=lambda connector: FakeCredential(connector),
    )
    rejects(
        lambda: ambiguous_runtime.run(
            "google_calendar",
            {"object_scope": "primary", "operation": "event_search"},
        ),
        tools_mod.ToolDenied,
        "ambiguous exact grants fail before transport",
    )
    check(
        ambiguous_audit.recent(connector="google_calendar")[0]["detail"] == "ambiguous_active_exact_grants",
        "ambiguous grants are categorically audited",
    )
    ambiguous_store.close()
    ambiguous_audit.close()
finally:
    runtime_mod.ProviderPinnedTransport = original_transport
    runtime_mod.AccountBoundReadConnectorClient = original_client


# Successful runtime composition and error redaction are tested with a fake
# provider seam. The authority/source types are real; no network or token exists.
success_store = ReadConnectorGrantStore()
success_scope = ReadConnectorScope(
    connector="google_calendar",
    account_ref="acct_123",
    object_scopes=("primary",),
    operations=("event_search",),
)
success_grant = success_store.create_grant(success_scope, actor="test", now=30)
success_audit = ReadConnectorAuditLog()
source = ReadConnectorSourceReceipt(
    connector="google_calendar",
    grant_id=success_grant.grant_id,
    scope_sha256=success_grant.scope.digest,
    account_ref="acct_123",
    workspace_ref=None,
    object_scope="primary",
    operation="event_search",
    source_id="event_1",
    object_id="event_1",
    revision="rev_1",
    retrieved_at=40,
)


class FakeTransport:
    def __init__(self, *, credentials) -> None:
        self.credentials = credentials


class GoodClient:
    def __init__(self, *, grants, transport) -> None:
        self.grants = grants
        self.transport = transport

    def read(self, grant_id, request, *, now):
        check(grant_id == success_grant.grant_id, "runtime passes exact grant id to provider client")
        check(now == 40, "runtime passes controlled execution time")
        return ProviderReadResult(
            connector=request.connector,
            operation=request.operation,
            object_scope=request.object_scope,
            value={"items": [{"id": "event_1", "summary": "review"}]},
            next_cursor=None,
            sources=(source,),
        )


runtime_mod.ProviderPinnedTransport = FakeTransport
runtime_mod.AccountBoundReadConnectorClient = GoodClient
try:
    good_runtime = runtime_mod.ReadConnectorRuntime(
        grants=success_store,
        audit=success_audit,
        credential_factory=lambda connector: FakeCredential(connector),
        now=lambda: 40,
    )
    raw = good_runtime.run(
        "google_calendar",
        {"object_scope": "primary", "operation": "event_search"},
    )
    result = json.loads(raw)
    check(result["schema"] == "kaliv-read-connector-tool-result/v1", "runtime emits versioned tool result")
    check(result["capability_id"] == capability_id("google_calendar"), "result preserves capability identity")
    check(result["sources"][0]["source_id"] == "event_1", "result carries source grounding receipt")
    check(result["production_activation"] is False, "runtime result cannot claim production activation")
    executed = success_audit.recent(connector="google_calendar")[0]
    check(
        executed["outcome"] == "executed"
        and executed["account_ref"] == "acct_123"
        and executed["object_scope"] == "primary"
        and executed["operation"] == "event_search",
        "runtime audit distinguishes connector account scope and operation",
    )

    class ErrorClient(GoodClient):
        def read(self, grant_id, request, *, now):
            del grant_id, request, now
            raise ReadConnectorRemoteError("TOPSECRET provider body")

    runtime_mod.AccountBoundReadConnectorClient = ErrorClient
    try:
        good_runtime.run(
            "google_calendar",
            {"object_scope": "primary", "operation": "event_search"},
        )
    except tools_mod.ToolError as exc:
        check("TOPSECRET" not in str(exc), "provider error does not leak body into ToolError")
        check("providerkaldet fejlede" in str(exc), "provider error is reduced to bounded message")
    else:
        check(False, "provider error is surfaced as ToolError")
    errored = success_audit.recent(connector="google_calendar")[0]
    check(errored["detail"] == "provider_execution_failed", "provider error audit is categorical")
finally:
    runtime_mod.ProviderPinnedTransport = original_transport
    runtime_mod.AccountBoundReadConnectorClient = original_client
    success_store.close()
    success_audit.close()


# Loopback operator flow: preview binds the exact digest; create persists it;
# readiness composes credential state; revoke is digest-bound and immediately
# changes readiness. Credentials are metadata-only fakes and no provider call runs.
with tempfile.TemporaryDirectory() as td:
    old_grants_db = runtime_mod._GRANTS_DB
    old_audit_db = runtime_mod._AUDIT_DB
    old_credentials = runtime_mod._credentials
    runtime_mod._GRANTS_DB = os.path.join(td, "grants.db")
    runtime_mod._AUDIT_DB = os.path.join(td, "audit.db")
    runtime_mod._credentials = lambda connector: FakeCredential(connector)
    try:
        operator_app = FastAPI()
        operator_app.include_router(runtime_mod.build_read_connector_router())
        client = TestClient(operator_app, client=("127.0.0.1", 51234))
        scope_body = {
            "connector": "google_calendar",
            "object_scopes": ["primary"],
            "operations": ["event_search"],
        }
        preview = client.post("/read-connectors/grants/preview", json=scope_body)
        check(preview.status_code == 200, "operator can preview exact connector grant")
        preview_json = preview.json()
        digest = preview_json["scope_sha256"]
        check(preview_json["grant_persisted"] is False, "preview never persists standing authority")
        check(preview_json["production_activation"] is False, "preview cannot claim production activation")

        bad_digest = client.post(
            "/read-connectors/grants",
            json={**scope_body, "expected_scope_sha256": "A" * 64},
        )
        check(bad_digest.status_code == 422, "grant digest must be lowercase SHA-256")

        created = client.post(
            "/read-connectors/grants",
            json={**scope_body, "expected_scope_sha256": digest},
        )
        check(created.status_code == 200, "operator creates preview-bound exact grant")
        grant = created.json()["grant"]
        grant_id = grant["grant_id"]
        check(grant["scope_sha256"] == digest, "persisted grant retains preview digest")
        check(created.json()["production_activation"] is False, "grant creation is still dormant")

        overlap = client.post(
            "/read-connectors/grants",
            json={**scope_body, "expected_scope_sha256": digest},
        )
        check(overlap.status_code == 409, "overlapping active grant is rejected")

        listed = client.get("/read-connectors/grants")
        check(listed.status_code == 200 and len(listed.json()["grants"]) == 1, "operator grant list reads durable authority")

        readiness = client.get(f"/read-connectors/readiness/google_calendar/{grant_id}")
        check(readiness.status_code == 200, "operator readiness route is available")
        check(readiness.json()["state"] == "ready", "active scope plus ready credential is ready")
        check(readiness.json()["production_activation"] is False, "ready state does not imply production activation")

        wrong_revoke = client.post(
            f"/read-connectors/grants/{grant_id}/revoke",
            json={"expected_scope_sha256": "0" * 64, "confirm_revoke": True},
        )
        check(wrong_revoke.status_code == 409, "revocation fails when preview digest changed")

        revoked = client.post(
            f"/read-connectors/grants/{grant_id}/revoke",
            json={"expected_scope_sha256": digest, "confirm_revoke": True},
        )
        check(revoked.status_code == 200, "operator can revoke exact preview-bound grant")
        check(revoked.json()["grant"]["status"] == "revoked", "revocation is durably recorded")

        after = client.get(f"/read-connectors/readiness/google_calendar/{grant_id}")
        check(after.status_code == 200 and after.json()["state"] == "revoked", "revocation immediately changes readiness")
    finally:
        runtime_mod._GRANTS_DB = old_grants_db
        runtime_mod._AUDIT_DB = old_audit_db
        runtime_mod._credentials = old_credentials


print(f"\n===== T-037 RUNTIME: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
