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

    private fun server(body: String): MockWebServer = MockWebServer().also { server ->
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody(body),
        )
        server.start()
    }

    private fun startEnvelope(runId: String, planId: String?): String = """
        {
          "run": {
            "id": "$runId",
            "state": "completed",
            "current_step": 0,
            "steps": []
          },
          ${planId?.let { "\"plan_id\":\"$it\"," } ?: ""}
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
