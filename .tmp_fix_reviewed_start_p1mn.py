from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:120]!r}")
    text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# P1n: durable execution-start watermark outside the rollbackable run payload.
# ---------------------------------------------------------------------------
core = "worker/app/agent3/core.py"
replace_once(
    core,
    '''        self._conn.execute(\n            "CREATE TABLE IF NOT EXISTS agent_events ("\n            "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts REAL NOT NULL, "\n            "kind TEXT NOT NULL, payload TEXT NOT NULL)"\n        )\n        self._conn.commit()\n\n    def save(self, run: AgentRun) -> None:\n''',
    '''        self._conn.execute(\n            "CREATE TABLE IF NOT EXISTS agent_events ("\n            "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ts REAL NOT NULL, "\n            "kind TEXT NOT NULL, payload TEXT NOT NULL)"\n        )\n        self._conn.commit()\n\n        # Execution-start evidence deliberately lives in a separate SQLite file.\n        # A stale/partially-restored agent_runs payload must never be able to roll\n        # this watermark backwards and make a side effect look PENDING again.\n        progress_path = ":memory:" if path == ":memory:" else f"{path}.execution-progress"\n        self._progress_conn = sqlite3.connect(progress_path, check_same_thread=False)\n        self._progress_conn.execute(\n            "CREATE TABLE IF NOT EXISTS agent_execution_starts ("\n            "run_id TEXT NOT NULL, step_index INTEGER NOT NULL, step_sha256 TEXT NOT NULL, "\n            "started_at REAL NOT NULL, "\n            "PRIMARY KEY(run_id,step_index,step_sha256))"\n        )\n        self._progress_conn.commit()\n\n    @staticmethod\n    def _execution_step_sha256(step: AgentStep) -> str:\n        payload = {\n            "tool": step.tool,\n            "args": step.args,\n            "risk": step.risk.value,\n            "sensitivity": step.sensitivity.value,\n            "egress": step.egress.value,\n            "origin": step.origin,\n            "conversation_id": step.conversation_id,\n            "idempotent": step.idempotent,\n        }\n        raw = json.dumps(\n            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")\n        ).encode("utf-8")\n        return hashlib.sha256(raw).hexdigest()\n\n    def _record_execution_start(self, run: AgentRun) -> None:\n        if run.current_step < 0 or run.current_step >= len(run.steps):\n            raise ValueError("cannot watermark an execution without a current step")\n        step = run.steps[run.current_step]\n        digest = self._execution_step_sha256(step)\n        with self._lock:\n            try:\n                self._progress_conn.execute(\n                    "INSERT OR IGNORE INTO agent_execution_starts("\n                    "run_id,step_index,step_sha256,started_at) VALUES(?,?,?,?)",\n                    (run.id, run.current_step, digest, time.time()),\n                )\n                self._progress_conn.commit()\n            except Exception:\n                self._progress_conn.rollback()\n                raise\n\n    def execution_progress_matches(self, run: AgentRun) -> bool:\n        """Fail closed when durable execution evidence is ahead of a run payload.\n\n        The marker is written after the EXECUTING run CAS but before the executor\n        is called. A crash before the marker therefore executes nothing; a marker\n        always means the step was allowed to cross the execution boundary.\n        Replaying a PENDING step is allowed only when the reviewed plan itself\n        declared that step idempotent.\n        """\n        with self._lock:\n            rows = self._progress_conn.execute(\n                "SELECT step_index,step_sha256 FROM agent_execution_starts "\n                "WHERE run_id=? ORDER BY step_index ASC",\n                (run.id,),\n            ).fetchall()\n        for step_index, expected_sha in rows:\n            if step_index < 0 or step_index >= len(run.steps):\n                return False\n            step = run.steps[step_index]\n            if self._execution_step_sha256(step) != expected_sha:\n                return False\n            if run.current_step < step_index:\n                return False\n            if run.current_step == step_index:\n                if step.state in {StepState.APPROVED, StepState.WAITING_CONFIRMATION}:\n                    return False\n                if step.state == StepState.PENDING and not step.idempotent:\n                    return False\n        return True\n\n    def save(self, run: AgentRun) -> None:\n''',
)

replace_once(
    core,
    '''                self._conn.execute(\n                    "INSERT INTO agent_events(run_id,ts,kind,payload) VALUES(?,?,?,?)",\n                    (run.id, time.time(), kind, encoded[:8000]),\n                )\n                self._conn.commit()\n                return True\n            except Exception:\n                self._conn.rollback()\n                raise\n\n    def save_if_unchanged(\n''',
    '''                self._conn.execute(\n                    "INSERT INTO agent_events(run_id,ts,kind,payload) VALUES(?,?,?,?)",\n                    (run.id, time.time(), kind, encoded[:8000]),\n                )\n                self._conn.commit()\n                if kind == "step_started":\n                    # Do not let the executor run until the independent, monotonic\n                    # execution watermark is durable. If this write fails, the run\n                    # stays EXECUTING and recovery blocks/replays by existing rules.\n                    self._record_execution_start(run)\n                return True\n            except Exception:\n                self._conn.rollback()\n                raise\n\n    def save_if_unchanged(\n''',
)

planner = "worker/app/agent3/planner.py"
replace_once(
    planner,
    '''        if (\n            agent_run_plan_sha256(existing) != agent_run_plan_sha256(reviewed_template)\n            or existing.proactive != reviewed_template.proactive\n            or existing.allow_private_cloud != reviewed_template.allow_private_cloud\n        ):\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "persisted reviewed Start run does not match the reviewed plan",\n                status_code=503,\n            )\n\n    def _reconcile_reviewed_start_run(\n''',
    '''        if (\n            agent_run_plan_sha256(existing) != agent_run_plan_sha256(reviewed_template)\n            or existing.proactive != reviewed_template.proactive\n            or existing.allow_private_cloud != reviewed_template.allow_private_cloud\n        ):\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "persisted reviewed Start run does not match the reviewed plan",\n                status_code=503,\n            )\n        if not orchestrator.store.execution_progress_matches(existing):\n            raise _reviewed_start_error(\n                "reviewed_start_pending",\n                "persisted reviewed Start execution progress moved backwards",\n                status_code=503,\n            )\n\n    def _reconcile_reviewed_start_run(\n''',
)

# ---------------------------------------------------------------------------
# P1m: atomic local recovery-slot reservation and compare-and-clear.
# ---------------------------------------------------------------------------
desktop_db = "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/data/DesktopChatDb.kt"
replace_once(
    desktop_db,
    '''    private fun putRawSetting(key: String, value: String) {\n        conn.prepareStatement(\n            "INSERT INTO setting(key, value) VALUES(?, ?) " +\n                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",\n        ).use { st ->\n            st.setString(1, key); st.setString(2, value); st.executeUpdate()\n        }\n    }\n\n    override fun close() {\n''',
    '''    private fun putRawSetting(key: String, value: String) {\n        conn.prepareStatement(\n            "INSERT INTO setting(key, value) VALUES(?, ?) " +\n                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",\n        ).use { st ->\n            st.setString(1, key); st.setString(2, value); st.executeUpdate()\n        }\n    }\n\n    internal fun putRawSettingIfAbsent(key: String, value: String): Boolean =\n        conn.prepareStatement(\n            "INSERT OR IGNORE INTO setting(key, value) VALUES(?, ?)",\n        ).use { st ->\n            st.setString(1, key)\n            st.setString(2, value)\n            st.executeUpdate() == 1\n        }\n\n    internal fun removeRawSettingIfValue(key: String, expectedValue: String): Boolean =\n        conn.prepareStatement(\n            "DELETE FROM setting WHERE key=? AND value=?",\n        ).use { st ->\n            st.setString(1, key)\n            st.setString(2, expectedValue)\n            st.executeUpdate() == 1\n        }\n\n    override fun close() {\n''',
)

desktop_store = "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/data/Agent3ReviewedStartRecoveryStore.kt"
Path(desktop_store).write_text(
    '''package dk.ternedal.modelrig.desktop.data\n\n/** Separate URL-scoped persistence for reviewed Start; task-surface authority is never reused. */\nclass Agent3ReviewedStartRecoveryStore(private val db: DesktopChatDb) {\n    fun read(baseUrl: String?): String? = agent3ReviewedStartRecoveryStorageKey(baseUrl)\n        ?.let(db::getSetting)\n        ?.trim()\n        ?.takeIf { it.isNotEmpty() }\n\n    /** Reserve an empty rig-scoped slot. Existing authority is never overwritten. */\n    fun reserve(baseUrl: String?, encodedAuthority: String?): Boolean {\n        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false\n        val normalized = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false\n        return runCatching { db.putRawSettingIfAbsent(key, normalized) }.getOrDefault(false)\n    }\n\n    /** Clear only the exact authority that originated this completion. */\n    fun clearIfMatches(baseUrl: String?, encodedAuthority: String?): Boolean {\n        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false\n        val expected = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false\n        return runCatching { db.removeRawSettingIfValue(key, expected) }.getOrDefault(false)\n    }\n}\n\ninternal fun agent3ReviewedStartRecoveryStorageKey(baseUrl: String?): String? =\n    baseUrl\n        ?.trim()\n        ?.trimEnd('/')\n        ?.takeIf { it.isNotEmpty() }\n        ?.let { "$REVIEWED_START_RECOVERY_KEY_PREFIX:$it" }\n\nprivate const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3ReviewedStartRecovery"\n''',
    encoding="utf-8",
)

android_store = "android/app/src/main/java/dk/ternedal/modelrig/data/Agent3ReviewedStartRecoveryStore.kt"
Path(android_store).write_text(
    '''package dk.ternedal.modelrig.data\n\nimport android.content.Context\n\n/** URL-scoped storage for the opaque reviewed-Start recovery authority record. */\nclass Agent3ReviewedStartRecoveryStore(context: Context) {\n    private val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)\n\n    fun read(baseUrl: String?): String? = agent3ReviewedStartRecoveryStorageKey(baseUrl)\n        ?.let { prefs.getString(it, null) }\n        ?.trim()\n        ?.takeIf { it.isNotEmpty() }\n\n    /** Reserve an empty slot atomically across concurrent screen/store instances. */\n    fun reserve(baseUrl: String?, encodedAuthority: String?): Boolean {\n        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false\n        val normalized = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false\n        synchronized(slotLock) {\n            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }\n            if (current != null) return false\n            return prefs.edit().putString(key, normalized).commit()\n        }\n    }\n\n    /** Clear only the exact authority that originated this completion. */\n    fun clearIfMatches(baseUrl: String?, encodedAuthority: String?): Boolean {\n        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false\n        val expected = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false\n        synchronized(slotLock) {\n            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }\n            if (current != expected) return false\n            return prefs.edit().remove(key).commit()\n        }\n    }\n\n    private companion object {\n        val slotLock = Any()\n    }\n}\n\ninternal fun agent3ReviewedStartRecoveryStorageKey(baseUrl: String?): String? =\n    baseUrl\n        ?.trim()\n        ?.trimEnd('/')\n        ?.takeIf { it.isNotEmpty() }\n        ?.let { "$REVIEWED_START_RECOVERY_KEY_PREFIX:$it" }\n\nprivate const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3_reviewed_start_recovery"\n''',
    encoding="utf-8",
)

for ui_path in [
    "android/app/src/main/java/dk/ternedal/modelrig/ui/Agent3ReviewScreen.kt",
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Agent3ReviewDevApp.kt",
]:
    p = Path(ui_path)
    text = p.read_text(encoding="utf-8")
    text = text.replace(
        "recoveryStore.write(connection.baseUrl, authority.encode())",
        "recoveryStore.reserve(connection.baseUrl, authority.encode())",
    )
    text = text.replace(
        "recoveryStore.write(connection.baseUrl, null)",
        "recoveryStore.clearIfMatches(connection.baseUrl, authority.encode())",
    )
    if "recoveryStore.write(" in text:
        raise SystemExit(f"unsafe reviewed-start recovery write remains in {ui_path}")
    p.write_text(text, encoding="utf-8")

# Persistence regressions: second authority cannot overwrite, and completion can
# clear only its own exact slot.
Path("desktop/composeApp/src/test/kotlin/dk/ternedal/modelrig/desktop/data/Agent3ReviewedStartRecoveryPersistenceTest.kt").write_text(
    '''package dk.ternedal.modelrig.desktop.data\n\nimport java.nio.file.Files\nimport kotlin.test.Test\nimport kotlin.test.assertEquals\nimport kotlin.test.assertFalse\nimport kotlin.test.assertNull\nimport kotlin.test.assertTrue\n\nclass Agent3ReviewedStartRecoveryPersistenceTest {\n    private object TestProtector : CredentialProtector {\n        override fun protect(plaintext: String): String = "test:$plaintext"\n        override fun unprotect(envelope: String): String = envelope.removePrefix("test:")\n        override fun isProtected(value: String): Boolean = value.startsWith("test:")\n    }\n\n    @Test\n    fun authorityReservationIsCrossConnectionCasAndRigScoped() {\n        val dbPath = Files.createTempFile("modelrig-reviewed-start-", ".db").toString()\n        val rigA = "https://rig-a.example:8443/"\n        val rigB = "https://rig-b.example:8443"\n        val first = "{\\\"schema\\\":\\\"authority-a\\\"}"\n        val second = "{\\\"schema\\\":\\\"authority-b\\\"}"\n\n        DesktopChatDb(dbPath, TestProtector).use { dbA ->\n            DesktopChatDb(dbPath, TestProtector).use { dbB ->\n                val storeA = Agent3ReviewedStartRecoveryStore(dbA)\n                val storeB = Agent3ReviewedStartRecoveryStore(dbB)\n                assertTrue(storeA.reserve(rigA, first))\n                assertFalse(storeB.reserve(rigA, second))\n                assertEquals(first, storeB.read("https://rig-a.example:8443"))\n                assertFalse(storeB.clearIfMatches(rigA, second))\n                assertEquals(first, storeA.read(rigA))\n                assertNull(storeA.read(rigB))\n                assertTrue(storeA.clearIfMatches(rigA, first))\n                assertNull(storeB.read(rigA))\n            }\n        }\n    }\n}\n''',
    encoding="utf-8",
)

Path("android/app/src/test/java/dk/ternedal/modelrig/data/Agent3ReviewedStartRecoveryPersistenceTest.kt").write_text(
    '''package dk.ternedal.modelrig.data\n\nimport android.content.Context\nimport org.junit.Assert.assertEquals\nimport org.junit.Assert.assertFalse\nimport org.junit.Assert.assertNull\nimport org.junit.Assert.assertTrue\nimport org.junit.Before\nimport org.junit.Test\nimport org.junit.runner.RunWith\nimport org.robolectric.RobolectricTestRunner\nimport org.robolectric.RuntimeEnvironment\n\n@RunWith(RobolectricTestRunner::class)\nclass Agent3ReviewedStartRecoveryPersistenceTest {\n    private lateinit var context: Context\n\n    @Before\n    fun resetPreferences() {\n        context = RuntimeEnvironment.getApplication().applicationContext\n        context.getSharedPreferences("modelrig", Context.MODE_PRIVATE).edit().clear().commit()\n    }\n\n    @Test\n    fun `authority reservation is compare-and-set across store instances`() {\n        val rigA = "https://rig-a.example:8443/"\n        val rigB = "https://rig-b.example:8443"\n        val first = "{\\\"schema\\\":\\\"authority-a\\\"}"\n        val second = "{\\\"schema\\\":\\\"authority-b\\\"}"\n\n        val storeA = Agent3ReviewedStartRecoveryStore(context)\n        val storeB = Agent3ReviewedStartRecoveryStore(context)\n        assertTrue(storeA.reserve(rigA, first))\n        assertFalse(storeB.reserve(rigA, second))\n        assertEquals(first, storeB.read("https://rig-a.example:8443"))\n        assertFalse(storeB.clearIfMatches(rigA, second))\n        assertEquals(first, storeA.read(rigA))\n        assertNull(storeA.read(rigB))\n        assertTrue(storeA.clearIfMatches(rigA, first))\n        assertNull(storeB.read(rigA))\n    }\n}\n''',
    encoding="utf-8",
)

# Keep the simple key tests compiling against the narrower CAS API; they do not
# need changes. Add a focused worker regression for rollback-after-side-effect.
Path("tests/worker_agent3_reviewed_start_p1m.py").write_text(
    r'''from __future__ import annotations

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
    StepState,
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


def template_run() -> AgentRun:
    return AgentRun(
        request=TurnRequest(message="do once", mode="rig", tools=True),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False),
        steps=[
            AgentStep(
                tool="non_idempotent_once",
                args={"value": 1},
                risk=RiskClass.READ,
                idempotent=False,
                summary="do once",
            )
        ],
    )


def payload() -> str:
    return json.dumps(
        {
            "run": template_run().to_json(),
            "capabilities": asdict(
                CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True)
            ),
            "review_reads": False,
        },
        sort_keys=True,
    )


def app_for(plans: PlanStore, runs: AgentRunStore, reviews: ReadReviewStore, executed: list[str]) -> FastAPI:
    orchestrator = ReviewingAgent3Orchestrator(
        runs,
        lambda step: executed.append(step.tool) or {"side_effect": "duplicate"},
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


def stale_run_payload_cannot_replay_started_non_idempotent_step(root: str) -> None:
    plans_path = os.path.join(root, "plans.db")
    old_plans = PlanStore(plans_path, ttl_seconds=30)
    plan_id, _ = old_plans.save(payload())
    run_id = "rollback-run"
    old_plans.claim_reviewed_start(plan_id, run_id)
    old_owner = old_plans.start_owner
    old_plans.close()

    runs = AgentRunStore(os.path.join(root, "runs.db"))
    run = template_run()
    run.id = run_id
    runs.save_with_event(run, "run_created", {})
    stale_payload = run.to_json()

    expected = run.to_json()
    run.steps[0].state = StepState.EXECUTING
    assert runs.save_with_event_if_unchanged(
        run,
        expected_state=RunState.RUNNING,
        expected_payload=expected,
        kind="step_started",
        payload={"step_id": run.steps[0].id, "tool": run.steps[0].tool},
    )
    execution_payload = run.to_json()
    run.steps[0].state = StepState.SUCCEEDED
    run.steps[0].result = {"side_effect": "happened"}
    assert runs.save_with_event_if_unchanged(
        run,
        expected_state=RunState.RUNNING,
        expected_payload=execution_payload,
        kind="step_succeeded",
        payload={"step_id": run.steps[0].id, "tool": run.steps[0].tool},
    )

    # Simulate a partial restore/corruption of the rollbackable run payload only.
    # The independent execution-progress DB is intentionally left untouched.
    with runs._lock:
        runs._conn.execute(
            "UPDATE agent_runs SET state=?,payload=? WHERE id=?",
            (RunState.RUNNING.value, stale_payload, run_id),
        )
        runs._conn.commit()

    restored = runs.load(run_id)
    assert restored is not None
    assert restored.current_step == 0
    assert restored.steps[0].state is StepState.PENDING
    assert not runs.execution_progress_matches(restored)

    reviews = ReadReviewStore(os.path.join(root, "reviews.db"))
    reviews.configure(run_id, False)
    plans = PlanStore(plans_path, ttl_seconds=30)
    executed: list[str] = []
    response = TestClient(app_for(plans, runs, reviews, executed)).post(
        f"/experimental/agent3/plans/{plan_id}/start"
    )
    assert response.status_code == 503, response.text
    assert response.headers.get("X-ModelRig-Agent3-Reason") == "reviewed_start_pending"
    assert executed == []
    recovery = plans.reviewed_start_recovery(plan_id)
    assert recovery == ("pending", run_id, plans.start_owner)
    persisted = runs.load(run_id)
    assert persisted is not None and persisted.steps[0].state is StepState.PENDING
    plans.close()


def idempotent_pending_replay_remains_allowed(root: str) -> None:
    runs = AgentRunStore(os.path.join(root, "idempotent-runs.db"))
    run = template_run()
    run.id = "idempotent-run"
    run.steps[0].idempotent = True
    runs.save_with_event(run, "run_created", {})
    stale_payload = run.to_json()
    expected = run.to_json()
    run.steps[0].state = StepState.EXECUTING
    assert runs.save_with_event_if_unchanged(
        run,
        expected_state=RunState.RUNNING,
        expected_payload=expected,
        kind="step_started",
        payload={"step_id": run.steps[0].id},
    )
    with runs._lock:
        runs._conn.execute(
            "UPDATE agent_runs SET state=?,payload=? WHERE id=?",
            (RunState.RUNNING.value, stale_payload, run.id),
        )
        runs._conn.commit()
    restored = runs.load(run.id)
    assert restored is not None and restored.steps[0].state is StepState.PENDING
    assert runs.execution_progress_matches(restored)


root = tempfile.mkdtemp(prefix="agent3-reviewed-start-p1m-")
stale_run_payload_cannot_replay_started_non_idempotent_step(root)
idempotent_pending_replay_remains_allowed(root)
print("P1m/P1n: recovery-slot/progress authority regressions passed")
''',
    encoding="utf-8",
)

print("applied reviewed Start P1m/P1n fixes")
