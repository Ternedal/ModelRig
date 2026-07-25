package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReadonlyTaskClientTest {
    @Test
    fun previewUsesOnlyAuthenticatedNormalTaskRoute() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(previewJson()))
        server.start()
        try {
            val client = Agent3ReadonlyTaskClient(server.url("/").toString(), "device-token")
            val preview = client.preview("vis rigstatus", "conversation-1")

            assertEquals("plan-123", preview.planId)
            assertTrue(preview.canStart)
            assertEquals("rig_status", preview.steps.single().tool)
            assertFalse(preview.capabilityReceipt?.productionActivation ?: true)

            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertEquals("/api/v1/experimental/agent3/task/plan", request.path)
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
            val body = JSONObject(request.body.readUtf8())
            assertEquals(setOf("message", "conversation_id"), body.keys().asSequence().toSet())
            assertEquals("vis rigstatus", body.getString("message"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun startUsesSinglePurposeRouteAndParsesOutcome() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(startedJson()))
        server.start()
        try {
            val client = Agent3ReadonlyTaskClient(server.url("/").toString(), "device-token")
            val started = client.start("plan-123")

            assertEquals("run-1", started.run.id)
            assertEquals("completed", started.run.state)
            assertEquals("rig_tools_local", started.run.routeKind)
            assertTrue(started.events.any { it.kind == "task_surface_bound" })

            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertEquals("/api/v1/experimental/agent3/task/plans/plan-123/start", request.path)
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
            assertEquals("{}", JSONObject(request.body.readUtf8()).toString())
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun unsafePreviewContractsFailClosed() {
        val client = Agent3ReadonlyTaskClient("http://127.0.0.1", "token")
        val write = JSONObject(previewJson()).also {
            it.getJSONArray("plan").getJSONObject(0).put("risk", "write")
        }
        val nonIdempotent = JSONObject(previewJson()).also {
            it.getJSONArray("plan").getJSONObject(0).put("idempotent", false)
        }
        val cloud = JSONObject(previewJson()).also {
            it.getJSONObject("route").put("uses_cloud", true)
        }
        val activation = JSONObject(previewJson()).put("production_activation", true)

        listOf(write, nonIdempotent, cloud, activation).forEach { value ->
            assertTrue(runCatching { client.parsePreview(value) }.exceptionOrNull() is ModelRigException)
        }
    }

    @Test
    fun confirmationOrWriteRunFailsClosed() {
        val client = Agent3ReadonlyTaskClient("http://127.0.0.1", "token")
        val confirmation = JSONObject(startedJson()).also {
            it.getJSONObject("run").put("state", "waiting_confirmation")
        }
        val write = JSONObject(startedJson()).also {
            it.getJSONObject("run").getJSONArray("steps").getJSONObject(0).put("risk", "write")
        }

        assertTrue(runCatching { client.parseStarted(confirmation) }.exceptionOrNull() is ModelRigException)
        assertTrue(runCatching { client.parseStarted(write) }.exceptionOrNull() is ModelRigException)
    }

    @Test
    fun malformedPlanIdNeverTouchesNetwork() {
        val server = MockWebServer()
        server.start()
        try {
            val client = Agent3ReadonlyTaskClient(server.url("/").toString(), "token")
            val error = runCatching { client.start("../generic-plan") }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertEquals(0, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    private fun jsonResponse(body: String) = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/json")
        .setBody(body)

    private fun envelope(): JSONObject = JSONObject()
        .put("task_surface", "agent3_readonly")
        .put("selected_surface", "agent3_readonly")
        .put("fallback_surface", "agent2")
        .put("reason", "agent3_readonly_selected")
        .put("production_activation", false)
        .put("normal_chat_route_unchanged", true)
        .put(
            "readiness_binding",
            JSONObject()
                .put("pilot_report_sha256", "a".repeat(64))
                .put("pilot_candidate_git_sha", "b".repeat(40))
                .put("rig_validation_report_sha256", "c".repeat(64)),
        )
        .put(
            "capability_receipt",
            JSONObject()
                .put("schema", "kaliv-agent3-capability-receipt/v1")
                .put("graph_sha256", "d".repeat(64))
                .put("plan_sha256", "e".repeat(64))
                .put("route", "rig_tools_local")
                .put("allowed", true)
                .put("blockers", org.json.JSONArray())
                .put("production_activation", false),
        )

    private fun readStep(): JSONObject = JSONObject()
        .put("id", "step-1")
        .put("tool", "rig_status")
        .put("args", JSONObject())
        .put("risk", "read")
        .put("sensitivity", "operational")
        .put("egress", "local")
        .put("idempotent", true)
        .put("summary", "Read rig status")
        .put("state", "succeeded")

    private fun previewJson(): String = envelope()
        .put(
            "route",
            JSONObject()
                .put("kind", "rig_tools_local")
                .put("uses_cloud", false)
                .put("uses_rig", true)
                .put("uses_tools", true)
                .put("uses_rag", false),
        )
        .put("rationale", "Read current status")
        .put("plan", org.json.JSONArray().put(readStep()))
        .put("plan_id", "plan-123")
        .put("expires_in_seconds", 120)
        .put("executed", false)
        .toString()

    private fun startedJson(): String = envelope()
        .put(
            "run",
            JSONObject()
                .put("id", "run-1")
                .put("state", "completed")
                .put("route", JSONObject().put("kind", "rig_tools_local"))
                .put("current_step", 1)
                .put("steps", org.json.JSONArray().put(readStep()))
                .put("answer", "Rig is ready")
                .put("error", JSONObject.NULL),
        )
        .put(
            "events",
            org.json.JSONArray().put(
                JSONObject()
                    .put("ts", 1.0)
                    .put("kind", "task_surface_bound")
                    .put("payload", JSONObject().put("surface", "agent3_readonly")),
            ),
        )
        .toString()
}
