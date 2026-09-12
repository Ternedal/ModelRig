package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedRunEnvelopeBindingTest {
    private enum class Operation(
        val method: String,
        val path: String,
    ) {
        Get("GET", "/api/v1/experimental/agent3/runs/run-1"),
        Resume("POST", "/api/v1/experimental/agent3/runs/run-1/resume"),
        Cancel("POST", "/api/v1/experimental/agent3/runs/run-1/cancel"),
    }

    @Test
    fun reviewedRunEndpointsPreserveAuthoritativeCheckpointEnvelope() {
        Operation.values().forEach { operation ->
            val server = server(
                runEnvelope(
                    readReviewJson = """
                        {
                          "enabled": true,
                          "waiting": true,
                          "window_start": 1,
                          "window_end": 2,
                          "removable_step_ids": ["step-2"],
                          "completed_step_id": "step-1",
                          "completed_tool": "rig_status"
                        }
                    """.trimIndent(),
                ),
            )
            try {
                val envelope = invokeEnvelope(
                    Agent3Client(server.url("/").toString(), "token"),
                    operation,
                    expectedReviewReads = true,
                )
                assertTrue(envelope.readReview.enabled)
                assertTrue(envelope.readReview.waiting)
                assertEquals(1, envelope.readReview.windowStart)
                assertEquals(2, envelope.readReview.windowEnd)
                assertEquals(listOf("step-2"), envelope.readReview.removableStepIds)
                assertEquals("step-1", envelope.readReview.completedStepId)
                assertEquals("rig_status", envelope.readReview.completedTool)

                val request = server.takeRequest()
                assertEquals(operation.method, request.method)
                assertEquals(operation.path, request.path)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun reviewedRunEndpointsRejectReviewModeMismatch() {
        Operation.values().forEach { operation ->
            listOf(
                true to false,
                false to true,
            ).forEach { (expected, returned) ->
                val server = server(
                    runEnvelope(
                        readReviewJson = "{\"enabled\":$returned,\"waiting\":false}",
                    ),
                )
                try {
                    val error = runCatching {
                        invokeEnvelope(
                            Agent3Client(server.url("/").toString(), "token"),
                            operation,
                            expectedReviewReads = expected,
                        )
                    }.exceptionOrNull()
                    assertTrue(error is ModelRigException)
                    assertEquals(
                        "Ugyldigt Agent 3.0 run-svar: Read review-state matcher ikke runnet",
                        error?.message,
                    )
                } finally {
                    server.shutdown()
                }
            }
        }
    }

    @Test
    fun reviewedModeRejectsMissingOrUnusableReadReviewAfterStart() {
        Operation.values().forEach { operation ->
            listOf<String?>(
                null,
                "{\"enabled\":\"not-a-bool\",\"waiting\":false}",
            ).forEach { reviewJson ->
                val server = server(runEnvelope(readReviewJson = reviewJson))
                try {
                    val error = runCatching {
                        invokeEnvelope(
                            Agent3Client(server.url("/").toString(), "token"),
                            operation,
                            expectedReviewReads = true,
                        )
                    }.exceptionOrNull()
                    assertTrue(error is ModelRigException)
                    assertEquals(
                        "Ugyldigt Agent 3.0 run-svar: Read review-state matcher ikke runnet",
                        error?.message,
                    )
                } finally {
                    server.shutdown()
                }
            }
        }
    }

    @Test
    fun genericRunCallersRemainBackwardCompatible() {
        Operation.values().forEach { operation ->
            val server = server(runEnvelope(readReviewJson = null))
            try {
                val run = invokeGeneric(
                    Agent3Client(server.url("/").toString(), "token"),
                    operation,
                )
                assertEquals("run-1", run.id)
                assertEquals("completed", run.state)
                val request = server.takeRequest()
                assertEquals(operation.method, request.method)
                assertEquals(operation.path, request.path)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun matchingDisabledReviewModeRemainsValid() {
        Operation.values().forEach { operation ->
            val server = server(
                runEnvelope(readReviewJson = "{\"enabled\":false,\"waiting\":false}"),
            )
            try {
                val envelope = invokeEnvelope(
                    Agent3Client(server.url("/").toString(), "token"),
                    operation,
                    expectedReviewReads = false,
                )
                assertFalse(envelope.readReview.enabled)
                assertFalse(envelope.readReview.waiting)
            } finally {
                server.shutdown()
            }
        }
    }

    private fun invokeEnvelope(
        client: Agent3Client,
        operation: Operation,
        expectedReviewReads: Boolean,
    ): Agent3Client.RunEnvelope = when (operation) {
        Operation.Get -> client.getRunEnvelope("run-1", expectedReviewReads)
        Operation.Resume -> client.resumeRunEnvelope("run-1", expectedReviewReads)
        Operation.Cancel -> client.cancelRunEnvelope("run-1", expectedReviewReads)
    }

    private fun invokeGeneric(
        client: Agent3Client,
        operation: Operation,
    ): Agent3Client.Run = when (operation) {
        Operation.Get -> client.getRun("run-1")
        Operation.Resume -> client.resume("run-1")
        Operation.Cancel -> client.cancel("run-1")
    }

    private fun server(body: String): MockWebServer = MockWebServer().also { server ->
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody(body),
        )
        server.start()
    }

    private fun runEnvelope(readReviewJson: String?): String = """
        {
          "run": {
            "id": "run-1",
            "state": "completed",
            "current_step": 0,
            "steps": []
          },
          ${readReviewJson?.let { "\"read_review\":$it," } ?: ""}
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
