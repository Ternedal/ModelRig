package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

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
            val recovered = Agent3Client(server.url("/").toString(), "token")
                .startReviewedPlanEnvelope("plan-1", true, reviewed)

            assertEquals("server-run", recovered.run.id)
            assertEquals(reviewed, recovered.capabilityReceipt)
            assertEquals(2, server.requestCount)
        } finally {
            server.shutdown()
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
            val recovered = Agent3Client(server.url("/").toString(), "token")
                .startReviewedPlanEnvelope("plan-1", true, reviewed)

            assertEquals(reviewed, recovered.capabilityReceipt)
            assertEquals(2, server.requestCount)
        } finally {
            server.shutdown()
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
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope("plan-1", true, reviewed)
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("Frisk run-recovery fejlede") == true)
            assertTrue(error?.message?.contains("capability receipt modsiger previewet") == true)
            assertEquals(2, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    private fun receipt(route: String): Agent3Client.CapabilityReceipt = Agent3Client.CapabilityReceipt(
        schema = "kaliv-agent3-capability-receipt/v1",
        graphSha256 = "a".repeat(64),
        planSha256 = "b".repeat(64),
        route = route,
        allowed = true,
        requiredCapabilityIds = listOf("tools"),
        blockers = emptyList(),
        productionActivation = false,
    )

    private fun receiptJson(receipt: Agent3Client.CapabilityReceipt): String = """
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
          "termination": ${terminationJson()}
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
              "termination": ${terminationJson()}
            }
        """.trimIndent()
    }

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
}
