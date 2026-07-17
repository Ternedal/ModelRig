package dk.ternedal.modelrig.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetSocketAddress
import java.util.concurrent.CopyOnWriteArrayList

class ScheduleClientTest {
    private data class Hit(val method: String, val path: String, val auth: String?, val body: String)

    private fun server(handler: (HttpExchange, List<Hit>) -> String): Pair<HttpServer, MutableList<Hit>> {
        val hits = CopyOnWriteArrayList<Hit>()
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange ->
            val body = exchange.requestBody.bufferedReader().use { it.readText() }
            hits += Hit(
                exchange.requestMethod,
                exchange.requestURI.path,
                exchange.requestHeaders.getFirst("Authorization"),
                body,
            )
            try {
                val response = handler(exchange, hits)
                val bytes = response.toByteArray()
                exchange.responseHeaders.set("Content-Type", "application/json")
                exchange.sendResponseHeaders(200, bytes.size.toLong())
                exchange.responseBody.use { it.write(bytes) }
            } catch (e: Refusal) {
                val bytes = e.body.toByteArray()
                exchange.responseHeaders.set("Content-Type", "application/json")
                exchange.sendResponseHeaders(e.status, bytes.size.toLong())
                exchange.responseBody.use { it.write(bytes) }
            }
        }
        server.start()
        return server to hits
    }

    @Test
    fun createUsesOpaquePreviewApprovalWithoutRecomputingIt() {
        val approval = "1234567890abcdef1234567890abcdef"
        val (server, hits) = server { exchange, _ ->
            when (exchange.requestURI.path) {
                "/api/v1/schedules/status" ->
                    """{"configured":true,"running":false,"resources_open":false,"last_error":null}"""
                "/api/v1/schedules/preview" -> previewJson(
                    operation = "create",
                    scheduleId = null,
                    approval = approval,
                    enable = null,
                )
                "/api/v1/schedules" -> scheduleEnvelope("012345abcdef")
                else -> error("unexpected ${exchange.requestURI.path}")
            }
        }
        try {
            val base = "http://127.0.0.1:${server.address.port}"
            val client = ScheduleClient(base, "device-token")
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

            assertEquals(3, hits.size)
            hits.forEach { assertEquals("Bearer device-token", it.auth) }
            val previewBody = JSONObject(hits[1].body)
            assertEquals("daily:08:00", previewBody.getString("cadence"))
            assertFalse(previewBody.has("approved_fingerprint"))
            val createBody = JSONObject(hits[2].body)
            assertEquals(approval, createBody.getString("approved_fingerprint"))
            assertEquals("Husk brygdag", createBody.getJSONObject("args").getString("text"))
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun renewalUsesItsOwnPreviewAndPreservesExplicitEnableState() {
        val approval = "fedcba0987654321fedcba0987654321"
        val id = "abcdef012345"
        val (server, hits) = server { exchange, _ ->
            when (exchange.requestURI.path) {
                "/api/v1/schedules/$id/renew/preview" -> previewJson(
                    operation = "renew",
                    scheduleId = id,
                    approval = approval,
                    enable = true,
                )
                "/api/v1/schedules/$id/renew" -> scheduleEnvelope(id)
                else -> error("unexpected ${exchange.requestURI.path}")
            }
        }
        try {
            val client = ScheduleClient("http://127.0.0.1:${server.address.port}", "token")
            val preview = client.previewRenewal(id, ttlDays = 60, maxRuns = 2, enable = true)
            assertEquals("renew", preview.operation)
            assertEquals(id, preview.scheduleId)
            assertEquals(true, preview.enable)
            client.renew(preview)

            val previewBody = JSONObject(hits[0].body)
            assertTrue(previewBody.getBoolean("enable"))
            assertFalse(previewBody.has("approved_fingerprint"))
            val renewBody = JSONObject(hits[1].body)
            assertEquals(approval, renewBody.getString("approved_fingerprint"))
            assertTrue(renewBody.getBoolean("enable"))
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun workerConflictDetailIsNotHidden() {
        val (server, _) = server { exchange, _ ->
            if (exchange.requestURI.path == "/api/v1/schedules") {
                throw Refusal(409, """{"detail":"standing grant changed"}""")
            }
            error("unexpected path")
        }
        try {
            val client = ScheduleClient("http://127.0.0.1:${server.address.port}", "token")
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
            server.stop(0)
        }
    }

    private class Refusal(val status: Int, val body: String) : RuntimeException()

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
