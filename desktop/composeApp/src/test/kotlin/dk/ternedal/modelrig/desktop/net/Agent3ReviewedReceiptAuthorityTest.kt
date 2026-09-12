package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class Agent3ReviewedReceiptAuthorityTest {
    @Test
    fun reviewedPreviewRejectsDefaultableCapabilityReceiptBeforeDtoParsing() {
        val fixture = server(previewEnvelope(receiptJson(includeAllowed = false), reviewReads = true))
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(fixture).previewPlan(message = "review this", reviewReads = true)
            }
            assertTrue(error.message?.contains("reviewed Preview capability evidence") == true)
            assertEquals(1, fixture.requests)
        } finally {
            fixture.server.stop(0)
        }
    }

    @Test
    fun genericPreviewKeepsPermissiveCapabilityReceiptCompatibility() {
        val fixture = server(previewEnvelope(receiptJson(includeAllowed = false), reviewReads = false))
        try {
            val preview = client(fixture).previewPlan(message = "generic preview")
            assertFalse(requireNotNull(preview.capabilityReceipt).allowed)
            assertEquals(1, fixture.requests)
        } finally {
            fixture.server.stop(0)
        }
    }

    @Test
    fun reviewedStartRejectsDefaultableReceiptBeforeTypedEquality() {
        val fixture = server(startEnvelope(receiptJson(includeAllowed = false)))
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(fixture).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = false,
                    expectedCapabilityReceipt = receipt(allowed = false),
                )
            }
            assertTrue(error.message?.contains("reviewed Start capability evidence") == true)
            assertEquals(1, fixture.requests)
        } finally {
            fixture.server.stop(0)
        }
    }

    @Test
    fun reviewedStartRejectsUnexpectedRawReceiptBeforeBaselineDtoAuthority() {
        val fixture = server(startEnvelope(receiptJson()))
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(fixture).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = false,
                    expectedCapabilityReceipt = null,
                )
            }
            assertTrue(error.message?.contains("receipt was not expected") == true)
            assertEquals(1, fixture.requests)
        } finally {
            fixture.server.stop(0)
        }
    }

    @Test
    fun reviewedStartRejectsWrongRawBlockerFieldType() {
        val malformed = receiptJson(
            allowed = false,
            blockers = """[{"capability_id":7,"state":"blocked","reason":"fixture"}]""",
        )
        val fixture = server(startEnvelope(malformed))
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(fixture).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = false,
                    expectedCapabilityReceipt = receipt(allowed = false),
                )
            }
            assertTrue(error.message?.contains("blocker is incomplete") == true)
            assertEquals(1, fixture.requests)
        } finally {
            fixture.server.stop(0)
        }
    }

    @Test
    fun ordinaryStartKeepsPermissiveCapabilityReceiptCompatibility() {
        val fixture = server(startEnvelope(receiptJson(includeAllowed = false)))
        try {
            val envelope = client(fixture).startPlanEnvelope("plan-1")
            assertFalse(requireNotNull(envelope.capabilityReceipt).allowed)
            assertEquals(1, fixture.requests)
        } finally {
            fixture.server.stop(0)
        }
    }

    private fun client(fixture: Fixture) = Agent3Client(fixture.baseUrl(), "token")

    private data class Fixture(
        val server: HttpServer,
        var requests: Int = 0,
    ) {
        fun baseUrl(): String = "http://127.0.0.1:${server.address.port}"
    }

    private fun server(responseBody: String): Fixture {
        lateinit var fixture: Fixture
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        fixture = Fixture(server)
        server.createContext("/api/v1/experimental/agent3") { exchange ->
            fixture.requests += 1
            exchange.requestBody.use { it.readBytes() }
            exchange.respond(200, responseBody)
        }
        server.start()
        return fixture
    }

    private fun receipt(allowed: Boolean = true): Agent3CapabilityReceipt = Agent3CapabilityReceipt(
        schema = "kaliv-agent3-capability-receipt/v1",
        graphSha256 = "a".repeat(64),
        planSha256 = "b".repeat(64),
        route = "rig-tools",
        allowed = allowed,
        requiredCapabilityIds = listOf("tools"),
        blockers = emptyList(),
        productionActivation = false,
    )

    private fun receiptJson(
        allowed: Boolean = true,
        includeAllowed: Boolean = true,
        blockers: String = "[]",
    ): String {
        val allowedField = if (includeAllowed) "\"allowed\": $allowed," else ""
        return """
            {
              "schema": "kaliv-agent3-capability-receipt/v1",
              "graph_sha256": "${"a".repeat(64)}",
              "plan_sha256": "${"b".repeat(64)}",
              "route": "rig-tools",
              $allowedField
              "required_capability_ids": ["tools"],
              "blockers": $blockers,
              "production_activation": false
            }
        """.trimIndent()
    }

    private fun previewEnvelope(receipt: String, reviewReads: Boolean): String = """
        {
          "plan_id": "plan-1",
          "review_reads": $reviewReads,
          "capability_receipt": $receipt
        }
    """.trimIndent()

    private fun startEnvelope(receipt: String): String = """
        {
          "run": {
            "id": "server-run",
            "state": "completed",
            "current_step": 0,
            "steps": []
          },
          "plan_id": "plan-1",
          "review_reads": false,
          "read_review": {"enabled":false,"waiting":false},
          "capability_receipt": $receipt,
          "termination": ${terminationJson()}
        }
    """.trimIndent()

    private fun terminationJson(): String = """
        {
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

    private fun HttpExchange.respond(status: Int, body: String) {
        val bytes = body.toByteArray(Charsets.UTF_8)
        responseHeaders.add("Content-Type", "application/json")
        sendResponseHeaders(status, bytes.size.toLong())
        responseBody.use { it.write(bytes) }
    }
}
