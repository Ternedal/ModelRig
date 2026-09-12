package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedReceiptAuthorityTest {
    @Test
    fun reviewedPreviewRejectsDefaultableCapabilityReceiptBeforeDtoParsing() {
        val malformed = JSONObject(receiptJson()).apply { remove("allowed") }.toString()
        val server = server(previewEnvelope(malformed, reviewReads = true))
        try {
            val error = runCatching {
                client(server).previewPlan(message = "review this", reviewReads = true)
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("reviewed Preview capability-evidence") == true)
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun genericPreviewKeepsPermissiveCapabilityReceiptCompatibility() {
        val compatible = JSONObject(receiptJson()).apply { remove("allowed") }.toString()
        val server = server(previewEnvelope(compatible, reviewReads = false))
        try {
            val preview = client(server).previewPlan(message = "generic preview")
            assertFalse(requireNotNull(preview.capabilityReceipt).allowed)
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedStartRejectsDefaultableReceiptBeforeTypedEquality() {
        val malformed = JSONObject(receiptJson()).apply { remove("allowed") }.toString()
        val server = server(startEnvelope(malformed))
        try {
            val error = runCatching {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = false,
                    expectedCapabilityReceipt = receipt(allowed = false),
                )
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("reviewed Start capability-evidence") == true)
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedStartRejectsUnexpectedRawReceiptBeforeBaselineDtoAuthority() {
        val server = server(startEnvelope(receiptJson()))
        try {
            val error = runCatching {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = false,
                    expectedCapabilityReceipt = null,
                )
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("receipt var ikke forventet") == true)
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedStartRejectsWrongRawBlockerFieldType() {
        val malformed = JSONObject(receiptJson(allowed = false, blockers = """[{"capability_id":7,"state":"blocked","reason":"fixture"}]"""))
            .toString()
        val server = server(startEnvelope(malformed))
        try {
            val error = runCatching {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = false,
                    expectedCapabilityReceipt = receipt(allowed = false),
                )
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("blocker er ufuldstændig") == true)
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun ordinaryStartKeepsPermissiveCapabilityReceiptCompatibility() {
        val compatible = JSONObject(receiptJson()).apply { remove("allowed") }.toString()
        val server = server(startEnvelope(compatible))
        try {
            val envelope = client(server).startPlanEnvelope("plan-1")
            assertFalse(requireNotNull(envelope.capabilityReceipt).allowed)
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    private fun client(server: MockWebServer) =
        Agent3Client(server.url("/").toString(), "token")

    private fun server(vararg bodies: String): MockWebServer = MockWebServer().also { server ->
        bodies.forEach { body ->
            server.enqueue(
                MockResponse()
                    .setHeader("Content-Type", "application/json")
                    .setBody(body),
            )
        }
        server.start()
    }

    private fun receipt(allowed: Boolean = true): Agent3Client.CapabilityReceipt =
        Agent3Client.CapabilityReceipt(
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
        blockers: String = "[]",
    ): String = """
        {
          "schema": "kaliv-agent3-capability-receipt/v1",
          "graph_sha256": "${"a".repeat(64)}",
          "plan_sha256": "${"b".repeat(64)}",
          "route": "rig-tools",
          "allowed": $allowed,
          "required_capability_ids": ["tools"],
          "blockers": $blockers,
          "production_activation": false
        }
    """.trimIndent()

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
}
