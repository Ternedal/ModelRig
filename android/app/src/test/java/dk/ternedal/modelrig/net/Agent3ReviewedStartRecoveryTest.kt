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
    fun recoveryPreservesReviewedReceiptWhenCurrentGraphChangesButPlanMatches() {
        val expected = receipt()
        val server = server(
            startEnvelope(
                answer = "rejected-start-payload",
                reviewReads = true,
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(),
            ),
            runEnvelope(
                answer = "fresh-run-truth",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
            ),
            capabilityEvidenceJson(
                graphSha = "c".repeat(64),
                allowed = false,
                blockersJson = """[{"capability_id":"tools","state":"degraded","reason":"fresh graph changed"}]""",
            ),
        )
        try {
            val envelope = Agent3Client(server.url("/").toString(), "token")
                .startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = expected,
                )

            assertEquals(expected, envelope.capabilityReceipt)
            assertEquals("fresh-run-truth", envelope.run.answer)
            assertEquals(3, server.requestCount)
            assertEquals(
                listOf(
                    "/api/v1/experimental/agent3/plans/plan-1/start",
                    "/api/v1/experimental/agent3/runs/server-run",
                    "/api/v1/experimental/agent3/runs/server-run/capability-receipt",
                ),
                listOf(
                    server.takeRequest().path,
                    server.takeRequest().path,
                    server.takeRequest().path,
                ),
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun rawModeConflictRecoveryRebindsReviewedPlanBeforePreservingReceipt() {
        val expected = receipt()
        val server = server(
            startEnvelope(
                answer = "rejected-mode-start-payload",
                reviewReads = false,
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(),
            ),
            runEnvelope(
                answer = "fresh-reviewed-truth",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
            ),
            capabilityEvidenceJson(),
        )
        try {
            val envelope = Agent3Client(server.url("/").toString(), "token")
                .startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = expected,
                )

            assertEquals(expected, envelope.capabilityReceipt)
            assertEquals("fresh-reviewed-truth", envelope.run.answer)
            assertEquals(3, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun changedCurrentPlanDigestFailsClosed() {
        val expected = receipt()
        val server = server(
            startEnvelope(
                answer = "rejected-start-payload",
                reviewReads = true,
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(),
            ),
            runEnvelope(
                answer = "fresh-run-truth",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
            ),
            capabilityEvidenceJson(planSha = "d".repeat(64)),
        )
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = true,
                        expectedCapabilityReceipt = expected,
                    )
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("Frisk run-recovery fejlede") == true)
            assertTrue(error?.message?.contains("frisk run-plan matcher ikke previewet") == true)
            assertEquals(3, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun changedCurrentRequiredCapabilitiesFailClosed() {
        val expected = receipt()
        val server = server(
            startEnvelope(
                answer = "rejected-start-payload",
                reviewReads = true,
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(),
            ),
            runEnvelope(
                answer = "fresh-run-truth",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
            ),
            capabilityEvidenceJson(requiredIdsJson = "[\"tools\",\"rag\"]"),
        )
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = true,
                        expectedCapabilityReceipt = expected,
                    )
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("frisk run-plan matcher ikke previewet") == true)
            assertEquals(3, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun capabilityEvidenceBindsExactRunIdAndEvaluationFlags() {
        val cases = listOf(
            capabilityEvidenceJson(runId = "other-run") to "andet run-id",
            capabilityEvidenceJson(evaluated = false) to "evaluated/executed-binding",
            capabilityEvidenceJson(executed = true) to "evaluated/executed-binding",
        )
        cases.forEach { (body, expectedMessage) ->
            val server = server(body)
            try {
                val error = runCatching {
                    Agent3Client(server.url("/").toString(), "token")
                        .getRunCapabilityEvidence("server-run")
                }.exceptionOrNull()
                assertTrue(error is ModelRigException)
                assertTrue(error?.message?.contains(expectedMessage) == true)
                assertEquals(1, server.requestCount)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun contradictoryFreshCapabilityFailsClosedBeforePlanEvidenceRequest() {
        val expected = receipt()
        val server = server(
            startEnvelope(
                answer = "rejected-start-payload",
                reviewReads = true,
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(),
            ),
            runEnvelope(
                answer = "fresh-but-contradictory",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(route = "other-route"),
            ),
        )
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = true,
                        expectedCapabilityReceipt = expected,
                    )
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("Frisk run-recovery fejlede") == true)
            assertTrue(error?.message?.contains("capability receipt matcher ikke previewet") == true)
            assertEquals(2, server.requestCount)
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
              "read_review": $readReviewJson,
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

    private fun receipt(route: String = "rig-tools"): Agent3Client.CapabilityReceipt =
        Agent3Client.CapabilityReceipt(
            schema = "kaliv-agent3-capability-receipt/v1",
            graphSha256 = "a".repeat(64),
            planSha256 = "b".repeat(64),
            route = route,
            allowed = true,
            requiredCapabilityIds = listOf("tools"),
            blockers = emptyList(),
            productionActivation = false,
        )

    private fun receiptJson(route: String = "rig-tools"): String = """
        {
          "schema": "kaliv-agent3-capability-receipt/v1",
          "graph_sha256": "${"a".repeat(64)}",
          "plan_sha256": "${"b".repeat(64)}",
          "route": "$route",
          "allowed": true,
          "required_capability_ids": ["tools"],
          "blockers": [],
          "production_activation": false
        }
    """.trimIndent()

    private fun capabilityEvidenceJson(
        runId: String = "server-run",
        graphSha: String = "a".repeat(64),
        planSha: String = "b".repeat(64),
        route: String = "rig-tools",
        requiredIdsJson: String = "[\"tools\"]",
        allowed: Boolean = true,
        blockersJson: String = "[]",
        evaluated: Boolean = true,
        executed: Boolean = false,
    ): String = """
        {
          "run_id": "$runId",
          "run_state": "completed",
          "current_step": 0,
          "receipt": {
            "schema": "kaliv-agent3-capability-receipt/v1",
            "graph_sha256": "$graphSha",
            "plan_sha256": "$planSha",
            "route": "$route",
            "allowed": $allowed,
            "required_capability_ids": $requiredIdsJson,
            "blockers": $blockersJson,
            "production_activation": false
          },
          "evaluated": $evaluated,
          "executed": $executed
        }
    """.trimIndent()
}
