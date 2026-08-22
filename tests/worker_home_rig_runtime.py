from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

import app.home_rig_tool as runtime_module  # noqa: E402
from app import tools  # noqa: E402
from app.data_sharing import DataSharingLedger  # noqa: E402
from app.home_assistant_provider_transport import HomeAssistantTransportError  # noqa: E402
from app.home_rig_connector_contract import (  # noqa: E402
    HomeRigAuditLog,
    HomeRigGrantStore,
    HomeRigScope,
)
from app.home_rig_provider_gate import finish_home_assistant_state_request  # noqa: E402
from app.riggate_provider_transport import RigGateTransportError  # noqa: E402
from app.riggate_v1_contract import finish_riggate_request  # noqa: E402

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


class UUIDs:
    def __init__(self, start: int = 0) -> None:
        self.value = start

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


class Clock:
    def __init__(self, value: int = 10_000) -> None:
        self.value = value

    def __call__(self) -> int:
        self.value += 1
        return self.value


def permit(runtime: runtime_module.HomeRigRuntime, *, kind: str, target: str, operation: str) -> str:
    claim = runtime.prepare_claim(
        target_kind=kind,
        target_id=target,
        operation=operation,
    )
    request = runtime.sharing_request(claim)
    proposal = runtime.sharing.propose(request, now=runtime.now())
    runtime.sharing.approve(proposal.permission_id, actor="operator", now=runtime.now())
    return proposal.permission_id


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="modelrig-t038-runtime-test-") as td:
        grants = HomeRigGrantStore(os.path.join(td, "grants.db"), uuid_factory=UUIDs())
        audit = HomeRigAuditLog(os.path.join(td, "audit.db"))
        sharing = DataSharingLedger(os.path.join(td, "sharing.db"), uuid_factory=UUIDs(100))
        clock = Clock()
        runtime = runtime_module.HomeRigRuntime(
            grants=grants,
            audit=audit,
            sharing=sharing,
            now=clock,
            max_freshness_seconds=120,
        )
        grants.create(
            HomeRigScope(
                rig_ids=("render-rig-1",),
                entity_ids=("sensor.gpu_temp",),
                operations=(
                    "rig_health",
                    "rig_power_readiness",
                    "entity_state",
                    "wake_preview",
                    "control_preview",
                ),
            ),
            actor="operator",
            now=clock(),
        )

        original_rig_connection = runtime_module._riggate_connection
        original_rig_execute = runtime_module.execute_riggate_status_read
        original_ha_connection = runtime_module._home_assistant_connection
        original_ha_execute = runtime_module.execute_home_assistant_state_read
        try:
            runtime_module._riggate_connection = lambda: object()
            runtime_module._home_assistant_connection = lambda: object()

            # Fresh status brief: provider state remains usable and source-bound.
            rig_permission = permit(
                runtime,
                kind="rig",
                target="render-rig-1",
                operation="rig_health",
            )

            def fresh_rig(grants_arg, ledger_arg, authorized, connection, *, now, **kwargs):
                finish_riggate_request(
                    ledger_arg,
                    authorized,
                    outcome="completed",
                    bytes_sent=authorized.sharing_request.max_bytes,
                    now=now,
                )
                return SimpleNamespace(state="ready", observed_at=now)

            runtime_module.execute_riggate_status_read = fresh_rig
            result = json.loads(
                runtime.read(
                    target_kind="rig",
                    target_id="render-rig-1",
                    operation="rig_health",
                    permission_id=rig_permission,
                )
            )
            observation = result["observation"]
            check(observation["state"] == "ready", "fresh RigGate status remains ready")
            check(observation["freshness"] == "fresh", "fresh RigGate status is marked fresh")
            check(observation["source"] == "riggate", "status brief preserves RigGate source")

            # Stale provider evidence must normalize to unknown, never stale-ready.
            stale_permission = permit(
                runtime,
                kind="rig",
                target="render-rig-1",
                operation="rig_power_readiness",
            )

            def stale_rig(grants_arg, ledger_arg, authorized, connection, *, now, **kwargs):
                finish_riggate_request(
                    ledger_arg,
                    authorized,
                    outcome="completed",
                    bytes_sent=authorized.sharing_request.max_bytes,
                    now=now,
                )
                return SimpleNamespace(state="ready", observed_at=now - 121)

            runtime_module.execute_riggate_status_read = stale_rig
            result = json.loads(
                runtime.read(
                    target_kind="rig",
                    target_id="render-rig-1",
                    operation="rig_power_readiness",
                    permission_id=stale_permission,
                )
            )
            observation = result["observation"]
            check(observation["state"] == "unknown", "stale RigGate status is never ready")
            check(observation["freshness"] == "stale", "stale RigGate evidence is explicit")

            # Offline RigGate closes T-032 as failed but still returns the safe
            # T-038 observation promised by issue #85: unknown/unavailable.
            offline_permission = permit(
                runtime,
                kind="rig",
                target="render-rig-1",
                operation="rig_health",
            )

            def offline_rig(grants_arg, ledger_arg, authorized, connection, *, now, **kwargs):
                finish_riggate_request(
                    ledger_arg,
                    authorized,
                    outcome="failed",
                    bytes_sent=0,
                    error_code="riggate_read_failed",
                    now=now,
                )
                raise RigGateTransportError("fixture offline")

            runtime_module.execute_riggate_status_read = offline_rig
            result = json.loads(
                runtime.read(
                    target_kind="rig",
                    target_id="render-rig-1",
                    operation="rig_health",
                    permission_id=offline_permission,
                )
            )
            observation = result["observation"]
            check(observation["state"] == "unknown", "offline RigGate returns unknown")
            check(observation["freshness"] == "unavailable", "offline RigGate returns unavailable freshness")
            check(observation["observed_at"] is None, "offline RigGate invents no observation timestamp")
            finished = [row for row in sharing.recent_events(limit=100) if row["event_type"] == "finished"]
            check(
                any(row["outcome"] == "failed" and row["error_code"] == "riggate_read_failed" for row in finished),
                "offline RigGate retains failed T-032 transport evidence",
            )

            # Home Assistant transport unavailability follows the same safe rule.
            ha_permission = permit(
                runtime,
                kind="entity",
                target="sensor.gpu_temp",
                operation="entity_state",
            )

            def offline_ha(grants_arg, ledger_arg, authorized, connection, *, now, **kwargs):
                finish_home_assistant_state_request(
                    ledger_arg,
                    authorized,
                    outcome="failed",
                    bytes_sent=0,
                    error_code="home_assistant_read_failed",
                    now=now,
                )
                raise HomeAssistantTransportError("fixture offline")

            runtime_module.execute_home_assistant_state_read = offline_ha
            result = json.loads(
                runtime.read(
                    target_kind="entity",
                    target_id="sensor.gpu_temp",
                    operation="entity_state",
                    permission_id=ha_permission,
                )
            )
            observation = result["observation"]
            check(observation["state"] == "unknown", "offline Home Assistant returns unknown")
            check(observation["freshness"] == "unavailable", "offline Home Assistant is unavailable")

            # An unscoped entity is denied before provider configuration/execution.
            provider_calls: list[str] = []
            runtime_module._home_assistant_connection = lambda: provider_calls.append("config") or object()
            try:
                runtime.read(
                    target_kind="entity",
                    target_id="sensor.secret",
                    operation="entity_state",
                    permission_id="dsp_00000000000000000000000000000000",
                )
            except tools.ToolDenied:
                pass
            else:
                check(False, "unscoped entity is denied")
            check(provider_calls == [], "unscoped entity never reaches provider configuration")

            # Missing deployment config is not disguised as an offline device;
            # the already-claimed one-use receipt must still be terminally closed.
            config_permission = permit(
                runtime,
                kind="rig",
                target="render-rig-1",
                operation="rig_health",
            )
            runtime_module._riggate_connection = lambda: (_ for _ in ()).throw(
                RigGateTransportError("configuration missing")
            )
            try:
                runtime.read(
                    target_kind="rig",
                    target_id="render-rig-1",
                    operation="rig_health",
                    permission_id=config_permission,
                )
            except tools.ToolError:
                pass
            else:
                check(False, "missing provider configuration fails explicitly")
            finished = [row for row in sharing.recent_events(limit=100) if row["event_type"] == "finished"]
            check(
                any(row["outcome"] == "failed" and row["error_code"] == "provider_config_failed" for row in finished),
                "provider config failure leaves no T-032 receipt in flight",
            )

            # Preview contract remains inert while the runtime is present.
            wake = json.loads(runtime.preview(target_kind="rig", target_id="render-rig-1", action="wake"))
            control = json.loads(
                runtime.preview(
                    target_kind="entity",
                    target_id="sensor.gpu_temp",
                    action="turn_off",
                )
            )
            check(wake["would_execute"] is False, "wake remains preview-only")
            check(control["would_execute"] is False, "control remains preview-only")

            audit_rows = audit.recent(limit=100)
            check(
                any(row["connector"] == "riggate" and row["detail"] == "source_unavailable" for row in audit_rows),
                "offline RigGate is auditable as source_unavailable",
            )
            check(
                any(row["connector"] == "home_assistant" and row["detail"] == "source_unavailable" for row in audit_rows),
                "offline Home Assistant is auditable as source_unavailable",
            )
        finally:
            runtime_module._riggate_connection = original_rig_connection
            runtime_module.execute_riggate_status_read = original_rig_execute
            runtime_module._home_assistant_connection = original_ha_connection
            runtime_module.execute_home_assistant_state_read = original_ha_execute
            grants.close()
            audit.close()
            sharing.close()

    print(f"===== T-038 HOME/RIG RUNTIME: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
