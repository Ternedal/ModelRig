package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ControlCenterAuditClientTest {
    @Test
    fun snapshotUsesExistingAuthenticatedAuditGetRoute() {
        val requests = CopyOnWriteArrayList<Pair<String, String?>>()
        val server = server { exchange ->
            val target = buildString {
                append(exchange.requestURI.path)
                exchange.requestURI.rawQuery?.let { append('?').append(it) }
            }
            requests += target to exchange.requestHeaders.getFirst("Authorization")
            val body = payload().toByteArray()
            exchange.responseHeaders.add("Content-Type", "application/json")
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val snapshot = ControlCenterAuditClient(
                "http://127.0.0.1:${server.address.port}",
                "paired-token",
            ).snapshot()

            assertEquals(1, snapshot.entries.size)
            assertEquals(
                listOf("/api/v1/tools/audit?limit=100" to "Bearer paired-token"),
                requests.toList(),
            )
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun rawContentNeverEntersControlCenterModel() {
        val snapshot = client().parse(payload())
        val entry = snapshot.entries.single()

        assertEquals("tool:note_append", entry.capabilityId)
        assertEquals("task-123", entry.taskRef)
        assertEquals("confirm-123", entry.approvalId)
        assertEquals("cloud", entry.origin)
        assertEquals("executed", entry.outcome)
        assertFalse(entry.toString().contains("TOP SECRET ARGUMENT"))
        assertFalse(entry.toString().contains("TOP SECRET RESULT"))
        assertFalse(snapshot.toString().contains("TOP SECRET ARGUMENT"))
        assertFalse(snapshot.toString().contains("TOP SECRET RESULT"))
    }

    @Test
    fun taskCapabilityAndApprovalFiltersUseRecordedEvidence() {
        val snapshot = client().parse(payload())

        assertEquals(1, snapshot.filtered(ControlCenterAuditFilter(task = "task-123")).size)
        assertEquals(1, snapshot.filtered(ControlCenterAuditFilter(capability = "tool:note")).size)
        assertEquals(1, snapshot.filtered(ControlCenterAuditFilter(approval = "confirm-123")).size)
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(task = "other-task")).isEmpty())
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(capability = "tool:rig_status")).isEmpty())
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(approval = "other-approval")).isEmpty())
    }

    @Test
    fun connectorFilterFailsClosedBecauseConnectorIsNotRecorded() {
        val snapshot = client().parse(payload())

        assertEquals("unavailable", snapshot.connectorEvidence.state)
        assertEquals("tool_audit_does_not_record_connector_id", snapshot.connectorEvidence.reason)
        assertEquals(null, snapshot.entries.single().connectorId)
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(connector = "gmail")).isEmpty())
    }

    @Test
    fun malformedDurationTypesFailClosed() {
        val fractional = payload().replace("\"duration_ms\":12", "\"duration_ms\":12.5")
        val error = runCatching { client().parse(fractional) }.exceptionOrNull()
        assertTrue(error is ControlCenterException)
        assertTrue(error.message.orEmpty().contains("duration_ms must be an integer"))

        val quoted = payload().replace("\"duration_ms\":12", "\"duration_ms\":\"12\"")
        val error2 = runCatching { client().parse(quoted) }.exceptionOrNull()
        assertTrue(error2 is ControlCenterException)
        assertTrue(error2.message.orEmpty().contains("duration_ms must be an integer"))
    }

    @Test
    fun unknownOutcomeStaysUnknownDataInsteadOfSyntheticSuccess() {
        val snapshot = client().parse(
            payload().replace("\"outcome\":\"executed\"", "\"outcome\":\"future_outcome\""),
        )
        assertEquals("future_outcome", snapshot.entries.single().outcome)
    }

    @Test
    fun auditApiFailureDoesNotBecomeEmptyHealthyState() {
        val server = server { exchange ->
            val body = "{\"error\":\"audit unavailable\"}".toByteArray()
            exchange.sendResponseHeaders(502, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val error = runCatching {
                ControlCenterAuditClient(
                    "http://127.0.0.1:${server.address.port}",
                    "token",
                ).snapshot()
            }.exceptionOrNull()
            assertTrue(error is ControlCenterException)
            assertTrue(error.message.orEmpty().contains("(502)"))
            assertTrue(error.message.orEmpty().contains("audit unavailable"))
        } finally {
            server.stop(0)
        }
    }

    private fun client() = ControlCenterAuditClient("http://127.0.0.1:1", "token")

    private fun server(handler: (com.sun.net.httpserver.HttpExchange) -> Unit): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange -> handler(exchange) }
        server.start()
        return server
    }

    private fun payload() = """
        {
          "entries":[
            {
              "ts":"2026-08-11T11:00:00",
              "conversation_id":"task-123",
              "tool":"note_append",
              "args_json":"TOP SECRET ARGUMENT",
              "risk":"write",
              "outcome":"executed",
              "confirmation_id":"confirm-123",
              "result_summary":"TOP SECRET RESULT",
              "duration_ms":12,
              "origin":"cloud"
            }
          ]
        }
    """.trimIndent()
}
