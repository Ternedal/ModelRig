package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControlCenterSchedulesClientTest {
    @Test
    fun snapshotUsesOnlyExistingAuthenticatedGetRoutes() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(runtimePayload().toString()))
        server.enqueue(jsonResponse(scheduleListPayload().toString()))
        server.start()
        try {
            val snapshot = ControlCenterSchedulesClient(
                server.url("/").toString(),
                "paired-token",
            ).snapshot()

            assertTrue(snapshot.runtime.configured)
            assertTrue(snapshot.runtime.running)
            assertEquals(1, snapshot.runtime.maxConcurrency)
            assertEquals(0, snapshot.runtime.queueCapacity)
            assertEquals(1, snapshot.schedules.size)
            val schedule = snapshot.schedules.single()
            assertEquals("0a1b2c3d4e5f", schedule.id)
            assertEquals("note_append", schedule.tool)
            assertEquals(2, schedule.runsUsed)
            assertEquals(5, schedule.maxRuns)
            assertTrue(schedule.structurallyEligible)
            assertFalse(schedule.budgetExhausted)

            val statusRequest = server.takeRequest()
            assertEquals("GET", statusRequest.method)
            assertEquals("/api/v1/schedules/status", statusRequest.path)
            assertEquals("Bearer paired-token", statusRequest.getHeader("Authorization"))
            val listRequest = server.takeRequest()
            assertEquals("GET", listRequest.method)
            assertEquals("/api/v1/schedules", listRequest.path)
            assertEquals("Bearer paired-token", listRequest.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun runtimeRejectsTypeAndStateContradictions() {
        val client = client()

        assertInvalidRuntime(
            client,
            runtimePayload().put("running", "true"),
            "running must be boolean",
        )
        assertInvalidRuntime(
            client,
            runtimePayload().put("configured", false).put("running", true),
            "running runtime is not configured",
        )
        assertInvalidRuntime(
            client,
            runtimePayload().put("active_executions", 2).put("max_concurrency", 1),
            "active executions exceed max concurrency",
        )
        assertInvalidRuntime(
            client,
            runtimePayload().put("accepted_ticks", -1),
            "accepted_ticks must be non-negative",
        )
    }

    @Test
    fun grantsRejectBudgetEligibilityAndRuntimeGateContradictions() {
        val client = client()

        val impossibleBudget = scheduleListPayload()
        impossibleBudget.getJSONArray("schedules").getJSONObject(0)
            .put("runs_used", 6)
        assertInvalidSchedules(client, impossibleBudget, "runs_used exceeds max_runs")

        val wrongBudgetFlag = scheduleListPayload()
        wrongBudgetFlag.getJSONArray("schedules").getJSONObject(0)
            .put("runs_used", 5)
            .put("budget_exhausted", false)
            .put("structurally_eligible", false)
            .put("blocked_reason", "budget used")
        assertInvalidSchedules(client, wrongBudgetFlag, "budget exhaustion contradicts run counters")

        val fakeRuntimeGate = scheduleListPayload()
        fakeRuntimeGate.getJSONArray("schedules").getJSONObject(0)
            .put("runtime_gate_checked", true)
        assertInvalidSchedules(client, fakeRuntimeGate, "must not claim the runtime gate was checked")

        val eligibleButDisabled = scheduleListPayload()
        eligibleButDisabled.getJSONArray("schedules").getJSONObject(0)
            .put("enabled", false)
        assertInvalidSchedules(client, eligibleButDisabled, "structural eligibility contradicts grant state")

        val unexplainedIneligible = scheduleListPayload()
        unexplainedIneligible.getJSONArray("schedules").getJSONObject(0)
            .put("structurally_eligible", false)
        assertInvalidSchedules(client, unexplainedIneligible, "ineligible grant lacks a reason")
    }

    @Test
    fun grantsRejectMalformedIdentityTypesAndDuplicates() {
        val client = client()

        val badId = scheduleListPayload()
        badId.getJSONArray("schedules").getJSONObject(0).put("schedule_id", "not-an-id")
        assertInvalidSchedules(client, badId, "invalid schedule id")

        val stringBoolean = scheduleListPayload()
        stringBoolean.getJSONArray("schedules").getJSONObject(0).put("enabled", "true")
        assertInvalidSchedules(client, stringBoolean, "enabled must be boolean")

        val floatCounter = scheduleListPayload()
        floatCounter.getJSONArray("schedules").getJSONObject(0).put("runs_used", 2.0)
        assertInvalidSchedules(client, floatCounter, "runs_used must be an integer")

        val duplicate = scheduleListPayload()
        val first = duplicate.getJSONArray("schedules").getJSONObject(0)
        duplicate.getJSONArray("schedules").put(JSONObject(first.toString()))
        assertInvalidSchedules(client, duplicate, "duplicate schedule ids")
    }

    @Test
    fun disabledOrExhaustedGrantCanBeRepresentedWithoutClaimingExecutionOutcome() {
        val client = client()
        val payload = scheduleListPayload()
        val row = payload.getJSONArray("schedules").getJSONObject(0)
            .put("enabled", false)
            .put("structurally_eligible", false)
            .put("blocked_reason", "paused by operator")
        val parsed = client.parseSchedules(payload).single()
        assertFalse(parsed.enabled)
        assertFalse(parsed.structurallyEligible)
        assertEquals("paused by operator", parsed.blockedReason)
    }

    @Test
    fun schedulerApiFailureDoesNotBecomeEmptyOrHealthyState() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(404)
                .addHeader("Content-Type", "application/json")
                .setBody("""{"error":"scheduler api disabled"}"""),
        )
        server.start()
        try {
            val error = runCatching {
                ControlCenterSchedulesClient(server.url("/").toString(), "token").snapshot()
            }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertTrue(error?.message.orEmpty().contains("(404)"))
            assertTrue(error?.message.orEmpty().contains("scheduler api disabled"))
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    private fun client() = ControlCenterSchedulesClient("http://127.0.0.1:1", "token")

    private fun assertInvalidRuntime(
        client: ControlCenterSchedulesClient,
        payload: JSONObject,
        text: String,
    ) {
        val error = runCatching { client.parseRuntime(payload) }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertTrue("${error?.message} should contain $text", error?.message.orEmpty().contains(text))
    }

    private fun assertInvalidSchedules(
        client: ControlCenterSchedulesClient,
        payload: JSONObject,
        text: String,
    ) {
        val error = runCatching { client.parseSchedules(payload) }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertTrue("${error?.message} should contain $text", error?.message.orEmpty().contains(text))
    }

    private fun runtimePayload() = JSONObject()
        .put("configured", true)
        .put("running", true)
        .put("resources_open", true)
        .put("last_error", JSONObject.NULL)
        .put("max_concurrency", 1)
        .put("queue_capacity", 0)
        .put("active_executions", 0)
        .put("accepted_ticks", 42)
        .put("overlap_rejections", 3)

    private fun scheduleListPayload() = JSONObject().put(
        "schedules",
        JSONArray().put(
            JSONObject()
                .put("schedule_id", "0a1b2c3d4e5f")
                .put("tool", "note_append")
                .put("args", JSONObject().put("text", "private value not rendered"))
                .put("cadence", "daily:08:00")
                .put("timezone", "Europe/Copenhagen")
                .put("misfire_policy", "run_once")
                .put("due_at_local", "2026-08-12T08:00:00+02:00")
                .put("risk", "write")
                .put("sensitivity", "private")
                .put("action_fingerprint", "0123456789abcdef0123456789abcdef")
                .put("approved_fingerprint", "0123456789abcdef0123456789abcdef")
                .put("approval_valid", true)
                .put("expires_at", 2_000_000_000.0)
                .put("expired", false)
                .put("max_runs", 5)
                .put("runs_used", 2)
                .put("budget_exhausted", false)
                .put("due_at", 1_900_000_000.0)
                .put("missed", 1)
                .put("enabled", true)
                .put("structurally_eligible", true)
                .put("runtime_gate_checked", false)
                .put("blocked_reason", JSONObject.NULL),
        ),
    )

    private fun jsonResponse(body: String) = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/json")
        .setBody(body)
}
