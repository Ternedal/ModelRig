package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedStartBindingTest {
    @Test
    fun matchingCapabilityReceiptIsAccepted() {
        val receipt = receipt()
        val server = server(startEnvelope(capabilityReceiptJson = receiptJson()))
        try {
            val envelope = Agent3Client(server.url("/").toString(), "token")
                .startReviewedPlanEnvelope("plan-1", true, receipt)
            assertEquals(receipt, envelope.capabilityReceipt)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun matchingMissingCapabilityReceiptIsAccepted() {
        val server = server(startEnvelope())
        try {
            val envelope = Agent3Client(server.url("/").toString(), "token")
                .startReviewedPlanEnvelope("plan-1", true, null)
            assertNull(envelope.capabilityReceipt)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun changedCapabilityReceiptFailsClosed() {
        val expected = receipt()
        val server = server(startEnvelope(capabilityReceiptJson = receiptJson(route = "other-route")))
        try {
            assertReceiptFailure(
                server = server,
                expected = expected,
                expectedMessage = "Ugyldigt Agent 3.0 Start-svar: capability receipt matcher ikke previewet",
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun missingCapabilityReceiptFailsClosed() {
        val server = server(startEnvelope())
        try {
            assertReceiptFailure(
                server = server,
                expected = receipt(),
                expectedMessage = "Ugyldigt Agent 3.0 reviewed Start capability-evidence: receipt mangler",
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun unexpectedCapabilityReceiptFailsClosed() {
        val server = server(startEnvelope(capabilityReceiptJson = receiptJson()))
        try {
            assertReceiptFailure(
                server = server,
                expected = null,
                expectedMessage = "Ugyldigt Agent 3.0 reviewed Start capability-evidence: receipt var ikke forventet",
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedStartAcceptsMatchingReadReviewState() {
        listOf(true, false).forEach { expected ->
            val server = server(
                startEnvelope(
                    reviewReads = expected,
                    readReviewJson = "{\"enabled\":$expected,\"waiting\":false}",
                ),
            )
            try {
                val envelope = Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope("plan-1", expected, null)
                assertEquals(expected, envelope.readReview.enabled)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun reviewedStartFailsClosedWhenFreshReadReviewStillMismatches() {
        listOf(
            true to false,
            false to true,
        ).forEach { (expected, returned) ->
            val server = server(
                startEnvelope(
                    reviewReads = expected,
                    readReviewJson = "{\"enabled\":$returned,\"waiting\":false}",
                ),
            )
            try {
                assertReadReviewFailure(server, expected)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun reviewedStartFailsClosedWhenMissingReadReviewCannotBeRecovered() {
        val server = server(startEnvelope(reviewReads = true, readReviewJson = null))
        try {
            assertReadReviewFailure(server, true)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedStartFailsClosedWhenUnusableReadReviewCannotBeRecovered() {
        val server = server(
            startEnvelope(
                reviewReads = true,
                readReviewJson = "{\"enabled\":\"not-a-bool\",\"waiting\":false}",
            ),
        )
        try {
            assertReadReviewFailure(server, true)
        } finally {
            server.shutdown()
        }
    }

    private fun assertReceiptFailure(
        server: MockWebServer,
        expected: Agent3Client.CapabilityReceipt?,
        expectedMessage: String,
    ) {
        val error = runCatching {
            Agent3Client(server.url("/").toString(), "token")
                .startReviewedPlanEnvelope("plan-1", true, expected)
        }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertEquals(expectedMessage, error?.message)
    }

    private fun assertReadReviewFailure(server: MockWebServer, expected: Boolean) {
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody(
                    startEnvelope(
                        reviewReads = expected,
                        readReviewJson = "{\"enabled\":${!expected},\"waiting\":false}",
                    ),
                ),
        )
        val error = runCatching {
            Agent3Client(server.url("/").toString(), "token")
                .startReviewedPlanEnvelope("plan-1", expected, null)
        }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertTrue(
            error?.message?.contains(
                "Ugyldigt Agent 3.0 Start-svar: Read review-state matcher ikke previewet",
            ) == true,
        )
        assertTrue(error?.message?.contains("Frisk run-recovery fejlede") == true)
        assertEquals(2, server.requestCount)
    }

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

    private fun server(body: String): MockWebServer = MockWebServer().also { server ->
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody(body),
        )
        server.start()
    }

    private fun startEnvelope(
        capabilityReceiptJson: String? = null,
        reviewReads: Boolean = true,
        readReviewJson: String? = "{\"enabled\":true,\"waiting\":false}",
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
          ${readReviewJson?.let { "\"read_review\":$it," } ?: ""}
          ${capabilityReceiptJson?.let { "\"capability_receipt\":$it," } ?: ""}
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
