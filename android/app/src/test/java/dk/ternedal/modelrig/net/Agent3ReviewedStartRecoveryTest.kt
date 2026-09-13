package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedStartRecoveryTest {
    @Test
    fun rejectedReadReviewStateRecoversFromFreshExactRunTruthWithoutReviewedReceipt() {
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
            val envelope = client(server).startReviewedPlanEnvelope(
                planId = "plan-1",
                expectedReviewReads = true,
                expectedCapabilityReceipt = null,
            )

            assertEquals("server-run", envelope.run.id)
            assertEquals("fresh-run-truth", envelope.run.answer)
            assertTrue(envelope.readReview.enabled)
            assertNull(envelope.capabilityReceipt)
            assertTwoRecoveryRequests(server)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun recoveryPreservesReviewedReceiptWhenCurrentGraphChangesButPlanMatches() {
        val expected = receipt()
        val current = receiptJson(
            graphSha = "c".repeat(64),
            allowed = false,
            blockersJson = """[{"capability_id":"tools","state":"degraded","reason":"fresh graph changed"}]""",
        )
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
                capabilityReceiptJson = current,
            ),
        )
        try {
            val envelope = client(server).startReviewedPlanEnvelope(
                planId = "plan-1",
                expectedReviewReads = true,
                expectedCapabilityReceipt = expected,
            )

            assertEquals(expected, envelope.capabilityReceipt)
            assertEquals("fresh-run-truth", envelope.run.answer)
            assertTwoRecoveryRequests(server)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun rawModeConflictUsesSameSnapshotPlanEvidence() {
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
                capabilityReceiptJson = receiptJson(),
            ),
        )
        try {
            val envelope = client(server).startReviewedPlanEnvelope(
                planId = "plan-1",
                expectedReviewReads = true,
                expectedCapabilityReceipt = expected,
            )

            assertEquals(expected, envelope.capabilityReceipt)
            assertEquals("fresh-reviewed-truth", envelope.run.answer)
            assertTwoRecoveryRequests(server)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun changedSameSnapshotPlanDigestFailsClosedBeforeAnyThirdRequest() {
        val server = recoveryServer(receiptJson(planSha = "d".repeat(64)))
        try {
            val error = runCatching {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = receipt(),
                )
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("Frisk run-recovery fejlede") == true)
            assertTrue(error?.message?.contains("frisk run-plan matcher ikke previewet") == true)
            assertEquals(2, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun changedSameSnapshotRouteOrRequiredCapabilitiesFailClosed() {
        val variants = listOf(
            receiptJson(route = "other-route"),
            receiptJson(requiredIdsJson = "[\"tools\",\"rag\"]"),
        )
        variants.forEach { current ->
            val server = recoveryServer(current)
            try {
                val error = runCatching {
                    client(server).startReviewedPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = true,
                        expectedCapabilityReceipt = receipt(),
                    )
                }.exceptionOrNull()
                assertTrue(error is ModelRigException)
                assertTrue(error?.message?.contains("frisk run-plan matcher ikke previewet") == true)
                assertEquals(2, server.requestCount)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun missingSameSnapshotEvidenceFailsClosedWhenReviewedReceiptExists() {
        val server = server(
            startEnvelope(
                answer = "rejected-start-payload",
                reviewReads = true,
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(),
            ),
            runEnvelope(
                answer = "fresh-without-evidence",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
            ),
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
            assertTrue(error?.message?.contains("same-snapshot capability evidence mangler") == true)
            assertEquals(2, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun currentReceiptDoesNotInventHistoricalAuthorityWhenReviewedReceiptWasNull() {
        val server = server(
            startEnvelope(
                answer = "rejected-start-payload",
                reviewReads = true,
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
            ),
            runEnvelope(
                answer = "fresh-run-truth",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(),
            ),
        )
        try {
            val envelope = client(server).startReviewedPlanEnvelope(
                planId = "plan-1",
                expectedReviewReads = true,
                expectedCapabilityReceipt = null,
            )

            assertNull(envelope.capabilityReceipt)
            assertEquals("fresh-run-truth", envelope.run.answer)
            assertTwoRecoveryRequests(server)
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
                client(server).startReviewedPlanEnvelope(
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

    private fun recoveryServer(currentReceipt: String): MockWebServer = server(
        startEnvelope(
            answer = "rejected-start-payload",
            reviewReads = true,
            readReviewJson = "{\"enabled\":false,\"waiting\":false}",
            capabilityReceiptJson = receiptJson(),
        ),
        runEnvelope(
            answer = "fresh-run-truth",
            readReviewJson = "{\"enabled\":true,\"waiting\":false}",
            capabilityReceiptJson = currentReceipt,
        ),
    )

    private fun client(server: MockWebServer) =
        Agent3Client(server.url("/").toString(), "token")

    private fun assertTwoRecoveryRequests(server: MockWebServer) {
        assertEquals(2, server.requestCount)
        assertEquals(
            "/api/v1/experimental/agent3/plans/plan-1/start",
            server.takeRequest().path,
        )
        assertEquals(
            "/api/v1/experimental/agent3/runs/server-run",
            server.takeRequest().path,
        )
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

    private fun receiptJson(
        graphSha: String = "a".repeat(64),
        planSha: String = "b".repeat(64),
        route: String = "rig-tools",
        requiredIdsJson: String = "[\"tools\"]",
        allowed: Boolean = true,
        blockersJson: String = "[]",
    ): String = """
        {
          "schema": "kaliv-agent3-capability-receipt/v1",
          "graph_sha256": "$graphSha",
          "plan_sha256": "$planSha",
          "route": "$route",
          "allowed": $allowed,
          "required_capability_ids": $requiredIdsJson,
          "blockers": $blockersJson,
          "production_activation": false
        }
    """.trimIndent()
}
