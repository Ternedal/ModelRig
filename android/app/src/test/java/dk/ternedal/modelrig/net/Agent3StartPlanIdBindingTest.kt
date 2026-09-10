package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3StartPlanIdBindingTest {
    @Test
    fun matchingPlanIdKeepsServerAuthoredRunIdentity() {
        val server = server(startEnvelope("server-run", "plan-1"))
        try {
            val envelope = Agent3Client(server.url("/").toString(), "token")
                .startPlanEnvelope("plan-1")
            assertEquals("plan-1", envelope.planId)
            assertEquals("server-run", envelope.run.id)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun mismatchingPlanIdFailsClosed() {
        val server = server(startEnvelope("server-run", "plan-2"))
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token").startPlan("plan-1")
            }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertEquals(
                "Ugyldigt Agent 3.0 Start-svar: serveren returnerede et andet plan-id",
                error?.message,
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun missingPlanIdFailsClosed() {
        val server = server(startEnvelope("server-run", null))
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token").startPlan("plan-1")
            }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertEquals(
                "Ugyldigt Agent 3.0 Start-svar: serveren returnerede et andet plan-id",
                error?.message,
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedStartAcceptsMatchingTrueMode() {
        val server = server(startEnvelope("server-run", "plan-1", "true"))
        try {
            val envelope = Agent3Client(server.url("/").toString(), "token")
                .startPlanEnvelope("plan-1", expectedReviewReads = true)
            assertTrue(envelope.reviewReads)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedStartAcceptsMatchingFalseMode() {
        val server = server(startEnvelope("server-run", "plan-1", "false"))
        try {
            val envelope = Agent3Client(server.url("/").toString(), "token")
                .startPlanEnvelope("plan-1", expectedReviewReads = false)
            assertEquals(false, envelope.reviewReads)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedStartRejectsMismatchingMode() {
        listOf(
            true to "false",
            false to "true",
        ).forEach { (expected, responseValue) ->
            val server = server(startEnvelope("server-run", "plan-1", responseValue))
            try {
                assertReviewModeFailure(server, expected)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun reviewedStartRejectsMissingMode() {
        val server = server(startEnvelope("server-run", "plan-1"))
        try {
            assertReviewModeFailure(server, false)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedStartRejectsNonBooleanMode() {
        val server = server(startEnvelope("server-run", "plan-1", "\"false\""))
        try {
            assertReviewModeFailure(server, false)
        } finally {
            server.shutdown()
        }
    }

    private fun assertReviewModeFailure(server: MockWebServer, expected: Boolean) {
        val error = runCatching {
            Agent3Client(server.url("/").toString(), "token")
                .startPlanEnvelope("plan-1", expectedReviewReads = expected)
        }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertEquals(
            "Ugyldigt Agent 3.0 Start-svar: serverens Read review matcher ikke previewet",
            error?.message,
        )
    }

    private fun server(body: String): MockWebServer = MockWebServer().also { server ->
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody(body),
        )
        server.start()
    }

    private fun startEnvelope(
        runId: String,
        planId: String?,
        reviewReadsJson: String? = null,
    ): String = """
        {
          "run": {
            "id": "$runId",
            "state": "completed",
            "current_step": 0,
            "steps": []
          },
          ${planId?.let { "\"plan_id\":\"$it\"," } ?: ""}
          ${reviewReadsJson?.let { "\"review_reads\":$it," } ?: ""}
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
