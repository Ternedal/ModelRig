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

class Agent3ReviewedStartRawModeRecoveryTest {
    @Test
    fun rawModeConflictRecoversOnlyFromFreshExpectedModeTruth() {
        val server = server(
            startEnvelope(reviewReads = false),
            runEnvelope(readReviewEnabled = true, answer = "fresh-truth"),
        )
        try {
            val envelope = Agent3Client(server.baseUrl(), "token")
                .startReviewedPlanEnvelope("plan-1", true, null)

            assertEquals("server-run", envelope.run.id)
            assertEquals("fresh-truth", envelope.run.answer)
            assertTrue(envelope.readReview.enabled)
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
    fun rawModeConflictRequiresExactPlanBeforeRecovery() {
        val server = server(startEnvelope(reviewReads = false, planId = "other-plan"))
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3Client(server.baseUrl(), "token")
                    .startReviewedPlanEnvelope("plan-1", true, null)
            }
            assertEquals("Invalid Agent 3.0 Start envelope: server returned another plan id", error.message)
            assertEquals(1, server.requests.size)
        } finally {
            server.stop()
        }
    }

    @Test
    fun rawModeConflictRequiresExactCapabilityBeforeRecovery() {
        val server = server(
            startEnvelope(
                reviewReads = false,
                capabilityReceiptJson = receiptJson(),
            ),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3Client(server.baseUrl(), "token")
                    .startReviewedPlanEnvelope("plan-1", true, null)
            }
            assertEquals(
                "Invalid Agent 3.0 reviewed Start capability evidence: receipt was not expected",
                error.message,
            )
            assertEquals(1, server.requests.size)
        } finally {
            server.stop()
        }
    }

    @Test
    fun freshWrongModeAfterRawConflictFailsClosedAndIsNeverAdopted() {
        val server = server(
            startEnvelope(reviewReads = false),
            runEnvelope(readReviewEnabled = false, answer = "wrong-mode-truth"),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3Client(server.baseUrl(), "token")
                    .startReviewedPlanEnvelope("plan-1", true, null)
            }
            assertTrue(error.message?.contains("recovery-only") == true)
            assertTrue(error.message?.contains("Fresh run recovery failed") == true)
            assertTrue(error.message?.contains("read_review state does not match reviewed run") == true)
            assertEquals(2, server.requests.size)
        } finally {
            server.stop()
        }
    }

    @Test
    fun ordinaryStartRemainsStrictOnRawModeConflict() {
        val server = server(startEnvelope(reviewReads = false))
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3Client(server.baseUrl(), "token")
                    .startPlanEnvelope("plan-1", expectedReviewReads = true)
            }
            assertEquals(
                "Invalid Agent 3.0 Start envelope: server review_reads does not match reviewed intent",
                error.message,
            )
            assertEquals(1, server.requests.size)
        } finally {
            server.stop()
        }
    }

    private fun startEnvelope(
        reviewReads: Boolean,
        planId: String = "plan-1",
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
              "plan_id": "$planId",
              "review_reads": $reviewReads,
              "read_review": {"enabled":$reviewReads,"waiting":false},
              $capabilityField
              ${terminationJson()}
            }
        """.trimIndent()
    }

    private fun runEnvelope(
        readReviewEnabled: Boolean,
        answer: String,
    ): String = """
        {
          "run": {
            "id": "server-run",
            "state": "completed",
            "current_step": 0,
            "steps": [],
            "answer": "$answer"
          },
          "read_review": {"enabled":$readReviewEnabled,"waiting":false},
          ${terminationJson()}
        }
    """.trimIndent()

    private fun receiptJson(): String = """
        {
          "schema": "kaliv-agent3-capability-receipt/v1",
          "graph_sha256": "${"a".repeat(64)}",
          "plan_sha256": "${"b".repeat(64)}",
          "route": "rig-tools",
          "allowed": true,
          "required_capability_ids": ["tools"],
          "blockers": [],
          "production_activation": false
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
        val bytes = body.toByteArray(Charsets.UTF_8)
        responseHeaders.add("Content-Type", "application/json")
        sendResponseHeaders(status, bytes.size.toLong())
        responseBody.use { it.write(bytes) }
    }
}
