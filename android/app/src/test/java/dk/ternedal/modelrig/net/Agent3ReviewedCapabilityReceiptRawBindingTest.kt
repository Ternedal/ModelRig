package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedCapabilityReceiptRawBindingTest {
    @Test
    fun reviewedPreviewRejectsDefaultableCapabilityReceiptButGenericPreviewRemainsCompatible() {
        val malformed = JSONObject(receiptJson(allowed = false)).apply { remove("allowed") }.toString()

        val reviewedServer = server(previewEnvelope(malformed, reviewReads = true))
        try {
            val error = runCatching {
                client(reviewedServer).previewPlan(message = "read", reviewReads = true)
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("reviewed Preview capability-evidence") == true)
            assertEquals(1, reviewedServer.requestCount)
        } finally {
            reviewedServer.shutdown()
        }

        val genericServer = server(previewEnvelope(malformed, reviewReads = false))
        try {
            val preview = client(genericServer).previewPlan(message = "read")
            assertFalse(requireNotNull(preview.capabilityReceipt).allowed)
            assertEquals(1, genericServer.requestCount)
        } finally {
            genericServer.shutdown()
        }
    }

    @Test
    fun reviewedPreviewAndStartRejectWrongRawCapabilityReceiptType() {
        val malformed = JSONObject(receiptJson(allowed = false))
            .put("allowed", "false")
            .toString()

        val previewServer = server(previewEnvelope(malformed, reviewReads = true))
        try {
            val error = runCatching {
                client(previewServer).previewPlan(message = "read", reviewReads = true)
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("reviewed Preview capability-evidence") == true)
            assertEquals(1, previewServer.requestCount)
        } finally {
            previewServer.shutdown()
        }

        val startServer = server(startEnvelope(malformed))
        try {
            val error = runCatching {
                client(startServer).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = receipt(allowed = false),
                )
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("reviewed Start capability-evidence") == true)
            assertEquals(1, startServer.requestCount)
        } finally {
            startServer.shutdown()
        }
    }

    @Test
    fun reviewedStartRejectsDefaultableReceiptBeforeTypedEqualityCouldAcceptIt() {
        val malformed = JSONObject(receiptJson(allowed = false)).apply { remove("allowed") }.toString()
        val server = server(startEnvelope(malformed))
        try {
            val error = runCatching {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
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
    fun reviewedStartRejectsPresentReceiptWhenReviewedPreviewHadNone() {
        val server = server(startEnvelope(receiptJson(allowed = true)))
        try {
            val error = runCatching {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = null,
                )
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertEquals(
                "Ugyldigt Agent 3.0 Start-svar: capability receipt matcher ikke previewet",
                error?.message,
            )
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedPreviewAndStartAcceptExplicitNullCapabilityReceipt() {
        val previewServer = server(previewEnvelope("null", reviewReads = true))
        try {
            val preview = client(previewServer).previewPlan(message = "read", reviewReads = true)
            assertNull(preview.capabilityReceipt)
            assertEquals(1, previewServer.requestCount)
        } finally {
            previewServer.shutdown()
        }

        val startServer = server(startEnvelope("null"))
        try {
            val envelope = client(startServer).startReviewedPlanEnvelope(
                planId = "plan-1",
                expectedReviewReads = true,
                expectedCapabilityReceipt = null,
            )
            assertNull(envelope.capabilityReceipt)
            assertEquals(1, startServer.requestCount)
        } finally {
            startServer.shutdown()
        }
    }

    @Test
    fun ordinaryStartKeepsPermissiveCapabilityReceiptCompatibility() {
        val malformed = JSONObject(receiptJson(allowed = false)).apply { remove("allowed") }.toString()
        val server = server(startEnvelope(malformed))
        try {
            val envelope = client(server).startPlanEnvelope("plan-1")
            assertFalse(requireNotNull(envelope.capabilityReceipt).allowed)
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    private fun client(server: MockWebServer) = Agent3Client(server.url("/").toString(), "token")

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

    private fun receipt(allowed: Boolean): Agent3Client.CapabilityReceipt =
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

    private fun receiptJson(allowed: Boolean): String = """
        {
          "schema": "kaliv-agent3-capability-receipt/v1",
          "graph_sha256": "${"a".repeat(64)}",
          "plan_sha256": "${"b".repeat(64)}",
          "route": "rig-tools",
          "allowed": $allowed,
          "required_capability_ids": ["tools"],
          "blockers": [],
          "production_activation": false
        }
    """.trimIndent()
}
