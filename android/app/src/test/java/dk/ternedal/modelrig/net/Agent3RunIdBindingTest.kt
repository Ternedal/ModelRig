package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3RunIdBindingTest {
    @Test
    fun sameRunMethodsAcceptRequestedRunId() {
        val server = MockWebServer()
        repeat(4) { server.enqueue(response(completedEnvelope("run-1"))) }
        server.start()
        try {
            val client = Agent3Client(server.url("/").toString(), "token")
            assertEquals("run-1", client.getRun("run-1").id)
            assertEquals("run-1", client.confirm("run-1", "step-1", "digest", approve = true).id)
            assertEquals("run-1", client.resume("run-1").id)
            assertEquals("run-1", client.cancel("run-1").id)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun everySameRunMethodRejectsAnotherRunId() {
        val server = MockWebServer()
        repeat(4) { server.enqueue(response(completedEnvelope("run-2"))) }
        server.start()
        try {
            val client = Agent3Client(server.url("/").toString(), "token")
            val requests = listOf<() -> Agent3Client.Run>(
                { client.getRun("run-1") },
                { client.confirm("run-1", "step-1", "digest", approve = false) },
                { client.resume("run-1") },
                { client.cancel("run-1") },
            )
            requests.forEach { request ->
                val error = runCatching { request() }.exceptionOrNull()
                assertTrue(error is ModelRigException)
                assertEquals(
                    "Ugyldigt Agent 3.0 run-svar: serveren returnerede et andet run-id",
                    error?.message,
                )
            }
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun retryAcceptsFreshRunIdBoundToOriginalRun() {
        val server = server(completedEnvelope("run-2", retryOfRunId = "run-1"))
        try {
            val run = Agent3Client(server.url("/").toString(), "token").retry("run-1")
            assertEquals("run-2", run.id)
            assertEquals("run-1", run.request.retryOfRunId)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun retryRejectsMissingOrMismatchingOriginalRunId() {
        listOf(null, "run-other").forEach { retryOf ->
            val server = server(completedEnvelope("run-2", retryOfRunId = retryOf))
            try {
                val error = runCatching {
                    Agent3Client(server.url("/").toString(), "token").retry("run-1")
                }.exceptionOrNull()
                assertTrue(error is ModelRigException)
                assertEquals(
                    "Ugyldigt Agent 3.0 Retry-svar: serveren returnerede et andet oprindeligt run-id",
                    error?.message,
                )
            } finally {
                server.shutdown()
            }
        }
    }

    private fun server(body: String): MockWebServer = MockWebServer().also { server ->
        server.enqueue(response(body))
        server.start()
    }

    private fun response(body: String) = MockResponse()
        .setHeader("Content-Type", "application/json")
        .setBody(body)

    private fun completedEnvelope(runId: String, retryOfRunId: String? = null): String = """
        {
          "run": {
            "id": "$runId",
            "state": "completed",
            "current_step": 0,
            "steps": []${retryOfRunId?.let { ",\n            \"request\": {\"retry_of_run_id\": \"$it\"}" } ?: ""}
          },
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
