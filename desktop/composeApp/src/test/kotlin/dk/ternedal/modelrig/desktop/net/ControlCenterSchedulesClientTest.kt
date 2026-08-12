package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ControlCenterSchedulesClientTest {
    @Test
    fun snapshotUsesOnlyExistingAuthenticatedGetRoutes() {
        val requests = CopyOnWriteArrayList<Pair<String, String?>>()
        val server = server { exchange ->
            requests += exchange.requestURI.path to exchange.requestHeaders.getFirst("Authorization")
            val body = when (exchange.requestURI.path) {
                "/api/v1/schedules/status" -> runtimePayload()
                "/api/v1/schedules" -> scheduleListPayload()
                else -> "{\"error\":\"unexpected path\"}"
            }.toByteArray()
            exchange.responseHeaders.add("Content-Type", "application/json")
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val snapshot = ControlCenterSchedulesClient(
                "http://127.0.0.1:${server.address.port}",
                "paired-token",
            ).snapshot()

            assertTrue(snapshot.runtime.configured)
            assertTrue(snapshot.runtime.running)
            assertEquals(1, snapshot.runtime.maxConcurrency)
            assertEquals(1, snapshot.schedules.size)
            val grant = snapshot.schedules.single()
            assertEquals("0a1b2c3d4e5f", grant.id)
            assertEquals("note_append", grant.tool)
            assertEquals(2, grant.runsUsed)
            assertEquals(5, grant.maxRuns)
            assertTrue(grant.structurallyEligible)
            assertFalse(grant.budgetExhausted)
            assertFalse(grant.toString().contains("private value not rendered"))
            assertEquals(
                listOf(
                    "/api/v1/schedules/status" to "Bearer paired-token",
                    "/api/v1/schedules" to "Bearer paired-token",
                ),
                requests.toList(),
            )
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun runtimeRejectsTypeAndStateContradictions() {
        val client = client()
        assertInvalidRuntime(
            client,
            runtimePayload().replace("\"running\":true", "\"running\":\"true\""),
            "running must be boolean",
        )
        assertInvalidRuntime(
            client,
            runtimePayload()
                .replace("\"configured\":true", "\"configured\":false")
                .replace("\"running\":true", "\"running\":true"),
            "running runtime is not configured",
        )
        assertInvalidRuntime(
            client,
            runtimePayload().replace("\"active_executions\":0", "\"active_executions\":2"),
            "active executions exceed max concurrency",
        )
        assertInvalidRuntime(
            client,
            runtimePayload().replace("\"accepted_ticks\":42", "\"accepted_ticks\":-1"),
            "accepted_ticks must be non-negative",
        )
    }

    @Test
    fun grantsRejectBudgetEligibilityAndRuntimeGateContradictions() {
        val client = client()
        assertInvalidSchedules(
            client,
            scheduleListPayload().replace("\"runs_used\":2", "\"runs_used\":6"),
            "runs_used exceeds max_runs",
        )
        assertInvalidSchedules(
            client,
            scheduleListPayload()
                .replace("\"runs_used\":2", "\"runs_used\":5")
                .replace("\"structurally_eligible\":true", "\"structurally_eligible\":false")
                .replace("\"blocked_reason\":null", "\"blocked_reason\":\"budget used\""),
            "budget exhaustion contradicts run counters",
        )
        assertInvalidSchedules(
            client,
            scheduleListPayload().replace("\"runtime_gate_checked\":false", "\"runtime_gate_checked\":true"),
            "must not claim the runtime gate was checked",
        )
        assertInvalidSchedules(
            client,
            scheduleListPayload().replace("\"enabled\":true", "\"enabled\":false"),
            "structural eligibility contradicts grant state",
        )
        assertInvalidSchedules(
            client,
            scheduleListPayload().replace("\"structurally_eligible\":true", "\"structurally_eligible\":false"),
            "ineligible grant lacks a reason",
        )
    }

    @Test
    fun grantsRejectMalformedIdentityTypesAndDuplicates() {
        val client = client()
        assertInvalidSchedules(
            client,
            scheduleListPayload().replace("0a1b2c3d4e5f", "not-an-id"),
            "invalid schedule id",
        )
        assertInvalidSchedules(
            client,
            scheduleListPayload().replace("\"enabled\":true", "\"enabled\":\"true\""),
            "enabled must be boolean",
        )
        assertInvalidSchedules(
            client,
            scheduleListPayload().replace("\"runs_used\":2", "\"runs_used\":2.0"),
            "runs_used must be an integer",
        )
        val row = scheduleRow()
        assertInvalidSchedules(
            client,
            "{\"schedules\":[$row,$row]}",
            "duplicate schedule ids",
        )
    }

    @Test
    fun disabledGrantRemainsGrantMetadataNotExecutionOutcome() {
        val parsed = client().parseSchedules(
            scheduleListPayload()
                .replace("\"enabled\":true", "\"enabled\":false")
                .replace("\"structurally_eligible\":true", "\"structurally_eligible\":false")
                .replace("\"blocked_reason\":null", "\"blocked_reason\":\"paused by operator\""),
        ).single()

        assertFalse(parsed.enabled)
        assertFalse(parsed.structurallyEligible)
        assertEquals("paused by operator", parsed.blockedReason)
    }

    @Test
    fun schedulerApiFailureDoesNotBecomeEmptyHealthyState() {
        val server = server { exchange ->
            val body = "{\"error\":\"scheduler api disabled\"}".toByteArray()
            exchange.sendResponseHeaders(404, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val error = runCatching {
                ControlCenterSchedulesClient(
                    "http://127.0.0.1:${server.address.port}",
                    "token",
                ).snapshot()
            }.exceptionOrNull()
            assertTrue(error is ControlCenterException)
            assertTrue(error.message.orEmpty().contains("(404)"))
            assertTrue(error.message.orEmpty().contains("scheduler api disabled"))
        } finally {
            server.stop(0)
        }
    }

    private fun client() = ControlCenterSchedulesClient("http://127.0.0.1:1", "token")

    private fun assertInvalidRuntime(
        client: ControlCenterSchedulesClient,
        body: String,
        text: String,
    ) {
        val error = runCatching { client.parseRuntime(body) }.exceptionOrNull()
        assertTrue(error is ControlCenterException, "unexpected error: $error")
        assertTrue(error.message.orEmpty().contains(text), "${error.message} should contain $text")
    }

    private fun assertInvalidSchedules(
        client: ControlCenterSchedulesClient,
        body: String,
        text: String,
    ) {
        val error = runCatching { client.parseSchedules(body) }.exceptionOrNull()
        assertTrue(error is ControlCenterException, "unexpected error: $error")
        assertTrue(error.message.orEmpty().contains(text), "${error.message} should contain $text")
    }

    private fun server(handler: (com.sun.net.httpserver.HttpExchange) -> Unit): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange -> handler(exchange) }
        server.start()
        return server
    }

    private fun runtimePayload() = """
        {
          "configured":true,
          "running":true,
          "resources_open":true,
          "last_error":null,
          "max_concurrency":1,
          "queue_capacity":0,
          "active_executions":0,
          "accepted_ticks":42,
          "overlap_rejections":3
        }
    """.trimIndent()

    private fun scheduleListPayload() = "{\"schedules\":[${scheduleRow()}]}"

    private fun scheduleRow() = """
        {
          "schedule_id":"0a1b2c3d4e5f",
          "tool":"note_append",
          "args":{"text":"private value not rendered"},
          "cadence":"daily:08:00",
          "timezone":"Europe/Copenhagen",
          "misfire_policy":"run_once",
          "due_at_local":"2026-08-12T08:00:00+02:00",
          "risk":"write",
          "sensitivity":"private",
          "action_fingerprint":"0123456789abcdef0123456789abcdef",
          "approved_fingerprint":"0123456789abcdef0123456789abcdef",
          "approval_valid":true,
          "expires_at":2000000000.0,
          "expired":false,
          "max_runs":5,
          "runs_used":2,
          "budget_exhausted":false,
          "due_at":1900000000.0,
          "missed":1,
          "enabled":true,
          "structurally_eligible":true,
          "runtime_gate_checked":false,
          "blocked_reason":null
        }
    """.trimIndent()
}
