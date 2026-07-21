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
    fun confirmedWriteExchangesPreviewFingerprintForOpaqueToken() {
        val fingerprint = "1234567890abcdef1234567890abcdef"
        val token = "signed.single-use-token"
        val server = MockWebServer()
        server.enqueue(jsonResponse("""{"configured":true,"running":false,"resources_open":false,"last_error":null}"""))
        server.enqueue(jsonResponse(previewJson(
            operation = "create",
            scheduleId = null,
            fingerprint = fingerprint,
            enable = true,
        )))
        server.enqueue(jsonResponse("""{"approval_token":"$token","expires_at":1800000120}"""))
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
                timezone = "America/New_York",
                misfirePolicy = "run_once",
            )
            assertEquals(fingerprint, preview.approvalFingerprint)
            assertEquals("America/New_York", preview.timezone)
            assertEquals("run_once", preview.misfirePolicy)
            assertEquals("2027-01-15T08:00:00-05:00", preview.dueAtLocal)
            val created = client.create(preview)
            assertEquals("012345abcdef", created.id)

            val statusRequest = server.takeRequest()
            assertEquals("GET", statusRequest.method)
            assertEquals("/api/v1/schedules/status", statusRequest.path)
            assertEquals("Bearer device-token", statusRequest.getHeader("Authorization"))

            val previewRequest = server.takeRequest()
            assertEquals("/api/v1/schedules/preview", previewRequest.path)
            val previewBody = JSONObject(previewRequest.body.readUtf8())
            assertFalse(previewBody.has("approved_fingerprint"))
            assertFalse(previewBody.has("approval_token"))
            assertEquals("America/New_York", previewBody.getString("timezone"))
            assertEquals("run_once", previewBody.getString("misfire_policy"))

            val approvalRequest = server.takeRequest()
            assertEquals("/api/v1/schedules/approve", approvalRequest.path)
            assertEquals("Bearer device-token", approvalRequest.getHeader("Authorization"))
            val approvalBody = JSONObject(approvalRequest.body.readUtf8())
            assertEquals(fingerprint, approvalBody.getString("preview_fingerprint"))
            assertEquals("Husk brygdag", approvalBody.getJSONObject("args").getString("text"))
            assertEquals("America/New_York", approvalBody.getString("timezone"))
            assertEquals("run_once", approvalBody.getString("misfire_policy"))

            val createRequest = server.takeRequest()
            assertEquals("/api/v1/schedules", createRequest.path)
            assertEquals("Bearer device-token", createRequest.getHeader("Authorization"))
            val createBody = JSONObject(createRequest.body.readUtf8())
            assertEquals(token, createBody.getString("approval_token"))
            assertFalse(createBody.has("approved_fingerprint"))
            assertEquals("Husk brygdag", createBody.getJSONObject("args").getString("text"))
            assertEquals("America/New_York", createBody.getString("timezone"))
            assertEquals("run_once", createBody.getString("misfire_policy"))
            assertEquals("2027-01-15T08:00:00-05:00", created.dueAtLocal)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun renewalUsesItsOwnApprovalEndpointAndPreservesEnableState() {
        val fingerprint = "fedcba0987654321fedcba0987654321"
        val token = "renewal.single-use-token"
        val id = "abcdef012345"
        val server = MockWebServer()
        server.enqueue(jsonResponse(previewJson(
            operation = "renew",
            scheduleId = id,
            fingerprint = fingerprint,
            enable = true,
        )))
        server.enqueue(jsonResponse("""{"approval_token":"$token","expires_at":1800000120}"""))
        server.enqueue(jsonResponse(scheduleEnvelope(id)))
        server.start()
        try {
            val client = ScheduleClient(server.url("/").toString(), "device-token")
            val preview = client.previewRenewal(id, ttlDays = 60, maxRuns = 2, enable = true)
            assertEquals("renew", preview.operation)
            assertEquals(id, preview.scheduleId)
            assertEquals(true, preview.enable)
            client.renew(preview)

            val previewRequest = server.takeRequest()
            assertEquals("/api/v1/schedules/$id/renew/preview", previewRequest.path)
            assertTrue(JSONObject(previewRequest.body.readUtf8()).getBoolean("enable"))

            val approvalRequest = server.takeRequest()
            assertEquals("/api/v1/schedules/$id/renew/approve", approvalRequest.path)
            val approvalBody = JSONObject(approvalRequest.body.readUtf8())
            assertEquals(fingerprint, approvalBody.getString("preview_fingerprint"))
            assertTrue(approvalBody.getBoolean("enable"))

            val renewRequest = server.takeRequest()
            assertEquals("/api/v1/schedules/$id/renew", renewRequest.path)
            val renewBody = JSONObject(renewRequest.body.readUtf8())
            assertEquals(token, renewBody.getString("approval_token"))
            assertTrue(renewBody.getBoolean("enable"))
            assertFalse(renewBody.has("approved_fingerprint"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun readScheduleSkipsWriteApprovalExchange() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(previewJson(
            operation = "create",
            scheduleId = null,
            fingerprint = null,
            enable = true,
            requiresApproval = false,
            tool = "current_datetime",
        )))
        server.enqueue(jsonResponse(scheduleEnvelope("012345abcdef", tool = "current_datetime")))
        server.start()
        try {
            val client = ScheduleClient(server.url("/").toString(), "device-token")
            val preview = client.preview(
                tool = "current_datetime",
                args = JSONObject(),
                cadence = "every:60",
                ttlDays = 10,
                maxRuns = 0,
            )
            client.create(preview)

            assertEquals("/api/v1/schedules/preview", server.takeRequest().path)
            val create = server.takeRequest()
            assertEquals("/api/v1/schedules", create.path)
            assertFalse(JSONObject(create.body.readUtf8()).has("approval_token"))
            assertEquals(2, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun approvalConflictDetailIsNotHidden() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(409)
                .addHeader("Content-Type", "application/json")
                .setBody("""{"error":"schedule preview changed; preview and confirm it again"}"""),
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
                timezone = "Europe/Copenhagen",
                misfirePolicy = "run_once",
                dueAtLocal = "2027-01-15T08:00:00+01:00",
                risk = "write",
                sensitivity = "private",
                humanSummary = "append note",
                requiresApproval = true,
                approvalFingerprint = "1234567890abcdef1234567890abcdef",
                dueAt = 1.0,
                expiresAt = 2.0,
                ttlDays = 30,
                maxRuns = 1,
                enable = true,
            )
            val error = runCatching { client.create(preview) }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertTrue(error?.message.orEmpty().contains("(409)"))
            assertTrue(error?.message.orEmpty().contains("preview changed"))
            assertEquals("/api/v1/schedules/approve", server.takeRequest().path)
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
        fingerprint: String?,
        enable: Boolean?,
        requiresApproval: Boolean = true,
        tool: String = "note_append",
        timezone: String = "America/New_York",
        dueAtLocal: String = "2027-01-15T08:00:00-05:00",
    ): String {
        val args = if (tool == "note_append") JSONObject().put("text", "Husk brygdag") else JSONObject()
        val preview = JSONObject()
            .put("operation", operation)
            .put("schedule_id", scheduleId ?: JSONObject.NULL)
            .put("tool", tool)
            .put("args", args)
            .put("cadence", if (tool == "note_append") "daily:08:00" else "every:60")
            .put("timezone", timezone)
            .put("misfire_policy", "run_once")
            .put("due_at_local", dueAtLocal)
            .put("risk", if (requiresApproval) "write" else "read")
            .put("sensitivity", if (requiresApproval) "private" else "public")
            .put("human_summary", "Planlagt handling")
            .put("requires_approval", requiresApproval)
            .put("action_fingerprint", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
            .put("approval_fingerprint", fingerprint ?: JSONObject.NULL)
            .put("due_at", 1_800_000_000.0)
            .put("expires_at", 1_802_592_000.0)
            .put("ttl_days", if (operation == "renew") 60 else if (tool == "note_append") 30 else 10)
            .put("max_runs", if (operation == "renew") 2 else if (tool == "note_append") 5 else 0)
            .put("enable", enable ?: JSONObject.NULL)
        return JSONObject()
            .put("preview", preview)
            .put("executed", false)
            .put("schedule_persisted", false)
            .toString()
    }

    private fun scheduleEnvelope(id: String, tool: String = "note_append"): String {
        val schedule = JSONObject()
            .put("schedule_id", id)
            .put("tool", tool)
            .put("args", if (tool == "note_append") JSONObject().put("text", "Husk brygdag") else JSONObject())
            .put("cadence", if (tool == "note_append") "daily:08:00" else "every:60")
            .put("timezone", "America/New_York")
            .put("misfire_policy", "run_once")
            .put("due_at_local", "2027-01-15T08:00:00-05:00")
            .put("risk", if (tool == "note_append") "write" else "read")
            .put("sensitivity", if (tool == "note_append") "private" else "public")
            .put("approved_fingerprint", if (tool == "note_append") "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" else JSONObject.NULL)
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
