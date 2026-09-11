package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedStartRawModeRecoveryTest {
    @Test
    fun rawModeConflictRecoversOnlyFromFreshExactReviewedTruth() {
        val server = server(
            startEnvelope(
                rawReviewReads = false,
                readReviewEnabled = false,
                answer = "rejected-start-payload",
            ),
            runEnvelope(
                runId = "server-run",
                rawReviewReads = true,
                readReviewEnabled = true,
                answer = "fresh-reviewed-truth",
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
            assertEquals("fresh-reviewed-truth", envelope.run.answer)
            assertTrue(envelope.reviewReads)
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
    fun rawModeConflictCannotExposeRunIdBeforeExactCapabilityBinding() {
        val expected = receipt(route = "rig")
        val server = server(
            startEnvelope(
                rawReviewReads = false,
                readReviewEnabled = false,
                capabilityReceiptJson = receiptJson(receipt(route = "other-route")),
            ),
            runEnvelope(
                runId = "server-run",
                rawReviewReads = true,
                readReviewEnabled = true,
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
    fun rawModeConflictCannotCreateRecoveryReferenceFromWrongPlan() {
        val server = server(
            startEnvelope(
                rawReviewReads = false,
                readReviewEnabled = false,
                planId = "other-plan",
            ),
            runEnvelope(
                runId = "server-run",
                rawReviewReads = true,
                readReviewEnabled = true,
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
                "Ugyldigt Agent 3.0 Start-svar: serveren returnerede et andet plan-id",
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
    fun freshParsedReviewMatchCannotOverrideFreshRawModeConflict() {
        val server = server(
            startEnvelope(
                rawReviewReads = false,
                readReviewEnabled = false,
            ),
            runEnvelope(
                runId = "server-run",
                rawReviewReads = false,
                readReviewEnabled = true,
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
            assertTrue(
                error?.message?.contains(
                    "Ugyldigt Agent 3.0 Start-svar: serverens Read review matcher ikke previewet",
                ) == true,
            )
            assertTrue(error?.message?.contains("Frisk run-recovery fejlede") == true)
            assertTrue(
                error?.message?.contains(
                    "Ugyldigt Agent 3.0 run-svar: serverens Read review matcher ikke runnet",
                ) == true,
            )
            assertEquals(2, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun ordinaryStartStillFailsImmediatelyOnRawModeConflict() {
        val server = server(
            startEnvelope(
                rawReviewReads = false,
                readReviewEnabled = false,
            ),
            runEnvelope(
                runId = "server-run",
                rawReviewReads = true,
                readReviewEnabled = true,
            ),
        )
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = true,
                    )
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertEquals(
                "Ugyldigt Agent 3.0 Start-svar: serverens Read review matcher ikke previewet",
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

    private fun receipt(route: String): Agent3Client.CapabilityReceipt = Agent3Client.CapabilityReceipt(
        schema = "kaliv-agent3-capability-receipt/v1",
        graphSha256 = "a".repeat(64),
        planSha256 = "b".repeat(64),
        route = route,
        allowed = true,
        requiredCapabilityIds = listOf("tool.read"),
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
          "required_capability_ids": ["tool.read"],
          "blockers": [],
          "production_activation": false
        }
    """.trimIndent()

    private fun startEnvelope(
        rawReviewReads: Boolean,
        readReviewEnabled: Boolean,
        planId: String = "plan-1",
        capabilityReceiptJson: String? = null,
        answer: String? = null,
    ): String {
        val capabilityField = capabilityReceiptJson
            ?.let { "\"capability_receipt\":$it," }
            .orEmpty()
        val answerField = answer?.let { "\"answer\":\"$it\"," }.orEmpty()
        return """
            {
              "run": {
                "id": "server-run",
                "state": "completed",
                "current_step": 0,
                "steps": [],
                $answerField
                "request": {}
              },
              "plan_id": "$planId",
              "review_reads": $rawReviewReads,
              "read_review": {"enabled":$readReviewEnabled,"waiting":false},
              $capabilityField
              "termination": ${terminationJson()}
            }
        """.trimIndent()
    }

    private fun runEnvelope(
        runId: String,
        rawReviewReads: Boolean,
        readReviewEnabled: Boolean,
        answer: String? = null,
    ): String {
        val answerField = answer?.let { "\"answer\":\"$it\"," }.orEmpty()
        return """
            {
              "run": {
                "id": "$runId",
                "state": "completed",
                "current_step": 0,
                "steps": [],
                $answerField
                "request": {}
              },
              "review_reads": $rawReviewReads,
              "read_review": {"enabled":$readReviewEnabled,"waiting":false},
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
