package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedStartRawReceiptRecoveryTest {
    @Test
    fun reviewedRecoveryRejectsDefaultableOrCoercibleSameSnapshotReceiptFields() {
        val valid = JSONObject(receiptJson())
        val variants = listOf(
            JSONObject(valid.toString()).apply { remove("allowed") }.toString(),
            JSONObject(valid.toString()).apply { remove("blockers") }.toString(),
            JSONObject(valid.toString()).apply {
                put("allowed", false)
                put(
                    "blockers",
                    JSONArray().put(
                        JSONObject()
                            .put("capability_id", 7)
                            .put("state", "degraded")
                            .put("reason", "wrong raw type"),
                    ),
                )
            }.toString(),
        )

        variants.forEach { malformed ->
            val server = server(
                startEnvelope(receiptJson()),
                runEnvelope(malformed),
            )
            try {
                val error = runCatching {
                    client(server).startReviewedPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = true,
                        expectedCapabilityReceipt = receipt(),
                    )
                }.exceptionOrNull()

                assertTrue(error is ModelRigException)
                assertTrue(error?.message?.contains("same-snapshot capability-evidence") == true)
                assertEquals(2, server.requestCount)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun ordinaryRunEnvelopeKeepsPermissiveCapabilityReceiptCompatibility() {
        val compatible = JSONObject(receiptJson()).apply { remove("allowed") }.toString()
        val server = server(runEnvelope(compatible))
        try {
            val envelope = client(server).getRunEnvelope(
                runId = "server-run",
                expectedReviewReads = true,
            )

            assertEquals("server-run", envelope.run.id)
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
          "termination": ${terminationJson()}
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

    private fun receipt(): Agent3Client.CapabilityReceipt =
        Agent3Client.CapabilityReceipt(
            schema = "kaliv-agent3-capability-receipt/v1",
            graphSha256 = "a".repeat(64),
            planSha256 = "b".repeat(64),
            route = "rig-tools",
            allowed = true,
            requiredCapabilityIds = listOf("tools"),
            blockers = emptyList(),
            productionActivation = false,
        )

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
}
