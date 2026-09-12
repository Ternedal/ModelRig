package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse

class Agent3StartReviewModeReceiptTest {
    @Test
    fun reviewedStartAcceptsMatchingTrueAndFalseReceipts() {
        listOf(true, false).forEach { expected ->
            val server = server(
                startEnvelope(
                    reviewReadsJson = expected.toString(),
                    readReviewEnabled = expected,
                )
            )
            try {
                val envelope = Agent3Client(server.baseUrl(), "token")
                    .startPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = expected,
                    )
                assertEquals("plan-1", envelope.planId)
                assertEquals(expected, envelope.reviewReads)
                assertEquals(expected, envelope.readReview.enabled)
            } finally {
                server.stop(0)
            }
        }
    }

    @Test
    fun reviewedStartRejectsBothReviewModeMismatchDirections() {
        listOf(
            true to false,
            false to true,
        ).forEach { (expected, returned) ->
            val server = server(
                startEnvelope(
                    reviewReadsJson = returned.toString(),
                    readReviewEnabled = returned,
                )
            )
            try {
                assertReceiptFailure(server, expected)
            } finally {
                server.stop(0)
            }
        }
    }

    @Test
    fun reviewedStartRejectsMissingNullStringAndNumberReceipts() {
        listOf<String?>(
            null,
            "null",
            "\"false\"",
            "0",
        ).forEach { responseValue ->
            val server = server(
                startEnvelope(
                    reviewReadsJson = responseValue,
                    readReviewEnabled = false,
                )
            )
            try {
                assertReceiptFailure(server, expected = false)
            } finally {
                server.stop(0)
            }
        }
    }

    @Test
    fun genericStartKeepsMissingReceiptCompatibility() {
        val server = server(
            startEnvelope(
                reviewReadsJson = null,
                readReviewEnabled = false,
            )
        )
        try {
            val envelope = Agent3Client(server.baseUrl(), "token")
                .startPlanEnvelope("plan-1")
            assertEquals("plan-1", envelope.planId)
            assertFalse(envelope.reviewReads)
            assertFalse(envelope.readReview.enabled)
        } finally {
            server.stop(0)
        }
    }

    private fun assertReceiptFailure(server: HttpServer, expected: Boolean) {
        val error = assertFailsWith<Agent3Exception> {
            Agent3Client(server.baseUrl(), "token")
                .startPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = expected,
                )
        }
        assertEquals(
            "Invalid Agent 3.0 Start envelope: server review_reads does not match reviewed intent",
            error.message,
        )
    }

    private fun server(body: String): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/v1/experimental/agent3") { exchange ->
            exchange.respond(200, body)
        }
        server.start()
        return server
    }

    private fun HttpServer.baseUrl(): String = "http://127.0.0.1:${address.port}"

    private fun HttpExchange.respond(status: Int, body: String) {
        val bytes = body.toByteArray(Charsets.UTF_8)
        responseHeaders.add("Content-Type", "application/json")
        sendResponseHeaders(status, bytes.size.toLong())
        responseBody.use { it.write(bytes) }
    }

    private fun startEnvelope(
        reviewReadsJson: String?,
        readReviewEnabled: Boolean,
    ): String {
        val reviewReadsField = reviewReadsJson?.let { "\"review_reads\":$it," }.orEmpty()
        return """
            {
              "run": {
                "id": "server-run",
                "state": "completed",
                "current_step": 0,
                "steps": []
              },
              "plan_id": "plan-1",
              $reviewReadsField
              "read_review": {
                "enabled": $readReviewEnabled,
                "waiting": false
              },
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
            }
        """.trimIndent()
    }
}
