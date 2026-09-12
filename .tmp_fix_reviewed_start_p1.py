from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one replacement, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


planner = "worker/app/agent3/planner.py"
replace_once(
    planner,
    '''    def _reviewed_start_error(reason: str, message: str, status_code: int = 409) -> HTTPException:
        return HTTPException(
            status_code=status_code,
            detail=message,
            headers={"X-ModelRig-Agent3-Reason": reason},
        )
''',
    '''    def _reviewed_start_error(reason: str, message: str, status_code: int = 409) -> HTTPException:
        return HTTPException(
            status_code=status_code,
            detail=message,
            headers={"X-ModelRig-Agent3-Reason": reason},
        )

    def _reconcile_reviewed_start_run(run_id: str) -> AgentRun:
        try:
            return orchestrator.advance(run_id)
        except Exception as exc:
            raise _reviewed_start_error(
                "reviewed_start_pending",
                "persisted reviewed Start requires recovery retry",
                status_code=503,
            ) from exc
''',
)
replace_once(
    planner,
    '''            reserved_run_id = recovered_run_id
            existing = orchestrator.store.load(reserved_run_id)
            if existing is not None:
                plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)
                stored = json.loads(
                    plan_store.reviewed_start_materialization(plan_id, reserved_run_id)
                )
                return _reviewed_start_response(plan_id, stored, existing)
            if state == "accepted":
                raise _reviewed_start_error(
                    "reviewed_start_refused",
                    "accepted reviewed Start is missing its bound run",
                )
            if owner == plan_store.start_owner:
                raise _reviewed_start_error(
                    "reviewed_start_pending",
                    "reviewed Start is still materializing in this worker",
                )
            if not plan_store.claim_reviewed_start_recovery(
                plan_id,
                reserved_run_id,
                owner,
            ):
                raise _reviewed_start_error(
                    "reviewed_start_pending",
                    "reviewed Start recovery changed concurrently",
                )
            payload = plan_store.reviewed_start_materialization(plan_id, reserved_run_id)
''',
    '''            reserved_run_id = recovered_run_id
            existing = orchestrator.store.load(reserved_run_id)
            if state == "accepted":
                if existing is None:
                    raise _reviewed_start_error(
                        "reviewed_start_refused",
                        "accepted reviewed Start is missing its bound run",
                    )
                stored = json.loads(
                    plan_store.reviewed_start_materialization(plan_id, reserved_run_id)
                )
                reconciled = _reconcile_reviewed_start_run(reserved_run_id)
                return _reviewed_start_response(plan_id, stored, reconciled)
            if owner == plan_store.start_owner:
                raise _reviewed_start_error(
                    "reviewed_start_pending",
                    "reviewed Start is still materializing in this worker",
                )
            if not plan_store.claim_reviewed_start_recovery(
                plan_id,
                reserved_run_id,
                owner,
            ):
                raise _reviewed_start_error(
                    "reviewed_start_pending",
                    "reviewed Start recovery changed concurrently",
                )
            payload = plan_store.reviewed_start_materialization(plan_id, reserved_run_id)
            if existing is not None:
                reconciled = _reconcile_reviewed_start_run(reserved_run_id)
                plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)
                stored = json.loads(payload)
                return _reviewed_start_response(plan_id, stored, reconciled)
''',
)
replace_once(
    planner,
    '''        except HTTPException:
            existing = orchestrator.store.load(reserved_run_id)
            if existing is not None:
                plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)
                return _reviewed_start_response(plan_id, envelope, existing)
            plan_store.mark_reviewed_start_refused(plan_id, reserved_run_id)
            raise
        except Exception:
            existing = orchestrator.store.load(reserved_run_id)
            if existing is not None:
                plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)
                return _reviewed_start_response(plan_id, envelope, existing)
            plan_store.mark_reviewed_start_refused(plan_id, reserved_run_id)
            raise
''',
    '''        except HTTPException:
            existing = orchestrator.store.load(reserved_run_id)
            if existing is not None:
                reconciled = _reconcile_reviewed_start_run(reserved_run_id)
                plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)
                return _reviewed_start_response(plan_id, envelope, reconciled)
            plan_store.mark_reviewed_start_refused(plan_id, reserved_run_id)
            raise
        except Exception:
            existing = orchestrator.store.load(reserved_run_id)
            if existing is not None:
                reconciled = _reconcile_reviewed_start_run(reserved_run_id)
                plan_store.mark_reviewed_start_accepted(plan_id, reserved_run_id)
                return _reviewed_start_response(plan_id, envelope, reconciled)
            plan_store.mark_reviewed_start_refused(plan_id, reserved_run_id)
            raise
''',
)

for path in [
    "android/app/src/main/java/dk/ternedal/modelrig/net/Agent3ReviewedStartRecoveryAuthority.kt",
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/Agent3ReviewedStartRecoveryAuthority.kt",
]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    marker = "        private fun validReceipt"
    if text.count(marker) != 1:
        raise SystemExit(f"{path}: validReceipt marker mismatch")
    p.write_text(
        text.replace(
            marker,
            "        fun hasUnresolvedRecord(raw: String?): Boolean = !raw.isNullOrBlank()\n\n" + marker,
            1,
        ),
        encoding="utf-8",
    )

android = "android/app/src/main/java/dk/ternedal/modelrig/ui/Agent3ReviewScreen.kt"
replace_once(
    android,
    '''    var pendingStartRecovery by remember(initialRecoveryRaw) { mutableStateOf(initialRecovery) }

    LaunchedEffect(initialRecoveryRaw, store.baseUrl) {
        if (initialRecoveryRaw != null && initialRecovery == null) {
            recoveryStore.write(store.baseUrl, null)
            error = "En ugyldig lokal Start-recovery blev ryddet; lav et nyt preview."
        }
    }
''',
    '''    var pendingStartRecovery by remember(initialRecoveryRaw) { mutableStateOf(initialRecovery) }
    var startRecoveryUnresolved by remember(initialRecoveryRaw) {
        mutableStateOf(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(initialRecoveryRaw))
    }

    LaunchedEffect(initialRecoveryRaw, store.baseUrl) {
        if (Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(initialRecoveryRaw) && initialRecovery == null) {
            startRecoveryUnresolved = true
            error = "Den lokale Start-recovery kan ikke læses sikkert. Nye previews er blokeret; recovery-recorden er bevaret til operatørkontrol."
        }
    }
''',
)
replace_once(
    android,
    '''        if (pendingStartRecovery != null) {
            error = "Et tidligere Start har uklart udfald. Gendan samme Start før et nyt preview."
            return
        }
''',
    '''        if (startRecoveryUnresolved) {
            error = if (pendingStartRecovery != null) {
                "Et tidligere Start har uklart udfald. Gendan samme Start før et nyt preview."
            } else {
                "En lokal Start-recovery kan ikke valideres. Nyt preview er blokeret, indtil recorden kan afklares sikkert."
            }
            return
        }
''',
)
replace_once(
    android,
    '''        if (recoveryStore.write(connection.baseUrl, null)) {
            pendingStartRecovery = null
        } else {
            pendingStartRecovery = authority
            error = "Run blev valideret, men den lokale Start-recovery kunne ikke ryddes. Samme plan kan sikkert gendannes igen."
        }
''',
    '''        if (recoveryStore.write(connection.baseUrl, null)) {
            pendingStartRecovery = null
            startRecoveryUnresolved = false
        } else {
            pendingStartRecovery = authority
            startRecoveryUnresolved = true
            error = "Run blev valideret, men den lokale Start-recovery kunne ikke ryddes. Samme plan kan sikkert gendannes igen."
        }
''',
)
replace_once(
    android,
    '''            val cleared = recoveryStore.write(connection.baseUrl, null)
            if (cleared) pendingStartRecovery = null
''',
    '''            val cleared = recoveryStore.write(connection.baseUrl, null)
            if (cleared) {
                pendingStartRecovery = null
                startRecoveryUnresolved = false
            } else {
                startRecoveryUnresolved = true
            }
''',
)
replace_once(
    android,
    '''        pendingStartRecovery = authority
        error = "$detail. Start-resultatet er uklart; brug Gendan samme Start i stedet for at lave et nyt preview."
''',
    '''        pendingStartRecovery = authority
        startRecoveryUnresolved = true
        error = "$detail. Start-resultatet er uklart; brug Gendan samme Start i stedet for at lave et nyt preview."
''',
)
replace_once(
    android,
    '''        if (authority == null) {
            if (raw != null) recoveryStore.write(connection.baseUrl, null)
            pendingStartRecovery = null
            error = "Der er ingen gyldig Start-recovery for denne rig."
            return
        }
        pendingStartRecovery = authority
''',
    '''        if (authority == null) {
            pendingStartRecovery = null
            startRecoveryUnresolved = Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(raw)
            error = if (startRecoveryUnresolved) {
                "Start-recovery-recorden kan ikke valideres og er bevaret. Nyt preview forbliver blokeret."
            } else {
                "Der er ingen Start-recovery for denne rig."
            }
            return
        }
        pendingStartRecovery = authority
        startRecoveryUnresolved = true
''',
)
replace_once(android, "        if (pendingStartRecovery != null) return\n", "        if (startRecoveryUnresolved) return\n")
replace_once(
    android,
    '''        pendingStartRecovery = authority
        busy = true
        error = null
        clearPreviewAuthority()
''',
    '''        pendingStartRecovery = authority
        startRecoveryUnresolved = true
        busy = true
        error = null
        clearPreviewAuthority()
''',
)
replace_once(
    android,
    "Button(enabled = canCreatePreview && pendingStartRecovery == null, onClick = { createPreview() })",
    "Button(enabled = canCreatePreview && !startRecoveryUnresolved, onClick = { createPreview() })",
)

desktop = "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Agent3ReviewDevApp.kt"
replace_once(
    desktop,
    '''        var pendingStartRecovery by remember {
            mutableStateOf(
                Agent3ReviewedStartRecoveryAuthority.decode(recoveryStore.read(baseUrl))
            )
        }

        LaunchedEffect(baseUrl) {
            val raw = recoveryStore.read(baseUrl)
            val decoded = Agent3ReviewedStartRecoveryAuthority.decode(raw)
            if (raw != null && decoded == null) {
                recoveryStore.write(baseUrl, null)
                error = "En ugyldig lokal Start-recovery blev ryddet; lav et nyt preview."
            }
            pendingStartRecovery = decoded
        }
''',
    '''        val initialRecoveryRaw = remember(baseUrl) { recoveryStore.read(baseUrl) }
        var pendingStartRecovery by remember(initialRecoveryRaw) {
            mutableStateOf(Agent3ReviewedStartRecoveryAuthority.decode(initialRecoveryRaw))
        }
        var startRecoveryUnresolved by remember(initialRecoveryRaw) {
            mutableStateOf(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(initialRecoveryRaw))
        }

        LaunchedEffect(baseUrl, initialRecoveryRaw) {
            val raw = recoveryStore.read(baseUrl)
            val decoded = Agent3ReviewedStartRecoveryAuthority.decode(raw)
            pendingStartRecovery = decoded
            startRecoveryUnresolved = Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(raw)
            if (startRecoveryUnresolved && decoded == null) {
                error = "Den lokale Start-recovery kan ikke læses sikkert. Nye previews er blokeret; recovery-recorden er bevaret til operatørkontrol."
            }
        }
''',
)
replace_once(
    desktop,
    '''            if (pendingStartRecovery != null) {
                error = "Et tidligere Start har uklart udfald. Gendan samme Start før et nyt preview."
                return
            }
''',
    '''            if (startRecoveryUnresolved) {
                error = if (pendingStartRecovery != null) {
                    "Et tidligere Start har uklart udfald. Gendan samme Start før et nyt preview."
                } else {
                    "En lokal Start-recovery kan ikke valideres. Nyt preview er blokeret, indtil recorden kan afklares sikkert."
                }
                return
            }
''',
)
replace_once(
    desktop,
    '''            if (recoveryStore.write(connection.baseUrl, null)) {
                pendingStartRecovery = null
            } else {
                pendingStartRecovery = authority
                error = "Run blev valideret, men den lokale Start-recovery kunne ikke ryddes. Samme plan kan sikkert gendannes igen."
            }
''',
    '''            if (recoveryStore.write(connection.baseUrl, null)) {
                pendingStartRecovery = null
                startRecoveryUnresolved = false
            } else {
                pendingStartRecovery = authority
                startRecoveryUnresolved = true
                error = "Run blev valideret, men den lokale Start-recovery kunne ikke ryddes. Samme plan kan sikkert gendannes igen."
            }
''',
)
replace_once(
    desktop,
    '''                val cleared = recoveryStore.write(connection.baseUrl, null)
                if (cleared) pendingStartRecovery = null
''',
    '''                val cleared = recoveryStore.write(connection.baseUrl, null)
                if (cleared) {
                    pendingStartRecovery = null
                    startRecoveryUnresolved = false
                } else {
                    startRecoveryUnresolved = true
                }
''',
)
replace_once(
    desktop,
    '''            pendingStartRecovery = authority
            error = "$detail. Start-resultatet er uklart; brug Gendan samme Start i stedet for at lave et nyt preview."
''',
    '''            pendingStartRecovery = authority
            startRecoveryUnresolved = true
            error = "$detail. Start-resultatet er uklart; brug Gendan samme Start i stedet for at lave et nyt preview."
''',
)
replace_once(
    desktop,
    '''            if (authority == null) {
                if (raw != null) recoveryStore.write(connection.baseUrl, null)
                pendingStartRecovery = null
                error = "Der er ingen gyldig Start-recovery for denne rig."
                return
            }
            pendingStartRecovery = authority
''',
    '''            if (authority == null) {
                pendingStartRecovery = null
                startRecoveryUnresolved = Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(raw)
                error = if (startRecoveryUnresolved) {
                    "Start-recovery-recorden kan ikke valideres og er bevaret. Nyt preview forbliver blokeret."
                } else {
                    "Der er ingen Start-recovery for denne rig."
                }
                return
            }
            pendingStartRecovery = authority
            startRecoveryUnresolved = true
''',
)
replace_once(desktop, "            if (pendingStartRecovery != null) return\n", "            if (startRecoveryUnresolved) return\n")
replace_once(
    desktop,
    '''            pendingStartRecovery = authority
            busy = true
            error = null
            clearPreviewAuthority()
''',
    '''            pendingStartRecovery = authority
            startRecoveryUnresolved = true
            busy = true
            error = null
            clearPreviewAuthority()
''',
)
replace_once(
    desktop,
    "Button(enabled = !busy && message.isNotBlank() && pendingStartRecovery == null, onClick = ::createPreview)",
    "Button(enabled = !busy && message.isNotBlank() && !startRecoveryUnresolved, onClick = ::createPreview)",
)

Path("tests/worker_agent3_reviewed_start_reconcile.py").write_text(
    '''from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import Agent3Orchestrator, AgentRun, AgentRunStore, AgentStep, CapabilitySnapshot, RiskClass, RouteKind, RoutePlan, StepState, TurnRequest
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.planner import build_planner_router


class Gate:
    enabled = True
    state_error = None


adapter = V2ToolAdapter(SimpleNamespace(REGISTRY={}, GATE=Gate()))


def stored_plan(plan_store: PlanStore, *, idempotent: bool) -> tuple[str, str]:
    step = AgentStep(tool="recovery_probe", args={}, risk=RiskClass.READ, idempotent=idempotent, summary="recovery probe")
    template = AgentRun(
        request=TurnRequest(message="recover", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[step],
    )
    envelope = {
        "run": template.to_json(),
        "capabilities": asdict(CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)),
        "review_reads": False,
    }
    plan_id, _ = plan_store.save(json.dumps(envelope, sort_keys=True))
    return plan_id, template.to_json()


def client_for(plan_store: PlanStore, run_store: AgentRunStore, executed: list[str]) -> TestClient:
    orchestrator = Agent3Orchestrator(run_store, lambda step: executed.append(step.tool) or {"ok": True})
    app = FastAPI()
    app.include_router(build_planner_router(adapter, SimpleNamespace(), orchestrator=orchestrator, plan_store=plan_store))
    return TestClient(app)


def recover_snapshot(*, executing: bool):
    root = tempfile.mkdtemp(prefix="agent3-reviewed-start-reconcile-")
    plans_path = os.path.join(root, "plans.db")
    runs_path = os.path.join(root, "runs.db")
    first = PlanStore(plans_path, ttl_seconds=30)
    plan_id, template_raw = stored_plan(first, idempotent=not executing)
    run_id = "reserved-executing" if executing else "reserved-pending"
    first.claim_reviewed_start(plan_id, run_id)

    crash_run = AgentRun.from_json(template_raw)
    crash_run.id = run_id
    if executing:
        crash_run.steps[0].state = StepState.EXECUTING
    run_store = AgentRunStore(runs_path)
    run_store.save_with_event(crash_run, "run_created", {"crash_fixture": True})
    first.close()

    second = PlanStore(plans_path, ttl_seconds=30)
    executed: list[str] = []
    response = client_for(second, run_store, executed).post(f"/experimental/agent3/plans/{plan_id}/start")
    assert response.status_code == 200, response.text
    recovery = second.reviewed_start_recovery(plan_id)
    second.close()
    return response.json(), executed, recovery


pending, pending_executed, pending_recovery = recover_snapshot(executing=False)
assert pending["run"]["id"] == "reserved-pending"
assert pending["run"]["state"] == "completed"
assert pending_executed == ["recovery_probe"]
assert pending_recovery is not None and pending_recovery[:2] == ("accepted", "reserved-pending")

interrupted, interrupted_executed, interrupted_recovery = recover_snapshot(executing=True)
assert interrupted["run"]["id"] == "reserved-executing"
assert interrupted["run"]["state"] == "blocked"
assert interrupted["run"]["steps"][0]["state"] == "blocked"
assert "interrupted" in (interrupted["run"]["error"] or "").lower()
assert interrupted_executed == []
assert interrupted_recovery is not None and interrupted_recovery[:2] == ("accepted", "reserved-executing")

print("8 passed, 0 failed")
''',
    encoding="utf-8",
)

Path("android/app/src/test/java/dk/ternedal/modelrig/net/Agent3ReviewedStartRecoverySentinelTest.kt").write_text(
    '''package dk.ternedal.modelrig.net

import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedStartRecoverySentinelTest {
    @Test
    fun unreadableNonEmptyRecordRemainsUnresolved() {
        val raw = "{\\\"schema\\\":\\\"future-or-corrupt\\\"}"
        assertTrue(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(raw))
        assertNull(Agent3ReviewedStartRecoveryAuthority.decode(raw))
    }

    @Test
    fun onlyAbsentOrBlankRecordIsNotUnresolved() {
        assertFalse(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(null))
        assertFalse(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(""))
        assertFalse(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord("   "))
    }
}
''',
    encoding="utf-8",
)

Path("desktop/composeApp/src/test/kotlin/dk/ternedal/modelrig/desktop/net/Agent3ReviewedStartRecoverySentinelTest.kt").write_text(
    '''package dk.ternedal.modelrig.desktop.net

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReviewedStartRecoverySentinelTest {
    @Test
    fun unreadableNonEmptyRecordRemainsUnresolved() {
        val raw = "{\\\"schema\\\":\\\"future-or-corrupt\\\"}"
        assertTrue(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(raw))
        assertNull(Agent3ReviewedStartRecoveryAuthority.decode(raw))
    }

    @Test
    fun onlyAbsentOrBlankRecordIsNotUnresolved() {
        assertFalse(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(null))
        assertFalse(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(""))
        assertFalse(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord("   "))
    }
}
''',
    encoding="utf-8",
)

print("reviewed Start P1 patch staged")
