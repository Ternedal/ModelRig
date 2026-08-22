from __future__ import annotations

import ast
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.data_sharing import DataSharingDenied, DataSharingLedger  # noqa: E402
from app.home_rig_connector_contract import (  # noqa: E402
    HomeRigAuditLog,
    HomeRigDenied,
    HomeRigGrantStore,
    HomeRigScope,
)
from app.home_rig_read_boundary import fulfill_read, prepare_read  # noqa: E402
from app.riggate_v1_contract import (  # noqa: E402
    RigGateProtocolError,
    authorize_riggate_request,
    finish_riggate_request,
    parse_riggate_status_response,
    prepare_riggate_sharing_request,
)

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def rejects(fn, exc_type, name: str, contains: str = "") -> None:
    try:
        fn()
    except exc_type as exc:
        check(not contains or contains in str(exc), name)
    else:
        check(False, name)


class UUIDs:
    def __init__(self, start: int = 0) -> None:
        self.value = start

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


def rig_scope() -> HomeRigScope:
    return HomeRigScope(
        rig_ids=("render-rig-1",),
        operations=("rig_health", "rig_power_readiness"),
    )


def body(operation: str, state: str, observed_at: int, *, rig_id: str = "render-rig-1") -> bytes:
    return json.dumps(
        {
            "schema": "kaliv-riggate-status/v1",
            "rig_id": rig_id,
            "operation": operation,
            "state": state,
            "observed_at": observed_at,
        },
        separators=(",", ":"),
    ).encode("utf-8")


def main() -> int:
    # Source-level dormancy is part of this slice: the protocol must not smuggle
    # a transport/runtime/control path into the repository under a read label.
    source_path = os.path.join(
        os.path.dirname(__file__), "..", "worker", "app", "riggate_v1_contract.py"
    )
    source = open(source_path, encoding="utf-8").read()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    check(
        {"socket", "ssl", "http", "requests", "httpx", "subprocess", "os"}.isdisjoint(imported),
        "RigGate v1 contract imports no transport/process/environment authority",
    )
    for forbidden in (
        "REGISTRY[",
        "FastAPI(",
        "APIRouter(",
        "include_router(",
        "os.getenv(",
        "os.environ",
        "urlopen(",
        "requests.",
        "httpx.",
        "Authorization",
        "Bearer ",
        "wake_execute",
        "control_execute",
    ):
        check(forbidden not in source, f"RigGate v1 remains dormant: no {forbidden}")
    check("PRODUCTION_ACTIVATION = False" in source, "production activation is structurally false")

    # Public read: exact durable scope -> exact T-032 request -> one-use receipt
    # -> final durable re-authorization -> exact GET plan.
    grants = HomeRigGrantStore(uuid_factory=UUIDs())
    ledger = DataSharingLedger(uuid_factory=UUIDs(100))
    audit = HomeRigAuditLog()
    try:
        grant = grants.create(rig_scope(), actor="operator", now=100)
        health_claim = prepare_read(
            grants,
            grant.grant_id,
            target_kind="rig",
            target_id="render-rig-1",
            operation="rig_health",
            now=101,
        )
        preview = prepare_riggate_sharing_request(
            grants,
            health_claim,
            data_category="public",
            purpose_code="status_brief",
            purpose="Read health for one explicitly scoped rig.",
            summary="Scoped RigGate health lookup",
        )
        check(preview.provider == "riggate", "T-032 provider is exactly riggate")
        check(
            preview.destination == f"riggate/{grant.scope.digest}",
            "T-032 destination is bound to exact scope digest",
        )
        authorized = authorize_riggate_request(
            grants,
            ledger,
            health_claim,
            data_category="public",
            purpose_code="status_brief",
            purpose="Read health for one explicitly scoped rig.",
            summary="Scoped RigGate health lookup",
            now=102,
        )
        check(authorized.sharing_request.digest == preview.digest, "preview and authorization rebuild exact request")
        check(authorized.sharing_receipt.authorization == "automatic", "public RigGate read is automatic but receipted")
        check(authorized.plan.method == "GET", "RigGate plan is GET-only")
        check(authorized.plan.path == "/v1/rigs/render-rig-1/health", "health path is exact")
        check(authorized.plan.follow_redirects is False, "RigGate plan forbids redirects")
        check(authorized.plan.production_activation is False, "RigGate plan remains non-production")
        check("origin" not in authorized.plan.to_dict(), "plan carries no provider origin")
        check("token" not in authorized.plan.to_dict(), "plan carries no credential value")
        rejects(
            lambda: ledger.claim(authorized.sharing_receipt, authorized.sharing_request, now=103),
            DataSharingDenied,
            "T-032 RigGate receipt cannot be claimed twice",
            "not claimable",
        )
        finish_riggate_request(
            ledger,
            authorized,
            outcome="completed",
            bytes_sent=authorized.sharing_request.max_bytes,
            now=104,
        )
        event_types = {row["event_type"] for row in ledger.recent_events()}
        check(event_types >= {"authorized", "claimed", "finished"}, "T-032 lifecycle is fully auditable")

        power_claim = prepare_read(
            grants,
            grant.grant_id,
            target_kind="rig",
            target_id="render-rig-1",
            operation="rig_power_readiness",
            now=105,
        )
        power = authorize_riggate_request(
            grants,
            ledger,
            power_claim,
            data_category="public",
            purpose_code="status_brief",
            purpose="Read power readiness for one explicitly scoped rig.",
            summary="Scoped RigGate power/readiness lookup",
            now=106,
        )
        check(
            power.plan.path == "/v1/rigs/render-rig-1/power-readiness",
            "power/readiness path is exact",
        )
        finish_riggate_request(
            ledger,
            power,
            outcome="completed",
            bytes_sent=power.sharing_request.max_bytes,
            now=107,
        )

        # Wire response must bind exact rig and operation. Existing T-038 read
        # fulfillment owns freshness semantics and privacy-minimized audit.
        evidence = parse_riggate_status_response(
            body("rig_health", "ready", 108),
            expected_rig_id="render-rig-1",
            expected_operation="rig_health",
        )
        check(evidence.source == "riggate" and evidence.state == "ready", "valid RigGate evidence parses")
        fresh_receipt = fulfill_read(
            grants,
            audit,
            health_claim,
            source_state=evidence.state,
            observed_at=evidence.observed_at,
            now=110,
            max_freshness_seconds=10,
        )
        check(fresh_receipt.observation.state == "ready", "fresh RigGate ready may remain ready")
        check(fresh_receipt.observation.freshness == "fresh", "fresh RigGate evidence is marked fresh")
        check(fresh_receipt.observation.source == "riggate", "normalized source remains RigGate")

        stale = parse_riggate_status_response(
            body("rig_health", "ready", 100),
            expected_rig_id="render-rig-1",
            expected_operation="rig_health",
        )
        stale_receipt = fulfill_read(
            grants,
            audit,
            health_claim,
            source_state=stale.state,
            observed_at=stale.observed_at,
            now=200,
            max_freshness_seconds=10,
        )
        check(stale_receipt.observation.state == "unknown", "stale ready is normalized to unknown")
        check(stale_receipt.observation.freshness == "stale", "stale RigGate evidence is explicit")

        unavailable = parse_riggate_status_response(
            body("rig_health", "unavailable", 201),
            expected_rig_id="render-rig-1",
            expected_operation="rig_health",
        )
        unavailable_receipt = fulfill_read(
            grants,
            audit,
            health_claim,
            source_state=unavailable.state,
            observed_at=unavailable.observed_at,
            now=202,
        )
        check(unavailable_receipt.observation.state == "unknown", "unavailable RigGate state is unknown")
        check(
            unavailable_receipt.observation.freshness == "unavailable",
            "unavailable RigGate evidence cannot look ready",
        )
        rows = audit.recent(limit=10)
        check(any(row["connector"] == "riggate" for row in rows), "audit records RigGate connector")
        check(any(row["target_id"] == "render-rig-1" for row in rows), "audit records exact rig object")
    finally:
        audit.close()
        grants.close()
        ledger.close()

    # Operational read must consume an exact approved permission, exactly once.
    grants = HomeRigGrantStore(uuid_factory=UUIDs(200))
    ledger = DataSharingLedger(uuid_factory=UUIDs(300))
    try:
        grant = grants.create(rig_scope(), actor="operator", now=300)
        claim = prepare_read(
            grants,
            grant.grant_id,
            target_kind="rig",
            target_id="render-rig-1",
            operation="rig_health",
            now=301,
        )
        operational_preview = prepare_riggate_sharing_request(
            grants,
            claim,
            data_category="operational",
            purpose_code="status_brief",
            purpose="Read operational health for one explicitly scoped rig.",
            summary="Operational RigGate health lookup",
        )
        rejects(
            lambda: authorize_riggate_request(
                grants,
                ledger,
                claim,
                data_category="operational",
                purpose_code="status_brief",
                purpose="Read operational health for one explicitly scoped rig.",
                summary="Operational RigGate health lookup",
                now=302,
            ),
            DataSharingDenied,
            "operational RigGate read cannot bypass exact permission",
            "exact permission",
        )
        proposal = ledger.propose(operational_preview, now=303)
        ledger.approve(proposal.permission_id, actor="operator", now=304)
        permitted = authorize_riggate_request(
            grants,
            ledger,
            claim,
            data_category="operational",
            purpose_code="status_brief",
            purpose="Read operational health for one explicitly scoped rig.",
            summary="Operational RigGate health lookup",
            permission_id=proposal.permission_id,
            now=305,
        )
        check(permitted.sharing_receipt.authorization == "permission", "operational RigGate read uses permission")
        rejects(
            lambda: authorize_riggate_request(
                grants,
                ledger,
                claim,
                data_category="operational",
                purpose_code="status_brief",
                purpose="Read operational health for one explicitly scoped rig.",
                summary="Operational RigGate health lookup",
                permission_id=proposal.permission_id,
                now=306,
            ),
            DataSharingDenied,
            "consumed RigGate permission cannot be reused",
            "not approved",
        )
        finish_riggate_request(
            ledger,
            permitted,
            outcome="completed",
            bytes_sent=permitted.sharing_request.max_bytes,
            now=307,
        )
    finally:
        grants.close()
        ledger.close()

    # Secret payloads are forbidden by T-032 before any request plan exists.
    grants = HomeRigGrantStore(uuid_factory=UUIDs(400))
    ledger = DataSharingLedger(uuid_factory=UUIDs(500))
    try:
        grant = grants.create(rig_scope(), actor="operator", now=400)
        claim = prepare_read(
            grants,
            grant.grant_id,
            target_kind="rig",
            target_id="render-rig-1",
            operation="rig_health",
            now=401,
        )
        rejects(
            lambda: authorize_riggate_request(
                grants,
                ledger,
                claim,
                data_category="secret",
                purpose_code="forbidden_secret",
                purpose="This must never cross the connector boundary.",
                summary="Forbidden secret RigGate request",
                now=402,
            ),
            DataSharingDenied,
            "secret RigGate data cannot produce a plan",
            "forbids",
        )
    finally:
        grants.close()
        ledger.close()

    # Revoke after T-032 claim but before final durable re-authorization: no plan
    # may escape and the already-claimed receipt is terminally blocked.
    class RevokingStore(HomeRigGrantStore):
        def __init__(self) -> None:
            super().__init__(uuid_factory=UUIDs(600))
            self.calls = 0
            self.revoke_on_call: int | None = None

        def authorize(self, grant_id, *, target_kind, target_id, operation):
            self.calls += 1
            if self.revoke_on_call == self.calls:
                current = self.get(grant_id)
                assert current is not None
                self.revoke(
                    grant_id,
                    expected_scope_sha256=current.scope.digest,
                    actor="concurrent-operator",
                    now=504,
                )
            return super().authorize(
                grant_id,
                target_kind=target_kind,
                target_id=target_id,
                operation=operation,
            )

    grants = RevokingStore()
    ledger = DataSharingLedger(uuid_factory=UUIDs(700))
    try:
        grant = grants.create(rig_scope(), actor="operator", now=500)
        claim = prepare_read(
            grants,
            grant.grant_id,
            target_kind="rig",
            target_id="render-rig-1",
            operation="rig_health",
            now=501,
        )
        preview = prepare_riggate_sharing_request(
            grants,
            claim,
            data_category="operational",
            purpose_code="status_brief",
            purpose="Read one scoped rig with concurrent-revoke protection.",
            summary="Concurrent revoke proof",
        )
        proposal = ledger.propose(preview, now=502)
        ledger.approve(proposal.permission_id, actor="operator", now=503)
        # Calls so far: prepare_read=1, preview=2. authorize() rebuilds preview
        # on call 3, claims T-032, then must perform final durable call 4.
        grants.revoke_on_call = 4
        rejects(
            lambda: authorize_riggate_request(
                grants,
                ledger,
                claim,
                data_category="operational",
                purpose_code="status_brief",
                purpose="Read one scoped rig with concurrent-revoke protection.",
                summary="Concurrent revoke proof",
                permission_id=proposal.permission_id,
                now=504,
            ),
            HomeRigDenied,
            "concurrent revoke after T-032 claim yields no RigGate plan",
        )
        finished = [row for row in ledger.recent_events() if row["event_type"] == "finished"]
        check(bool(finished) and finished[0]["outcome"] == "blocked", "concurrent revoke closes receipt blocked")
        check(
            bool(finished) and finished[0]["error_code"] == "authority_revoked",
            "concurrent revoke records authority_revoked",
        )
    finally:
        grants.close()
        ledger.close()

    # Wire-format fail-closed matrix.
    valid = body("rig_power_readiness", "ready", 600)
    parsed = parse_riggate_status_response(
        valid,
        expected_rig_id="render-rig-1",
        expected_operation="rig_power_readiness",
    )
    check(parsed.rig_id == "render-rig-1", "wire parser retains exact rig id")
    check(parsed.operation == "rig_power_readiness", "wire parser retains exact operation")
    rejects(
        lambda: parse_riggate_status_response(
            valid,
            expected_rig_id="other-rig",
            expected_operation="rig_power_readiness",
        ),
        RigGateProtocolError,
        "wire parser rejects substituted rig",
        "rig_id does not match",
    )
    rejects(
        lambda: parse_riggate_status_response(
            valid,
            expected_rig_id="render-rig-1",
            expected_operation="rig_health",
        ),
        RigGateProtocolError,
        "wire parser rejects substituted operation",
        "operation does not match",
    )
    bad_schema = json.loads(valid)
    bad_schema["schema"] = "kaliv-riggate-status/v2"
    rejects(
        lambda: parse_riggate_status_response(
            json.dumps(bad_schema).encode(),
            expected_rig_id="render-rig-1",
            expected_operation="rig_power_readiness",
        ),
        RigGateProtocolError,
        "wire parser rejects unknown schema",
        "unsupported",
    )
    extra = json.loads(valid)
    extra["debug"] = "should-not-escape"
    rejects(
        lambda: parse_riggate_status_response(
            json.dumps(extra).encode(),
            expected_rig_id="render-rig-1",
            expected_operation="rig_power_readiness",
        ),
        RigGateProtocolError,
        "wire parser rejects extra fields",
        "shape",
    )
    rejects(
        lambda: parse_riggate_status_response(
            b"{not-json",
            expected_rig_id="render-rig-1",
            expected_operation="rig_health",
        ),
        RigGateProtocolError,
        "wire parser rejects malformed JSON",
        "UTF-8 JSON",
    )
    rejects(
        lambda: parse_riggate_status_response(
            b"x" * (64 * 1024 + 1),
            expected_rig_id="render-rig-1",
            expected_operation="rig_health",
        ),
        RigGateProtocolError,
        "wire parser rejects oversized response",
        "size",
    )

    # Write-ish/previews are never valid RigGate provider reads.
    grants = HomeRigGrantStore(uuid_factory=UUIDs(800))
    ledger = DataSharingLedger(uuid_factory=UUIDs(900))
    try:
        preview_scope = HomeRigScope(
            rig_ids=("render-rig-1",),
            operations=("wake_preview",),
        )
        grant = grants.create(preview_scope, actor="operator", now=800)
        # HomeRigReadClaim itself correctly refuses wake_preview before provider
        # authorization can even be attempted.
        rejects(
            lambda: prepare_read(
                grants,
                grant.grant_id,
                target_kind="rig",
                target_id="render-rig-1",
                operation="wake_preview",
                now=801,
            ),
            Exception,
            "wake preview cannot become a RigGate read claim",
        )
    finally:
        grants.close()
        ledger.close()

    print(f"\n===== T-038 RIGGATE V1 CONTRACT: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
