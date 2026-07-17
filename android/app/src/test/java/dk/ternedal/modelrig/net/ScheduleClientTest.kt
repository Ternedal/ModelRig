package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ScheduleClientTest {
    @Test
    fun createGetsSignedApprovalOnlyAfterExplicitConfirmAndForwardsItOpaque() {
        val binding = "a".repeat(64)
        val token = "kav1.opaque-payload.opaque-signature"
        val server = MockWebServer()
        server.enqueue(jsonResponse("""{"configured":true,"running":false,"resources_open":false,"approval_verifier_configured":true,"last_error":null}"""))
        server.enqueue(jsonResponse(previewJson("create", null, binding, null, null)))
        server.enqueue(jsonResponse(previewJson("create", null, binding, token, null)))
        server.enqueue(jsonResponse(scheduleEnvelope("012345abcdef")))
        server.start()
        try {
            val client = ScheduleClient(server.url("/").toString(), "device-token")
            val status = client.status()
            assertTrue(status.configured)
            assertFalse(status.running)
            assertTrue(status.approvalVerifierConfigured)

            val preview = client.preview(
                tool = "note_append",
                args = JSONObject().put("text", "Husk brygdag"),
                cadence = "daily:08:00",
                ttlDays = 30,
                maxRuns = 5,
            )
            assertEquals(binding, preview.approvalBinding)
            assertTrue(preview.approvalToken == null)
            val created = client.create(preview)
            assertEquals("012345abcdef", created.id)

            val statusRequest = server.takeRequest()
            assertEquals("GET", statusRequest.method)
            assertEquals("/api/v1/schedules/status", statusRequest.path)
            assertEquals("Bearer device-token", statusRequest.getHeader("Authorization"))

            val previewRequest = server.takeRequest()
            assertEquals("/api/v1/schedules/preview", previewRequest.path)
            assertEquals("Bearer device-token", previewRequest.getHeader("Authorization"))
            val previewBody = JSONObject(previewRequest.body.readUtf8())
            assertEquals("daily:08:00", previewBody.getString("cadence"))
            assertFalse(previewBody.has("approval_token"))
            assertFalse(previewBody.has("approved_fingerprint"))

            val approvalRequest = server.takeRequest()
            assertEquals("/api/v1/schedules/approve", approvalRequest.path)
            assertEquals("Bearer device-token", approvalRequest.getHeader("Authorization"))
            val approvalBody = JSONObject(approvalRequest.body.readUtf8())
            assertEquals("Husk brygdag", approvalBody.getJSONObject("args").getString("text"))
            assertFalse(approvalBody.has("approval_token"))

            val createRequest = server.takeRequest()
            assertEquals("/api/v1/schedules", createRequest.path)
            assertEquals("Bearer device-token", createRequest.getHeader("Authorization"))
            val createBody = JSONObject(createRequest.body.readUtf8())
            assertEquals(token, createBody.getString("approval_token"))
            assertFalse(createBody.has("approved_fingerprint"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun renewalUsesItsOwnApprovalRouteAndPreservesExplicitEnableState() {
        val binding = "b".repeat(64)
        val token = "kav1.renew-payload.renew-signature"
        val id = "abcdef012345"
        val server = MockWebServer()
        server.enqueue(jsonResponse(previewJson("renew", id, binding, null, true)))
        server.enqueue(jsonResponse(previewJson("renew", id, binding, token, true)))
        server.enqueue(jsonResponse(scheduleEnvelope(id)))
        server.start()
        try {
            val client = ScheduleClient(server.url("/").toString(), "token")
            val preview = client.previewRenewal(id, ttlDays = 60, maxRuns = 2, enable = true)
            assertEquals("renew", preview.operation)
            assertEquals(id, preview.scheduleId)
            assertEquals(true, preview.enable)
            client.renew(preview)

            val previewRequest = server.takeRequest()
            assertEquals("/api/v1/schedules/$id/renew/preview", previewRequest.path)
            val previewBody = JSONObject(previewRequest.body.readUtf8())
            assertTrue(previewBody.getBoolean("enable"))

            val approvalRequest = server.takeRequest()
            assertEquals("/api/v1/schedules/$id/renew/approve", approvalRequest.path)
            assertTrue(JSONObject(approvalRequest.body.readUtf8()).getBoolean("enable"))

            val renewRequest = server.takeRequest()
            assertEquals("/api/v1/schedules/$id/renew", renewRequest.path)
            val renewBody = JSONObject(renewRequest.body.readUtf8())
            assertEquals(token, renewBody.getString("approval_token"))
            assertTrue(renewBody.getBoolean("enable"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun changedBackendApprovalBindingIsRefusedBeforeCreate() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(previewJson("create", null, "c".repeat(64), "kav1.x.y", null)))
        server.start()
        try {
            val client = ScheduleClient(server.url("/").toString(), "token")
            val preview = writePreview(binding = "d".repeat(64))
            val error = runCatching { client.create(preview) }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertTrue(error?.message.orEmpty().contains("changed after preview"))
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun workerConflictDetailIsNotHidden() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(409)
                .addHeader("Content-Type", "application/json")
                .setBody("""{"detail":"standing grant changed"}"""),
        )
        server.start()
        try {
            val client = ScheduleClient(server.url("/").toString(), "token")
            val error = runCatching { client.create(writePreview("e".repeat(64))) }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertTrue(error?.message.orEmpty().contains("(409)"))
            assertTrue(error?.message.orEmpty().contains("standing grant changed"))
        } finally {
            server.shutdown()
        }
    }

    private fun writePreview(binding: String) = SchedulePreview(
        operation = "create",
        scheduleId = null,
        tool = "note_append",
        argsJson = "{}",
        cadence = "daily:08:00",
        risk = "write",
        sensitivity = "private",
        humanSummary = "append note",
        requiresApproval = true,
        approvalBinding = binding,
        approvalToken = null,
        approvalTokenExpiresAt = null,
        dueAt = 1.0,
        expiresAt = 2.0,
        ttlDays = 30,
        maxRuns = 1,
        enable = null,
    )

    private fun jsonResponse(body: String) = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/json")
        .setBody(body)

    private fun previewJson(
        operation: String,
        scheduleId: String?,
        binding: String,
        token: String?,
        enable: Boolean?,
    ): String {
        val preview = JSONObject()
            .put("operation", operation)
            .put("schedule_id", scheduleId ?: JSONObject.NULL)
            .put("tool", "note_append")
            .put("args", JSONObject().put("text", "Husk brygdag"))
            .put("cadence", "daily:08:00")
            .put("risk", "write")
            .put("sensitivity", "private")
            .put("human_summary", "Tilføj noten Husk brygdag")
            .put("requires_approval", true)
            .put("action_fingerprint", "f".repeat(32))
            .put("approval_binding", binding)
            .put("due_at", 1_800_000_000.0)
            .put("expires_at", 1_802_592_000.0)
            .put("ttl_days", if (operation == "renew") 60 else 30)
            .put("max_runs", if (operation == "renew") 2 else 5)
            .put("enable", enable ?: JSONObject.NULL)
        if (token != null) {
            preview.put("approval_token", token)
            preview.put("approval_token_expires_at", 1_900_000_300.0)
        }
        return JSONObject()
            .put("preview", preview)
            .put("executed", false)
            .put("schedule_persisted", false)
            .toString()
    }

    private fun scheduleEnvelope(id: String): String {
        val schedule = JSONObject()
            .put("schedule_id", id)
            .put("tool", "note_append")
            .put("args", JSONObject().put("text", "Husk brygdag"))
            .put("cadence", "daily:08:00")
            .put("risk", "write")
            .put("sensitivity", "private")
            .put("approved_fingerprint", "a".repeat(32))
            .put("approval_valid", true)
            .put("expires_at", 1_802_592_000.0)
            .put("expired", false)
            .put("max_runs", 5)
            .put("runs_used", 0)
            .put("budget_exhausted", false)
            .put("due_at", 1_800_000_000.0)
            .put("missed", 0)
            .put("enabled", true)
            .put("eligible", true)
            .put("blocked_reason", JSONObject.NULL)
            .put("tool_layer_enabled", true)
            .put("tool_disabled", false)
        return JSONObject().put("schedule", schedule).put("executed", false).toString()
    }
}
