package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

class Agent3ReviewedStartCapabilityBindingTest {
    @Test
    fun reviewedStartAcceptsExactMatchingCapabilityReceipt() {
        val expected = receipt()
        val server = server(startEnvelope(capabilityReceiptJson = receiptJson(expected)))
        try {
            val envelope = Agent3Client(server.baseUrl(), "token")
                .startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = false,
                    expectedCapabilityReceipt = expected,
                )
            assertEquals(expected, envelope.capabilityReceipt)
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun reviewedStartAcceptsMatchingNullCapabilityReceipt() {
        val server = server(startEnvelope(capabilityReceiptJson = null))
        try {
            val envelope = Agent3Client(server.baseUrl(), "token")
                .startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = false,
                    expectedCapabilityReceipt = null,
                )
            assertNull(envelope.capabilityReceipt)
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun reviewedStartRejectsChangedCapabilityReceipt() {
        val expected = receipt()
        val returned = expected.copy(planSha256 = "c".repeat(64))
        val server = server(startEnvelope(capabilityReceiptJson = receiptJson(returned)))
        try {
            assertCapabilityFailure(
                server = server,
                expected = expected,
                expectedMessage = "Invalid Agent 3.0 Start envelope: capability receipt does not match reviewed Preview",
            )
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun reviewedStartRejectsMissingCapabilityReceipt() {
        val server = server(startEnvelope(capabilityReceiptJson = null))
        try {
            assertCapabilityFailure(
                server = server,
                expected = receipt(),
                expectedMessage = "Invalid Agent 3.0 reviewed Start capability evidence: receipt is missing",
            )
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun reviewedStartRejectsUnexpectedCapabilityReceipt() {
        val server = server(startEnvelope(capabilityReceiptJson = receiptJson(receipt())))
        try {
            assertCapabilityFailure(
                server = server,
                expected = null,
                expectedMessage = "Invalid Agent 3.0 reviewed Start capability evidence: receipt was not expected",
            )
        } finally {
            server.stop(0)
        }
    }

    private fun assertCapabilityFailure(
        server: HttpServer,
        expected: Agent3CapabilityReceipt?,
        expectedMessage: String,
    ) {
        val error = assertFailsWith<Agent3Exception> {
            Agent3Client(server.baseUrl(), "token")
                .startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = false,
                    expectedCapabilityReceipt = expected,
                )
        }
        assertEquals(expectedMessage, error.message)
    }

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

    private fun receiptJson(receipt: Agent3CapabilityReceipt): String = """
        {
          "schema": "${receipt.schema}",
          "graph_sha256": "${receipt.graphSha256}",
          "plan_sha256": "${receipt.planSha256}",
          "route": "${receipt.route}",
          "allowed": ${receipt.allowed},
          "required_capability_ids": [${receipt.requiredCapabilityIds.joinToString(",") { "\"$it\"" }}],
          "blockers": [],
          "production_activation": ${receipt.productionActivation}
        }
    """.trimIndent()

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

    private fun startEnvelope(capabilityReceiptJson: String?): String {
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
              "plan_id": "plan-1",
              "review_reads": false,
              "read_review": {
                "enabled": false,
                "waiting": false
              },
              $capabilityField
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
