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
    fun createUsesOpaquePreviewApprovalWithoutRecomputingIt() {
        val approval = "1234567890abcdef1234567890abcdef"
        val server = MockWebServer()
        server.enqueue(jsonResponse("""{"configured":true,"running":false,"resources_open":false,"last_error":null}"""))
        server.enqueue(jsonResponse(previewJson(
            operation = "create",
            scheduleId = null,
            approval = approval,
            enable = null,
        )))
        server.enqueue(jsonResponse(scheduleEnvelope("012345abcdef")))
        server.start()
        try {
            val client = ScheduleClient(server.url("/").toString(), "device-token")
            val status = client.status()
            assertTrue(status.configured)
            assertFalse(status.running)

            val preview = client.preview(
                tool = "note_append",
                args = JSONObject().put("text", "Husk brygdag"),
                cadence = "daily:08:00",
                ttlDays = 30,
                maxRuns = 5,
            )
            assertEquals(approval, preview.approvalFingerprint)
            val created = client.create(preview)
            assertEquals("012345abcdef", created.id)

            val statusRequest = server.takeRequest()
            assertEquals("GET", statusRequest.method)
            assertEquals("/api/v1/schedules/status", statusRequest.path)
            assertEquals("Bearer device-token", statusRequest.getHeader("Authorization"))

            val previewRequest = server.takeRequest()
            assertEquals("POST", previewRequest.method)
            assertEquals("/api/v1/schedules/preview", previewRequest.path)
            assertEquals("Bearer device-token", previewRequest.getHeader("Authorization"))
            val previewBody = JSONObject(previewRequest.body.readUtf8())
            assertEquals("daily:08:00", previewBody.getString("cadence"))
            assertFalse(previewBody.has("approved_fingerprint"))

            val createRequest = server.takeRequest()
            assertEquals("POST", createRequest.method)
            assertEquals("/api/v1/schedules", createRequest.path)
            assertEquals("Bearer device-token", createRequest.getHeader("Authorization"))
            val createBody = JSONObject(createRequest.body.readUtf8())
            assertEquals(approval, createBody.getString("approved_fingerprint"))
            assertEquals("Husk brygdag", createBody.getJSONObject("args").getString("text"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun renewalUsesItsOwnPreviewAndPreservesExplicitEnableState() {
        val approval = "fedcba0987654321fedcba0987654321"
        val id = "abcdef012345"
        val server = MockWebServer()
        server.enqueue(jsonResponse(previewJson(
            operation = "renew",
            scheduleId = id,
            approval = approval,
            enable = true,
        )))
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
            assertEquals("Bearer token", previewRequest.getHeader("Authorization"))
            val previewBody = JSONObject(previewRequest.body.readUtf8())
            assertTrue(previewBody.getBoolean("enable"))
            assertFalse(previewBody.has("approved_fingerprint"))

            val renewRequest = server.takeRequest()
            assertEquals("/api/v1/schedules/$id/renew", renewRequest.path)
            val renewBody = JSONObject(renewRequest.body.readUtf8())
            assertEquals(approval, renewBody.getString("approved_fingerprint"))
            assertTrue(renewBody.getBoolean("enable"))
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
            val preview = SchedulePreview(
                operation = "create",
                scheduleId = null,
                tool = "note_append",
                argsJson = "{}",
                cadence = "daily:08:00",
                risk = "write",
                sensitivity = "private",
                humanSummary = "append note",
                requiresApproval = true,
                approvalFingerprint = "1234567890abcdef1234567890abcdef",
                dueAt = 1.0,
                expiresAt = 2.0,
                ttlDays = 30,
                maxRuns = 1,
                enable = null,
            )
            val error = runCatching { client.create(preview) }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertTrue(error?.message.orEmpty().contains("(409)"))
            assertTrue(error?.message.orEmpty().contains("standing grant changed"))
        } finally {
            server.shutdown()
        }
    }

    private fun jsonResponse(body: String) = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/json")
        .setBody(body)

    private fun previewJson(
        operation: String,
        scheduleId: String?,
        approval: String,
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
            .put("action_fingerprint", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
            .put("approval_fingerprint", approval)
            .put("due_at", 1_800_000_000.0)
            .put("expires_at", 1_802_592_000.0)
            .put("ttl_days", if (operation == "renew") 60 else 30)
            .put("max_runs", if (operation == "renew") 2 else 5)
            .put("enable", enable ?: JSONObject.NULL)
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
            .put("approved_fingerprint", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
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
