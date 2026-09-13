package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class Agent3StartPlanIdBindingTest {
    @Test
    fun matchingPlanIdKeepsServerAuthoredRunIdentity() {
        val server = server(startEnvelope("server-run", "plan-1"))
        try {
            val client = Agent3Client(server.baseUrl(), "token")
            val envelope = client.startPlanEnvelope("plan-1")
            assertEquals("plan-1", envelope.planId)
            assertEquals("server-run", envelope.run.id)
            assertEquals("fresh-server-run", clientRunFromFreshServer("plan-1"))
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun mismatchingPlanIdFailsClosed() {
        val server = server(startEnvelope("server-run", "plan-2"))
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3Client(server.baseUrl(), "token").startPlan("plan-1")
            }
            assertEquals(
                "Invalid Agent 3.0 Start envelope: server returned another plan id",
                error.message,
            )
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun missingPlanIdFailsClosed() {
        val server = server(startEnvelope("server-run", null))
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3Client(server.baseUrl(), "token").startPlan("plan-1")
            }
            assertEquals(
                "Invalid Agent 3.0 Start envelope: server returned another plan id",
                error.message,
            )
        } finally {
            server.stop(0)
        }
    }

    private fun clientRunFromFreshServer(planId: String): String {
        val server = server(startEnvelope("fresh-server-run", planId))
        return try {
            Agent3Client(server.baseUrl(), "token").startPlan(planId).id
        } finally {
            server.stop(0)
        }
    }

    private fun server(body: String): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/v1/experimental/agent3") { exchange -> exchange.respond(200, body) }
        server.start()
        return server
    }

    private fun HttpServer.baseUrl(): String = "http://127.0.0.1:${address.port}"

    private fun HttpExchange.respond(status: Int, body: String) {
        val bytes = body.toByteArray(Charsets.UTF_8)
        responseHeaders.add("Content-Type", "application/json")
        sendResponseHeaders(status, bytes.size.toLong())
        responseBody.use { it.write(bytes) }
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
