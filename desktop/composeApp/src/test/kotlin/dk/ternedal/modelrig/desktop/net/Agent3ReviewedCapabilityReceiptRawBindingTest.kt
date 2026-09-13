package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.ArrayDeque
import java.util.Collections
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReviewedCapabilityReceiptRawBindingTest {
    @Test
    fun reviewedPreviewRejectsDefaultableCapabilityReceiptButGenericPreviewRemainsCompatible() {
        val malformed = receiptJson(includeAllowed = false, allowed = false)

        val reviewedServer = server(previewEnvelope(malformed, reviewReads = true))
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(reviewedServer).previewPlan(message = "read", reviewReads = true)
            }
            assertTrue(error.message?.contains("reviewed Preview capability evidence") == true)
            assertEquals(1, reviewedServer.requests.size)
        } finally {
            reviewedServer.stop()
        }

        val genericServer = server(previewEnvelope(malformed, reviewReads = false))
        try {
            val preview = client(genericServer).previewPlan(message = "read")
            assertFalse(requireNotNull(preview.capabilityReceipt).allowed)
            assertEquals(1, genericServer.requests.size)
        } finally {
            genericServer.stop()
        }
    }

    @Test
    fun reviewedPreviewAndStartRejectWrongRawCapabilityReceiptType() {
        val malformed = receiptJson(allowed = false)
            .replace("\"allowed\": false", "\"allowed\": \"false\"")

        val previewServer = server(previewEnvelope(malformed, reviewReads = true))
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(previewServer).previewPlan(message = "read", reviewReads = true)
            }
            assertTrue(error.message?.contains("reviewed Preview capability evidence") == true)
            assertEquals(1, previewServer.requests.size)
        } finally {
            previewServer.stop()
        }

        val startServer = server(startEnvelope(malformed))
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(startServer).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = receipt(allowed = false),
                )
            }
            assertTrue(error.message?.contains("reviewed Start capability evidence") == true)
            assertEquals(1, startServer.requests.size)
        } finally {
            startServer.stop()
        }
    }

    @Test
    fun reviewedStartRejectsDefaultableReceiptBeforeTypedEqualityCouldAcceptIt() {
        val malformed = receiptJson(includeAllowed = false, allowed = false)
        val server = server(startEnvelope(malformed))
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = receipt(allowed = false),
                )
            }

            assertTrue(error.message?.contains("reviewed Start capability evidence") == true)
            assertEquals(1, server.requests.size)
        } finally {
            server.stop()
        }
    }

    @Test
    fun reviewedStartRejectsPresentReceiptWhenReviewedPreviewHadNone() {
        val server = server(startEnvelope(receiptJson(allowed = true)))
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = null,
                )
            }

            assertEquals(
                "Invalid Agent 3.0 Start envelope: capability receipt does not match reviewed Preview",
                error.message,
            )
            assertEquals(1, server.requests.size)
        } finally {
            server.stop()
        }
    }

    @Test
    fun reviewedPreviewAndStartAcceptExplicitNullCapabilityReceipt() {
        val previewServer = server(previewEnvelope("null", reviewReads = true))
        try {
            val preview = client(previewServer).previewPlan(message = "read", reviewReads = true)
            assertNull(preview.capabilityReceipt)
            assertEquals(1, previewServer.requests.size)
        } finally {
            previewServer.stop()
        }

        val startServer = server(startEnvelope("null"))
        try {
            val envelope = client(startServer).startReviewedPlanEnvelope(
                planId = "plan-1",
                expectedReviewReads = true,
                expectedCapabilityReceipt = null,
            )
            assertNull(envelope.capabilityReceipt)
            assertEquals(1, startServer.requests.size)
        } finally {
            startServer.stop()
        }
    }

    @Test
    fun ordinaryStartKeepsPermissiveCapabilityReceiptCompatibility() {
        val server = server(startEnvelope(receiptJson(includeAllowed = false, allowed = false)))
        try {
            val envelope = client(server).startPlanEnvelope("plan-1")
            assertFalse(requireNotNull(envelope.capabilityReceipt).allowed)
            assertEquals(1, server.requests.size)
        } finally {
            server.stop()
        }
    }

    private fun client(server: QueueServer) = Agent3Client(server.baseUrl(), "token")

    private fun receipt(allowed: Boolean): Agent3CapabilityReceipt = Agent3CapabilityReceipt(
        schema = "kaliv-agent3-capability-receipt/v1",
        graphSha256 = "a".repeat(64),
        planSha256 = "b".repeat(64),
        route = "rig",
        allowed = allowed,
        requiredCapabilityIds = listOf("tool.read"),
        blockers = emptyList(),
        productionActivation = false,
    )

    private fun receiptJson(
        includeAllowed: Boolean = true,
        allowed: Boolean = true,
    ): String {
        val fields = buildList {
            add("\"schema\": \"kaliv-agent3-capability-receipt/v1\"")
            add("\"graph_sha256\": \"${"a".repeat(64)}\"")
            add("\"plan_sha256\": \"${"b".repeat(64)}\"")
            add("\"route\": \"rig\"")
            if (includeAllowed) add("\"allowed\": $allowed")
            add("\"required_capability_ids\": [\"tool.read\"]")
            add("\"blockers\": []")
            add("\"production_activation\": false")
        }
        return "{\n  ${fields.joinToString(",\n  ")}\n}"
    }

    private fun previewEnvelope(capabilityReceiptJson: String, reviewReads: Boolean): String = """
        {
          "plan_id": "plan-1",
          "expires_in_seconds": 30,
          "route": {"kind":"rig"},
          "rationale": "fixture",
          "plan": [],
          "executed": false,
          "memory_context": {},
          "capability_receipt": $capabilityReceiptJson,
          "review_reads": $reviewReads
        }
    """.trimIndent()

    private fun startEnvelope(capabilityReceiptJson: String): String = """
        {
          "run": {
            "id": "server-run",
            "state": "completed",
            "current_step": 0,
            "steps": [],
            "answer": "done"
          },
          "plan_id": "plan-1",
          "review_reads": true,
          "read_review": {"enabled":true,"waiting":false},
          "capability_receipt": $capabilityReceiptJson,
          ${terminationJson()}
        }
    """.trimIndent()

    private fun terminationJson(): String = """
        "termination": {
          "schema": "kaliv-agent3-termination/v1",
          "plan": {
            "state": "terminal",
            "can_request": false,
            "request_scope": "plan",
            "effect": "prevent_future_steps",
            "reason": "fixture"
          },
          "model_stream": {
            "state": "not_active",
            "active": false,
            "can_request": false,
            "handle_present": false,
            "reason": "fixture"
          },
          "active_tool": null,
          "production_activation": false
        }
    """.trimIndent()

    private fun server(vararg bodies: String): QueueServer = QueueServer(bodies.toList())

    private inner class QueueServer(bodies: List<String>) {
        private val responses = ArrayDeque(bodies)
        val requests: MutableList<String> = Collections.synchronizedList(mutableListOf())
        private val httpServer = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).also { server ->
            server.createContext("/api/v1/experimental/agent3") { exchange ->
                requests += "${exchange.requestMethod} ${exchange.requestURI.path}"
                val body = synchronized(responses) {
                    if (responses.isEmpty()) null else responses.removeFirst()
                }
                if (body == null) {
                    exchange.respond(500, "no fixture response queued")
                } else {
                    exchange.respond(200, body)
                }
            }
            server.start()
        }

        fun baseUrl(): String = "http://127.0.0.1:${httpServer.address.port}"

        fun stop() = httpServer.stop(0)
    }

    private fun HttpExchange.respond(status: Int, body: String) {
        val bytes = body.toByteArray()
        responseHeaders.add("Content-Type", "application/json")
        sendResponseHeaders(status, bytes.size.toLong())
        responseBody.use { it.write(bytes) }
    }
}
