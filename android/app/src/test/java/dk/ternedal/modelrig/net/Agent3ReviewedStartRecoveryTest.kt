package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedStartRecoveryTest {
    @Test
    fun rejectedReadReviewStateRecoversFromFreshExactRunTruth() {
        val server = server(
            startEnvelope(
                answer = "rejected-start-payload",
                reviewReads = true,
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
            ),
            runEnvelope(
                answer = "fresh-run-truth",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
            ),
        )
        try {
            val envelope = Agent3Client(server.url("/").toString(), "token")
                .startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = null,
                )

            assertEquals("server-run", envelope.run.id)
            assertEquals("fresh-run-truth", envelope.run.answer)
            assertTrue(envelope.readReview.enabled)
            assertEquals(2, server.requestCount)
            assertEquals(
                "/api/v1/experimental/agent3/plans/plan-1/start",
                server.takeRequest().path,
            )
            assertEquals(
                "/api/v1/experimental/agent3/runs/server-run",
                server.takeRequest().path,
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun capabilityMismatchNeverUsesRunIdForRecovery() {
        val server = server(
            startEnvelope(
                answer = "must-not-become-authority",
                reviewReads = true,
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(),
            ),
        )
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope(
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
            assertEquals(
                "/api/v1/experimental/agent3/plans/plan-1/start",
                server.takeRequest().path,
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun freshRecoveryFailsClosedWhenCheckpointIsInvalid() {
        val server = server(
            startEnvelope(
                answer = "rejected-start-payload",
                reviewReads = true,
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
            ),
            runEnvelope(
                answer = "fresh-but-invalid",
                readReviewJson = "{\"enabled\":true,\"waiting\":false,\"window_start\":1}",
            ),
        )
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = true,
                        expectedCapabilityReceipt = null,
                    )
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("Frisk run-recovery fejlede") == true)
            assertTrue(error?.message?.contains("stale cleared Read review-checkpoint") == true)
            assertEquals(2, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

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

    private fun startEnvelope(
        answer: String,
        reviewReads: Boolean,
        readReviewJson: String,
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
                "steps": [],
                "answer": "$answer"
              },
              "plan_id": "plan-1",
              "review_reads": $reviewReads,
              "read_review": $readReviewJson,
              $capabilityField
              "termination": ${terminationJson()}
            }
        """.trimIndent()
    }

    private fun runEnvelope(
        answer: String,
        readReviewJson: String,
    ): String = """
        {
          "run": {
            "id": "server-run",
            "state": "completed",
            "current_step": 0,
            "steps": [],
            "answer": "$answer"
          },
          "read_review": $readReviewJson,
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
