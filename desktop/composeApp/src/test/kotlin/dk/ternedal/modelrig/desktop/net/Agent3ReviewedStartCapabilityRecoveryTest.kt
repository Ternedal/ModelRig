package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.ArrayDeque
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class Agent3ReviewedStartCapabilityRecoveryTest {
    @Test
    fun postEnvelopeRecoveryPreservesPreviouslyReviewedCapabilityReceipt() {
        val reviewed = receipt(route = "rig-tools")
        val server = server(
            startEnvelope(
                reviewReads = true,
                readReviewEnabled = false,
                capabilityReceiptJson = receiptJson(reviewed),
            ),
            runEnvelope(readReviewEnabled = true),
        )
        try {
            val recovered = Agent3Client(server.baseUrl(), "token")
                .startReviewedPlanEnvelope("plan-1", true, reviewed)

            assertEquals("server-run", recovered.run.id)
            assertEquals(reviewed, recovered.capabilityReceipt)
            assertEquals(2, server.requestCount)
        } finally {
            server.stop()
        }
    }

    @Test
    fun rawModeRecoveryPreservesPreviouslyReviewedCapabilityReceipt() {
        val reviewed = receipt(route = "rig-tools")
        val server = server(
            startEnvelope(
                reviewReads = false,
                readReviewEnabled = false,
                capabilityReceiptJson = receiptJson(reviewed),
            ),
            runEnvelope(readReviewEnabled = true),
        )
        try {
            val recovered = Agent3Client(server.baseUrl(), "token")
                .startReviewedPlanEnvelope("plan-1", true, reviewed)

            assertEquals(reviewed, recovered.capabilityReceipt)
            assertEquals(2, server.requestCount)
        } finally {
            server.stop()
        }
    }

    @Test
    fun contradictoryFreshCapabilityReceiptFailsClosedInsteadOfBeingOverwritten() {
        val reviewed = receipt(route = "rig-tools")
        val contradictory = receipt(route = "other-route")
        val server = server(
            startEnvelope(
                reviewReads = true,
                readReviewEnabled = false,
                capabilityReceiptJson = receiptJson(reviewed),
            ),
            runEnvelope(
                readReviewEnabled = true,
                capabilityReceiptJson = receiptJson(contradictory),
            ),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3Client(server.baseUrl(), "token")
                    .startReviewedPlanEnvelope("plan-1", true, reviewed)
            }

            assertTrue(error.message?.contains("Fresh run recovery failed") == true)
            assertTrue(error.message?.contains("capability receipt contradicts reviewed Preview") == true)
            assertEquals(2, server.requestCount)
        } finally {
            server.stop()
        }
    }

    private fun receipt(route: String): Agent3CapabilityReceipt = Agent3CapabilityReceipt(
        schema = "kaliv-agent3-capability-receipt/v1",
        graphSha256 = "a".repeat(64),
        planSha256 = "b".repeat(64),
        route = route,
        allowed = true,
        requiredCapabilityIds = listOf("tools"),
        blockers = emptyList(),
        productionActivation = false,
    )

    private fun receiptJson(receipt: Agent3CapabilityReceipt): String = """
        {
          "schema": "${receipt.schema}",
          "graph_sha256": "${receipt.graphSha256}",
          "plan_sha256": "${receipt.planSha256}",
          "route": "${receipt.route}",
          "allowed": ${receipt.allowed},
          "required_capability_ids": ["tools"],
          "blockers": [],
          "production_activation": false
        }
    """.trimIndent()

    private fun startEnvelope(
        reviewReads: Boolean,
        readReviewEnabled: Boolean,
        capabilityReceiptJson: String,
    ): String = """
        {
          "run": {
            "id": "server-run",
            "state": "completed",
            "current_step": 0,
            "steps": []
          },
          "plan_id": "plan-1",
          "review_reads": $reviewReads,
          "read_review": {"enabled":$readReviewEnabled,"waiting":false},
          "capability_receipt": $capabilityReceiptJson,
          ${terminationJson()}
        }
    """.trimIndent()

    private fun runEnvelope(
        readReviewEnabled: Boolean,
        capabilityReceiptJson: String? = null,
    ): String {
        val capabilityField = capabilityReceiptJson
            ?.let { "\"capability_receipt\":$it," }
            .orEmpty()
        return """
            {
              "run": {
                "id": "server-run",
                "state": "completed",
                "current_step": 0,
                "steps": []
              },
              "read_review": {"enabled":$readReviewEnabled,"waiting":false},
              $capabilityField
              ${terminationJson()}
            }
        """.trimIndent()
    }

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
        var requestCount: Int = 0
            private set
        private val httpServer = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).also { server ->
            server.createContext("/api/v1/experimental/agent3") { exchange ->
                requestCount += 1
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
        val bytes = body.toByteArray(Charsets.UTF_8)
        responseHeaders.add("Content-Type", "application/json")
        sendResponseHeaders(status, bytes.size.toLong())
        responseBody.use { it.write(bytes) }
    }
}
