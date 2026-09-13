from pathlib import Path

# 1) Desktop: reviewed-Start completion may update shared UI recovery state only
# for the same URL-scoped rig that issued the request.
policy_path = Path("desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Agent3DevInteractionPolicy.kt")
policy = policy_path.read_text(encoding="utf-8")
old = '''    fun canPublishPreview(\n        requestIntent: Agent3DevPreviewIntent?,\n        currentIntent: Agent3DevPreviewIntent?,\n    ): Boolean = requestIntent != null && requestIntent == currentIntent\n\n    fun canStart(\n'''
new = '''    fun canPublishPreview(\n        requestIntent: Agent3DevPreviewIntent?,\n        currentIntent: Agent3DevPreviewIntent?,\n    ): Boolean = requestIntent != null && requestIntent == currentIntent\n\n    fun canPublishReviewedStartCompletion(\n        currentConnection: Agent3DevConnectionBinding?,\n        requestConnection: Agent3DevConnectionBinding,\n    ): Boolean = currentConnection?.baseUrl == requestConnection.baseUrl\n\n    fun canStart(\n'''
if old not in policy:
    raise SystemExit("missing Agent3DevInteractionPolicy insertion anchor")
policy = policy.replace(old, new, 1)
policy_path.write_text(policy, encoding="utf-8")

policy_test_path = Path("desktop/composeApp/src/test/kotlin/dk/ternedal/modelrig/desktop/Agent3DevInteractionPolicyTest.kt")
policy_test = policy_test_path.read_text(encoding="utf-8")
old = '''    @Test fun equivalentConnectionMatchesButUrlOrTokenDriftDoesNot() {\n        assertEquals(connection, binding(" http://rig-a:8080/ ", " token-a "))\n        assertFalse(connection == binding("http://rig-b:8080", "token-a"))\n        assertFalse(connection == binding("http://rig-a:8080", "token-b"))\n    }\n\n    @Test fun previewIntentNormalizesExactPlannerInputs() {\n'''
new = '''    @Test fun equivalentConnectionMatchesButUrlOrTokenDriftDoesNot() {\n        assertEquals(connection, binding(" http://rig-a:8080/ ", " token-a "))\n        assertFalse(connection == binding("http://rig-b:8080", "token-a"))\n        assertFalse(connection == binding("http://rig-a:8080", "token-b"))\n    }\n\n    @Test fun reviewedStartCompletionPublishesOnlyIntoSameUrlScopedRecoveryState() {\n        assertTrue(\n            Agent3DevInteractionPolicy.canPublishReviewedStartCompletion(\n                binding(" http://rig-a:8080/ ", "new-token"), connection\n            )\n        )\n        assertFalse(\n            Agent3DevInteractionPolicy.canPublishReviewedStartCompletion(\n                binding("http://rig-b:8080", "token-a"), connection\n            )\n        )\n        assertFalse(Agent3DevInteractionPolicy.canPublishReviewedStartCompletion(null, connection))\n    }\n\n    @Test fun previewIntentNormalizesExactPlannerInputs() {\n'''
if old not in policy_test:
    raise SystemExit("missing desktop policy test insertion anchor")
policy_test = policy_test.replace(old, new, 1)
policy_test_path.write_text(policy_test, encoding="utf-8")

app_path = Path("desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Agent3ReviewDevApp.kt")
app = app_path.read_text(encoding="utf-8")
old = '''        fun publishReviewedStart(\n            envelope: dk.ternedal.modelrig.desktop.net.Agent3RunEnvelope,\n            connection: Agent3DevConnectionBinding,\n            authority: Agent3ReviewedStartRecoveryAuthority,\n        ) {\n            run = envelope.run\n            review = envelope.readReview\n            if (recoveryStore.write(connection.baseUrl, null)) {\n                pendingStartRecovery = null\n                startRecoveryUnresolved = false\n            } else {\n                pendingStartRecovery = authority\n                startRecoveryUnresolved = true\n                error = "Run blev valideret, men den lokale Start-recovery kunne ikke ryddes. Samme plan kan sikkert gendannes igen."\n            }\n        }\n\n        fun publishReviewedStartFailure(\n            failure: Throwable,\n            connection: Agent3DevConnectionBinding,\n            authority: Agent3ReviewedStartRecoveryAuthority,\n        ) {\n            val detail = failure.message ?: "Planen kunne ikke startes"\n            if (!shouldRetainReviewedStartRecovery(failure)) {\n                val cleared = recoveryStore.write(connection.baseUrl, null)\n                if (cleared) {\n                    pendingStartRecovery = null\n                    startRecoveryUnresolved = false\n                } else {\n                    startRecoveryUnresolved = true\n                }\n                error = if (cleared) {\n                    "$detail. Serveren afviste Start definitivt; lav et nyt preview."\n                } else {\n                    "$detail. Serveren afviste Start definitivt, men lokal recovery kunne ikke ryddes."\n                }\n                return\n            }\n            pendingStartRecovery = authority\n            startRecoveryUnresolved = true\n            error = "$detail. Start-resultatet er uklart; brug Gendan samme Start i stedet for at lave et nyt preview."\n        }\n'''
new = '''        fun publishReviewedStart(\n            envelope: dk.ternedal.modelrig.desktop.net.Agent3RunEnvelope,\n            connection: Agent3DevConnectionBinding,\n            authority: Agent3ReviewedStartRecoveryAuthority,\n        ) {\n            // Resolve the durable authority in the URL scope that issued this\n            // request even if the operator has since navigated to another rig.\n            // Never publish that stale completion into the new rig's shared UI\n            // state, where it could clear an unrelated unresolved Start.\n            val cleared = recoveryStore.write(connection.baseUrl, null)\n            val current = Agent3DevConnectionBinding.capture(baseUrl, token)\n            if (!Agent3DevInteractionPolicy.canPublishReviewedStartCompletion(current, connection)) {\n                return\n            }\n            run = envelope.run\n            review = envelope.readReview\n            if (cleared) {\n                pendingStartRecovery = null\n                startRecoveryUnresolved = false\n            } else {\n                pendingStartRecovery = authority\n                startRecoveryUnresolved = true\n                error = "Run blev valideret, men den lokale Start-recovery kunne ikke ryddes. Samme plan kan sikkert gendannes igen."\n            }\n        }\n\n        fun publishReviewedStartFailure(\n            failure: Throwable,\n            connection: Agent3DevConnectionBinding,\n            authority: Agent3ReviewedStartRecoveryAuthority,\n        ) {\n            val detail = failure.message ?: "Planen kunne ikke startes"\n            if (!shouldRetainReviewedStartRecovery(failure)) {\n                val cleared = recoveryStore.write(connection.baseUrl, null)\n                val current = Agent3DevConnectionBinding.capture(baseUrl, token)\n                if (!Agent3DevInteractionPolicy.canPublishReviewedStartCompletion(current, connection)) {\n                    return\n                }\n                if (cleared) {\n                    pendingStartRecovery = null\n                    startRecoveryUnresolved = false\n                } else {\n                    startRecoveryUnresolved = true\n                }\n                error = if (cleared) {\n                    "$detail. Serveren afviste Start definitivt; lav et nyt preview."\n                } else {\n                    "$detail. Serveren afviste Start definitivt, men lokal recovery kunne ikke ryddes."\n                }\n                return\n            }\n            val current = Agent3DevConnectionBinding.capture(baseUrl, token)\n            if (!Agent3DevInteractionPolicy.canPublishReviewedStartCompletion(current, connection)) {\n                return\n            }\n            pendingStartRecovery = authority\n            startRecoveryUnresolved = true\n            error = "$detail. Start-resultatet er uklart; brug Gendan samme Start i stedet for at lave et nyt preview."\n        }\n'''
if old not in app:
    raise SystemExit("missing desktop reviewed Start publication block")
app = app.replace(old, new, 1)
app_path.write_text(app, encoding="utf-8")

# 2) Worker: the row key and the embedded AgentRun.id are both authority.
planner_path = Path("worker/app/agent3/planner.py")
planner = planner_path.read_text(encoding="utf-8")
old = '''    def _assert_reviewed_run_identity(existing: AgentRun, reviewed_template: AgentRun) -> None:\n'''
new = '''    def _assert_reserved_run_binding(existing: AgentRun, reserved_run_id: str) -> None:\n        if existing.id != reserved_run_id:\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "persisted reviewed Start payload has the wrong reserved run id",\n                status_code=503,\n            )\n\n    def _assert_reviewed_run_identity(existing: AgentRun, reviewed_template: AgentRun) -> None:\n'''
if old not in planner:
    raise SystemExit("missing planner identity helper anchor")
planner = planner.replace(old, new, 1)

old = '''        if existing is None:\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "persisted reviewed Start run is not yet materialized",\n                status_code=503,\n            )\n        # Only RUNNING snapshots can be advanced. BLOCKED is terminal authority\n'''
new = '''        if existing is None:\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "persisted reviewed Start run is not yet materialized",\n                status_code=503,\n            )\n        _assert_reserved_run_binding(existing, run_id)\n        # Only RUNNING snapshots can be advanced. BLOCKED is terminal authority\n'''
if old not in planner:
    raise SystemExit("missing reconcile run-binding anchor")
planner = planner.replace(old, new, 1)

old = '''                    if existing is None:\n                        raise _reviewed_start_error(\n                            "reviewed_start_pending",\n                            "accepted reviewed Start lost its bound run during recovery",\n                            status_code=503,\n                        )\n                    # Accepted replay is observation-only, but any state that\n'''
new = '''                    if existing is None:\n                        raise _reviewed_start_error(\n                            "reviewed_start_pending",\n                            "accepted reviewed Start lost its bound run during recovery",\n                            status_code=503,\n                        )\n                    _assert_reserved_run_binding(existing, reserved_run_id)\n                    # Accepted replay is observation-only, but any state that\n'''
if old not in planner:
    raise SystemExit("missing accepted run-binding anchor")
planner = planner.replace(old, new, 1)

old = '''            if existing is None:\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "pending reviewed Start is missing its bound run; recovery remains ambiguous",\n                    status_code=503,\n                )\n\n            if owner == plan_store.start_owner:\n'''
new = '''            if existing is None:\n                raise _reviewed_start_error(\n                    "reviewed_start_pending",\n                    "pending reviewed Start is missing its bound run; recovery remains ambiguous",\n                    status_code=503,\n                )\n            _assert_reserved_run_binding(existing, reserved_run_id)\n\n            if owner == plan_store.start_owner:\n'''
if old not in planner:
    raise SystemExit("missing pending run-binding anchor")
planner = planner.replace(old, new, 1)
planner_path.write_text(planner, encoding="utf-8")

# 3) Regression for both accepted replay and pending recovery with a row-key /
# embedded-id mismatch. The canonical plan digest intentionally excludes ids, so
# these tests prove the explicit reserved-run binding rather than digest behavior.
test_path = Path("tests/worker_agent3_reviewed_start_p1n.py")
if test_path.exists():
    raise SystemExit("P1n regression already exists")
test_path.write_text(r'''from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import (
    AgentRun,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    RiskClass,
    RouteKind,
    RoutePlan,
    RunState,
    TurnRequest,
)
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.planner import build_planner_router
from app.agent3.review_orchestrator import ReadReviewStore, ReviewingAgent3Orchestrator


class Gate:
    enabled = True
    state_error = None


adapter = V2ToolAdapter(SimpleNamespace(REGISTRY={}, GATE=Gate()))


def template() -> AgentRun:
    return AgentRun(
        request=TurnRequest(message="reserved run binding", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[
            AgentStep(
                tool="read_one",
                args={"scope": "reviewed"},
                risk=RiskClass.READ,
                idempotent=True,
                summary="read one",
            )
        ],
    )


def payload(run: AgentRun) -> str:
    return json.dumps(
        {
            "run": run.to_json(),
            "capabilities": asdict(
                CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)
            ),
            "review_reads": False,
        },
        sort_keys=True,
    )


def corrupt_embedded_id(runs: AgentRunStore, reserved_run_id: str, wrong_id: str) -> None:
    current = runs.load(reserved_run_id)
    assert current is not None
    current.id = wrong_id
    with runs._lock:
        runs._conn.execute(
            "UPDATE agent_runs SET payload=? WHERE id=?",
            (current.to_json(), reserved_run_id),
        )
        runs._conn.commit()
    reloaded = runs.load(reserved_run_id)
    assert reloaded is not None and reloaded.id == wrong_id


def app_for(plans: PlanStore, runs: AgentRunStore, reviews: ReadReviewStore, executed: list[str]) -> FastAPI:
    orchestrator = ReviewingAgent3Orchestrator(
        runs,
        lambda step: executed.append(step.tool) or {"ok": True},
        reviews,
    )
    app = FastAPI()
    app.include_router(
        build_planner_router(
            adapter,
            SimpleNamespace(),
            orchestrator=orchestrator,
            plan_store=plans,
        )
    )
    return app


def accepted_wrong_embedded_id_fails_closed(root: str) -> None:
    plans = PlanStore(os.path.join(root, "accepted-plans.db"), ttl_seconds=30)
    reviewed = template()
    plan_id, _ = plans.save(payload(reviewed))
    reserved = "accepted-reserved-run"
    plans.claim_reviewed_start(plan_id, reserved)
    plans.mark_reviewed_start_accepted(plan_id, reserved)

    runs = AgentRunStore(os.path.join(root, "accepted-runs.db"))
    materialized = AgentRun.from_json(reviewed.to_json())
    materialized.id = reserved
    materialized.state = RunState.RUNNING
    runs.save_with_event(materialized, "run_created", {})
    corrupt_embedded_id(runs, reserved, "accepted-other-run")
    reviews = ReadReviewStore(os.path.join(root, "accepted-reviews.db"))
    reviews.configure(reserved, False)
    executed: list[str] = []

    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    assert plans.reviewed_start_recovery(plan_id)[0] == "accepted"
    assert runs.load(reserved).id == "accepted-other-run"
    plans.close()


def pending_wrong_embedded_id_fails_closed_before_recovery_claim(root: str) -> None:
    plan_path = os.path.join(root, "pending-plans.db")
    seed = PlanStore(plan_path, ttl_seconds=30)
    reviewed = template()
    plan_id, _ = seed.save(payload(reviewed))
    reserved = "pending-reserved-run"
    seed.claim_reviewed_start(plan_id, reserved)
    old_owner = seed.reviewed_start_recovery(plan_id)[2]
    seed.close()

    # Reopening creates a fresh worker generation so this is a real recovery path.
    plans = PlanStore(plan_path, ttl_seconds=30)
    assert plans.start_owner != old_owner
    runs = AgentRunStore(os.path.join(root, "pending-runs.db"))
    materialized = AgentRun.from_json(reviewed.to_json())
    materialized.id = reserved
    materialized.state = RunState.RUNNING
    runs.save_with_event(materialized, "run_created", {})
    corrupt_embedded_id(runs, reserved, "pending-other-run")
    reviews = ReadReviewStore(os.path.join(root, "pending-reviews.db"))
    reviews.configure(reserved, False)
    executed: list[str] = []

    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    state, run_id, owner = plans.reviewed_start_recovery(plan_id)
    assert state == "pending" and run_id == reserved
    # Fail before taking recovery authority for the mismatched payload.
    assert owner == old_owner
    assert runs.load(reserved).id == "pending-other-run"
    plans.close()


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1n-")
accepted_wrong_embedded_id_fails_closed(root)
pending_wrong_embedded_id_fails_closed_before_recovery_claim(root)
print("P1n: URL-scoped desktop publication + reserved run-id binding regressions passed")
''', encoding="utf-8")

print("applied P1n stale-desktop-completion and reserved-run binding fix")
