package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3TaskReadinessClientTest {
    @Test
    fun agent2FallbackIsTypedAndAuthenticated() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(readinessJson()))
        server.start()
        try {
            val client = Agent3TaskReadinessClient(server.url("/").toString(), "device-token")
            val readiness = client.readiness()

            assertEquals("agent2", readiness.selectedSurface)
            assertFalse(readiness.agent3ReadonlySelected)
            assertEquals("pilot_report_path_not_configured", readiness.reason)
            assertFalse(readiness.productionActivation)
            assertTrue(readiness.normalChatRouteUnchanged)

            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertEquals("/api/v1/experimental/agent3/task-readiness", request.path)
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun exactAgent3ReadonlySelectionIsAcceptedAsStateOnly() {
        val client = Agent3TaskReadinessClient("http://127.0.0.1", "token")
        val readiness = client.parse(
            JSONObject(
                readinessJson(
                    selected = "agent3_readonly",
                    eligible = true,
                    operatorEnabled = true,
                    reason = "agent3_readonly_selected",
                    reasons = emptyList(),
                ),
            ),
        )

        assertTrue(readiness.agent3ReadonlySelected)
        assertEquals("agent2", readiness.fallbackSurface)
        assertTrue(readiness.uiContract.stopVisible)
        assertTrue(readiness.uiContract.receiptsVisible)
        assertTrue(readiness.pilot.stopFallbackProven)
        assertEquals(20, readiness.pilot.successes)
    }

    @Test
    fun unreadyAgent3SelectionFailsClosed() {
        val client = Agent3TaskReadinessClient("http://127.0.0.1", "token")
        val error = runCatching {
            client.parse(
                JSONObject(
                    readinessJson(
                        selected = "agent3_readonly",
                        eligible = false,
                        operatorEnabled = true,
                        reason = "agent3_readonly_selected",
                        reasons = emptyList(),
                    ),
                ),
            )
        }.exceptionOrNull()

        assertTrue(error is ModelRigException)
        assertTrue(error?.message.orEmpty().contains("eksakt readiness"))
    }

    @Test
    fun unknownSchemaOrSurfaceIsRejected() {
        val client = Agent3TaskReadinessClient("http://127.0.0.1", "token")
        val unknownSchema = JSONObject(readinessJson()).put("schema", "future/v9")
        val unknownSurface = JSONObject(readinessJson()).put("selected_surface", "agent4")

        val schemaError = runCatching { client.parse(unknownSchema) }.exceptionOrNull()
        val surfaceError = runCatching { client.parse(unknownSurface) }.exceptionOrNull()

        assertTrue(schemaError is ModelRigException)
        assertTrue(surfaceError is ModelRigException)
    }

    @Test
    fun incompleteUiSafetyContractIsRejected() {
        val client = Agent3TaskReadinessClient("http://127.0.0.1", "token")
        val root = JSONObject(readinessJson())
        root.getJSONObject("ui_contract").put("stop_visible", false)

        val error = runCatching { client.parse(root) }.exceptionOrNull()

        assertTrue(error is ModelRigException)
        assertTrue(error?.message.orEmpty().contains("UI-sikkerhedskontrakten"))
    }

    private fun jsonResponse(body: String) = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/json")
        .setBody(body)

    private fun readinessJson(
        selected: String = "agent2",
        eligible: Boolean = false,
        operatorEnabled: Boolean = true,
        reason: String = "pilot_report_path_not_configured",
        reasons: List<String> = listOf("pilot_report_path_not_configured"),
    ): String {
        val pilot = JSONObject()
            .put("configured", selected == "agent3_readonly")
            .put("present", selected == "agent3_readonly")
            .put("structurally_valid", selected == "agent3_readonly")
            .put("fresh", selected == "agent3_readonly")
            .put("version_match", selected == "agent3_readonly")
            .put("code_match", selected == "agent3_readonly")
            .put("finished_at", if (selected == "agent3_readonly") "2026-07-25T19:00:00+00:00" else JSONObject.NULL)
            .put("age_seconds", if (selected == "agent3_readonly") 60.0 else JSONObject.NULL)
            .put("max_age_hours", 168.0)
            .put("report_sha256", if (selected == "agent3_readonly") "a".repeat(64) else JSONObject.NULL)
            .put("candidate_git_sha", if (selected == "agent3_readonly") "b".repeat(40) else JSONObject.NULL)
            .put("tasks", if (selected == "agent3_readonly") 20 else JSONObject.NULL)
            .put("successes", if (selected == "agent3_readonly") 20 else JSONObject.NULL)
            .put("failures", if (selected == "agent3_readonly") 0 else JSONObject.NULL)
            .put("task_success_rate", if (selected == "agent3_readonly") 1.0 else JSONObject.NULL)
            .put("replans", if (selected == "agent3_readonly") 2 else JSONObject.NULL)
            .put("retry_events", if (selected == "agent3_readonly") 0 else JSONObject.NULL)
            .put("stop_fallback_proven", selected == "agent3_readonly")
        val validation = JSONObject()
            .put("eligible_for_developer_preview", selected == "agent3_readonly")
            .put("version_match", selected == "agent3_readonly")
            .put("code_match", selected == "agent3_readonly")
            .put("report_sha256", if (selected == "agent3_readonly") "c".repeat(64) else JSONObject.NULL)
        val ui = JSONObject()
            .put("route_source", "server_authoritative")
            .put("stop_visible", true)
            .put("fallback_visible", true)
            .put("receipts_visible", true)
            .put("replans_visible", true)
            .put("outcomes_visible", true)

        return JSONObject()
            .put("schema", "kaliv-agent3-task-readiness/v1")
            .put("selected_surface", selected)
            .put("candidate_surface", "agent3_readonly")
            .put("fallback_surface", "agent2")
            .put("eligible_for_task_ui", eligible)
            .put("operator_enabled", operatorEnabled)
            .put("normal_chat_route_unchanged", true)
            .put("production_activation", false)
            .put("reason", reason)
            .put("reasons", JSONArray(reasons))
            .put("pilot", pilot)
            .put("rig_validation", validation)
            .put("ui_contract", ui)
            .toString()
    }
}
