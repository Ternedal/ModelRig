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
        val server = server(startEnvelope(capabilityReceiptJson = receiptJson(route = "other-route")))
        try {
            assertReceiptFailure(server, receipt())
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun missingCapabilityReceiptFailsClosed() {
        val server = server(startEnvelope())
        try {
            assertReceiptFailure(server, receipt())
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun unexpectedCapabilityReceiptFailsClosed() {
        val server = server(startEnvelope(capabilityReceiptJson = receiptJson()))
        try {
            assertReceiptFailure(server, null)
        } finally {
            server.shutdown()
        }
    }

    private fun assertReceiptFailure(
        server: MockWebServer,
        expected: Agent3Client.CapabilityReceipt?,
    ) {
        val error = runCatching {
            Agent3Client(server.url("/").toString(), "token")
                .startReviewedPlanEnvelope("plan-1", true, expected)
        }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertEquals(
            "Ugyldigt Agent 3.0 Start-svar: capability receipt matcher ikke previewet",
            error?.message,
        )
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

    private fun startEnvelope(capabilityReceiptJson: String? = null): String = """
        {
          "run": {
            "id": "server-run",
            "state": "completed",
            "current_step": 0,
            "steps": []
          },
          "plan_id": "plan-1",
          "review_reads": true,
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
