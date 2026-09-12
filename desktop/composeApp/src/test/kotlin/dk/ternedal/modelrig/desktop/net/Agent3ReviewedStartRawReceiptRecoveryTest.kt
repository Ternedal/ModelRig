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
import kotlin.test.assertTrue

class Agent3ReviewedStartRawReceiptRecoveryTest {
    @Test
    fun reviewedRecoveryRejectsDefaultableOrWrongTypedSameSnapshotReceiptFields() {
        val variants = listOf(
            receiptJson(includeAllowed = false),
            receiptJson(includeBlockers = false),
            receiptJson(includeProductionActivation = false),
            receiptJson(
                allowed = false,
                blockersJson = """[{"capability_id":7,"state":"degraded","reason":"wrong raw type"}]""",
            ),
        )

        variants.forEach { malformed ->
            val server = server(
                startEnvelope(receiptJson()),
                runEnvelope(malformed),
            )
            try {
                val error = assertFailsWith<Agent3Exception> {
                    client(server).startReviewedPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = true,
                        expectedCapabilityReceipt = receipt(),
                    )
                }

                assertTrue(error.message?.contains("same-snapshot capability evidence") == true)
                assertEquals(2, server.requests.size)
            } finally {
                server.stop()
            }
        }
    }

    @Test
    fun ordinaryRunEnvelopeKeepsPermissiveCapabilityReceiptCompatibility() {
        val server = server(runEnvelope(receiptJson(includeAllowed = false)))
        try {
            val envelope = client(server).getRunEnvelope(
                runId = "server-run",
                expectedReviewReads = true,
            )

            assertEquals("server-run", envelope.run.id)
            assertFalse(requireNotNull(envelope.capabilityReceipt).allowed)
            assertEquals(1, server.requests.size)
        } finally {
            server.stop()
        }
    }

    private fun client(server: QueueServer) = Agent3Client(server.baseUrl(), "token")

    private fun receipt(): Agent3CapabilityReceipt = Agent3CapabilityReceipt(
        schema = "kaliv-agent3-capability-receipt/v1",
        graphSha256 = "a".repeat(64),
        planSha256 = "b".repeat(64),
        route = "rig",
        allowed = true,
        requiredCapabilityIds = listOf("tool.read"),
        blockers = emptyList(),
        productionActivation = false,
    )

    private fun receiptJson(
        includeAllowed: Boolean = true,
        includeBlockers: Boolean = true,
        includeProductionActivation: Boolean = true,
        allowed: Boolean = true,
        blockersJson: String = "[]",
    ): String {
        val fields = buildList {
            add("\"schema\": \"kaliv-agent3-capability-receipt/v1\"")
            add("\"graph_sha256\": \"${"a".repeat(64)}\"")
            add("\"plan_sha256\": \"${"b".repeat(64)}\"")
            add("\"route\": \"rig\"")
            if (includeAllowed) add("\"allowed\": $allowed")
            add("\"required_capability_ids\": [\"tool.read\"]")
            if (includeBlockers) add("\"blockers\": $blockersJson")
            if (includeProductionActivation) add("\"production_activation\": false")
        }
        return "{\n  ${fields.joinToString(",\n  ")}\n}"
    }

    private fun startEnvelope(capabilityReceiptJson: String): String = """
        {
          "run": {
            "id": "server-run",
            "state": "completed",
            "current_step": 0,
            "steps": [],
            "answer": "rejected-start-payload"
          },
          "plan_id": "plan-1",
          "review_reads": true,
          "read_review": {"enabled":false,"waiting":false},
          "capability_receipt": $capabilityReceiptJson,
          ${terminationJson()}
        }
    """.trimIndent()

    private fun runEnvelope(capabilityReceiptJson: String): String = """
        {
          "run": {
            "id": "server-run",
            "state": "completed",
            "current_step": 0,
            "steps": [],
            "answer": "fresh-run-truth"
          },
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
