from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.data_sharing import DataSharingLedger
from app.home_assistant_state_execution import (
    HomeAssistantStateExecutionDenied,
    HomeAssistantStateExecutionError,
    HomeAssistantStateExecutor,
    HomeAssistantStateTransportResult,
)
from app.home_rig_connector_contract import HomeRigAuditLog, HomeRigGrantStore, HomeRigScope
from app.home_rig_read_boundary import prepare_read
from app.home_rig_read_lease import HomeRigReadSharingBoundary


class UUIDs:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def state_body(entity: str, state: str, received_at: int) -> bytes:
    stamp = iso(received_at)
    return json.dumps(
        {
            "entity_id": entity,
            "state": state,
            "attributes": {"friendly_name": "GPU temperature", "canary": "MUST_NOT_ESCAPE"},
            "last_changed": stamp,
            "last_updated": stamp,
            "context": {"id": "MUST_NOT_ESCAPE"},
        },
        separators=(",", ":"),
    ).encode()


class FakeTransport:
    def __init__(
        self,
        *,
        mode: str = "success",
        state: str = "61.0",
        received_at: int = 106,
    ) -> None:
        self.mode = mode
        self.state = state
        self.received_at = received_at
        self.revoke = None
        self.calls = 0
        self.plans = []

    def execute(self, plan):
        self.calls += 1
        self.plans.append(plan)
        if self.revoke is not None:
            store, grant_id, scope_digest = self.revoke
            store.revoke(
                grant_id,
                expected_scope_sha256=scope_digest,
                actor="operator",
                now=self.received_at,
            )
        if self.mode == "raise":
            raise RuntimeError("provider-canary")
        if self.mode == "failure":
            return HomeAssistantStateTransportResult(
                request_plan_sha256=plan.digest,
                entity_id=plan.entity_id,
                request_bytes_sent=72,
                received_at=self.received_at,
                error_code="provider_unavailable",
            )
        return HomeAssistantStateTransportResult(
            request_plan_sha256="0" * 64 if self.mode == "identity" else plan.digest,
            entity_id=plan.entity_id,
            request_bytes_sent=72,
            received_at=self.received_at,
            status_code=200,
            content_type="application/json; charset=utf-8",
            body=state_body(plan.entity_id, self.state, self.received_at),
        )


def make_context(transport: FakeTransport):
    grants = HomeRigGrantStore(uuid_factory=UUIDs())
    ledger = DataSharingLedger(uuid_factory=UUIDs())
    audit = HomeRigAuditLog()
    scope = HomeRigScope(entity_ids=("sensor.gpu_temp",), operations=("entity_state",))
    grant = grants.create(scope, actor="operator", now=100)
    claim = prepare_read(
        grants,
        grant.grant_id,
        target_kind="entity",
        target_id="sensor.gpu_temp",
        operation="entity_state",
        now=101,
    )
    sharing = HomeRigReadSharingBoundary(grants, ledger)
    proposal = sharing.propose(claim, now=102)
    ledger.approve(proposal.permission_id, actor="operator", now=103)
    lease = sharing.prepare(
        claim,
        permission_id=proposal.permission_id,
        now=104,
        receipt_ttl_seconds=60,
    )
    executor = HomeAssistantStateExecutor(
        grants=grants,
        sharing=sharing,
        audit=audit,
        transport=transport,
    )
    return grants, ledger, audit, scope, grant, claim, lease, executor


def finished(ledger: DataSharingLedger, lease):
    rows = [
        row
        for row in ledger.recent_events(100)
        if row["receipt_id"] == lease.receipt.receipt_id and row["event_type"] == "finished"
    ]
    assert len(rows) == 1, rows
    return rows[0]


def close_all(grants, ledger, audit) -> None:
    audit.close()
    ledger.close()
    grants.close()


def main() -> None:
    transport = FakeTransport()
    grants, ledger, audit, scope, grant, claim, lease, executor = make_context(transport)
    result = executor.execute(lease, claim, now=105)
    assert transport.calls == 1 and len(transport.plans) == 1
    observation = result.read_receipt.observation
    assert observation.source == "home_assistant"
    assert observation.target_id == "sensor.gpu_temp"
    assert observation.state == "61.0" and observation.freshness == "fresh"
    rendered = json.dumps(result.to_dict(), sort_keys=True)
    assert "MUST_NOT_ESCAPE" not in rendered
    assert "attributes" not in rendered and "context" not in rendered
    audit_rows = audit.recent()
    assert len(audit_rows) == 1 and audit_rows[0]["outcome"] == "executed"
    assert audit_rows[0]["freshness"] == "fresh"
    assert "61.0" not in json.dumps(audit_rows, sort_keys=True)
    event = finished(ledger, lease)
    assert event["outcome"] == "completed" and event["bytes_sent"] == 72
    try:
        executor.execute(lease, claim, now=107)
    except HomeAssistantStateExecutionDenied:
        pass
    else:
        raise AssertionError("one-use receipt was replayed")
    assert transport.calls == 1
    close_all(grants, ledger, audit)

    transport = FakeTransport(state="unavailable")
    grants, ledger, audit, scope, grant, claim, lease, executor = make_context(transport)
    result = executor.execute(lease, claim, now=105)
    assert result.read_receipt.observation.state == "unknown"
    assert result.read_receipt.observation.freshness == "unavailable"
    assert finished(ledger, lease)["outcome"] == "completed"
    close_all(grants, ledger, audit)

    for mode, received_at, expected_code in (
        ("identity", 106, "transport_identity"),
        ("success", 104, "transport_time"),
        ("failure", 106, "provider_unavailable"),
        ("raise", 106, "transport_contract"),
    ):
        transport = FakeTransport(mode=mode, received_at=received_at)
        grants, ledger, audit, scope, grant, claim, lease, executor = make_context(transport)
        try:
            executor.execute(lease, claim, now=105)
        except HomeAssistantStateExecutionError as exc:
            assert "provider-canary" not in str(exc)
            if mode == "raise":
                assert exc.__cause__ is None
        else:
            raise AssertionError(f"negative transport case was accepted: {mode}")
        assert transport.calls == 1
        event = finished(ledger, lease)
        assert event["outcome"] == "failed"
        assert event["error_code"] == expected_code
        assert event["bytes_sent"] == (0 if mode == "raise" else 72)
        close_all(grants, ledger, audit)

    transport = FakeTransport()
    grants, ledger, audit, scope, grant, claim, lease, executor = make_context(transport)
    transport.revoke = (grants, grant.grant_id, scope.digest)
    try:
        executor.execute(lease, claim, now=105)
    except HomeAssistantStateExecutionDenied:
        pass
    else:
        raise AssertionError("revoked in-flight read returned provider state")
    assert transport.calls == 1
    event = finished(ledger, lease)
    assert event["outcome"] == "blocked"
    assert event["bytes_sent"] == 72 and event["error_code"] == "revoked_in_flight"
    audit_rows = audit.recent()
    assert len(audit_rows) == 1
    assert audit_rows[0]["outcome"] == "blocked"
    assert audit_rows[0]["detail"] == "authority_revoked_in_flight"
    close_all(grants, ledger, audit)

    print("T-038 one-shot Home Assistant read composition: PASS")


if __name__ == "__main__":
    main()
