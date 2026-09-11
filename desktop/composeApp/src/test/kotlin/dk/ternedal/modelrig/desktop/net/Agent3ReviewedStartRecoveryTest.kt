package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.ArrayDeque
import java.util.Collections
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class Agent3ReviewedStartRecoveryTest {
    @Test
    fun rejectedParsedReviewStateRecoversFreshExactRunTruth() {
        val server = server(
            startEnvelope(
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                answer = "rejected-start-payload",
            ),
            runEnvelope(
                runId = "server-run",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
                answer = "fresh-server-truth",
            ),
        )
        try {
            val envelope = Agent3Client(server.baseUrl(), "token")
                .startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = null,
                )

            assertEquals("server-run", envelope.run.id)
            assertEquals("fresh-server-truth", envelope.run.answer)
            assertEquals(true, envelope.readReview.enabled)
            assertEquals(
                listOf(
                    "POST /api/v1/experimental/agent3/plans/plan-1/start",
                    "GET /api/v1/experimental/agent3/runs/server-run",
                ),
                server.requests,
            )
        } finally {
            server.stop()
        }
    }

    @Test
    fun capabilityMismatchNeverCreatesRecoveryAuthority() {
        val expected = receipt(route = "rig")
        val server = server(
            startEnvelope(
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(receipt(route = "other-route")),
            ),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3Client(server.baseUrl(), "token")
                    .startReviewedPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = true,
                        expectedCapabilityReceipt = expected,
                    )
            }
            assertEquals(
                "Invalid Agent 3.0 Start envelope: capability receipt does not match reviewed Preview",
                error.message,
            )
            assertEquals(
                listOf("POST /api/v1/experimental/agent3/plans/plan-1/start"),
                server.requests,
            )
        } finally {
            server.stop()
        }
    }

    @Test
    fun invalidFreshCheckpointFailsClosedWithoutRejectedPayloadFallback() {
        val server = server(
            startEnvelope(
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                answer = "rejected-start-payload",
            ),
            runEnvelope(
                runId = "server-run",
                readReviewJson = "{\"enabled\":true,\"waiting\":false,\"window_start\":1}",
                answer = "invalid-fresh-payload",
            ),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3Client(server.baseUrl(), "token")
                    .startReviewedPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = true,
                        expectedCapabilityReceipt = null,
                    )
            }
            assertTrue(
                error.message?.contains(
                    "Invalid Agent 3.0 Start envelope: read_review state does not match reviewed intent",
                ) == true,
            )
            assertTrue(error.message?.contains("Fresh run recovery failed") == true)
            assertTrue(error.message?.contains("stale cleared read_review checkpoint") == true)
            assertEquals(2, server.requests.size)
        } finally {
            server.stop()
        }
    }

    @Test
    fun reviewedGetEnvelopeBindsExactRunIdAndReviewMode() {
        val wrongRun = server(
            runEnvelope(
                runId = "other-run",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
            ),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3Client(wrongRun.baseUrl(), "token")
                    .getRunEnvelope("run-1", expectedReviewReads = true)
            }
            assertEquals(
                "Invalid Agent 3.0 run envelope: server returned another run id",
                error.message,
            )
        } finally {
            wrongRun.stop()
        }

        val wrongMode = server(
            runEnvelope(
                runId = "run-1",
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
            ),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3Client(wrongMode.baseUrl(), "token")
                    .getRunEnvelope("run-1", expectedReviewReads = true)
            }
            assertEquals(
                "Invalid Agent 3.0 run envelope: read_review state does not match reviewed run",
                error.message,
            )
        } finally {
            wrongMode.stop()
        }
    }

    private fun receipt(route: String): Agent3CapabilityReceipt = Agent3CapabilityReceipt(
        schema = "kaliv-agent3-capability-receipt/v1",
        graphSha256 = "a".repeat(64),
        planSha256 = "b".repeat(64),
        route = route,
        allowed = true,
        requiredCapabilityIds = listOf("tool.read"),
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
          "required_capability_ids": ["tool.read"],
          "blockers": [],
          "production_activation": false
        }
    """.trimIndent()

    private fun startEnvelope(
        readReviewJson: String,
        capabilityReceiptJson: String? = null,
        answer: String? = null,
    ): String {
        val capabilityField = capabilityReceiptJson
            ?.let { "\"capability_receipt\":$it," }
            .orEmpty()
        val answerField = answer?.let { "\"answer\":\"$it\"," }.orEmpty()
        return """
            {
              "run": {
                "id": "server-run",
                "state": "completed",
                "current_step": 0,
                $answerField
                "steps": []
              },
              "plan_id": "plan-1",
              "review_reads": true,
              "read_review": $readReviewJson,
              $capabilityField
              ${terminationJson()}
            }
        """.trimIndent()
    }

    private fun runEnvelope(
        runId: String,
        readReviewJson: String,
        answer: String? = null,
    ): String {
        val answerField = answer?.let { "\"answer\":\"$it\"," }.orEmpty()
        return """
            {
              "run": {
                "id": "$runId",
                "state": "completed",
                "current_step": 0,
                $answerField
                "steps": []
              },
              "review_reads": true,
              "read_review": $readReviewJson,
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
        val bytes = body.toByteArray(Charsets.UTF_8)
        responseHeaders.add("Content-Type", "application/json")
        sendResponseHeaders(status, bytes.size.toLong())
        responseBody.use { it.write(bytes) }
    }
}
