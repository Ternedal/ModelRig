package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class Agent3RunIdBindingTest {
    @Test
    fun runScopedMethodsAcceptOnlyTheRequestedRunId() {
        val paths = CopyOnWriteArrayList<String>()
        val server = server { exchange ->
            paths += exchange.requestURI.path
            exchange.respond(200, completedEnvelope("run-1"))
        }
        try {
            val client = Agent3Client(server.baseUrl(), "token")

            assertEquals("run-1", client.getRun("run-1").id)
            assertEquals("run-1", client.retry("run-1").id)
            assertEquals("run-1", client.confirm("run-1", "step-1", "digest", approve = true).id)
            assertEquals("run-1", client.resume("run-1").id)
            assertEquals("run-1", client.cancel("run-1").id)

            assertEquals(
                listOf(
                    "/api/v1/experimental/agent3/runs/run-1",
                    "/api/v1/experimental/agent3/runs/run-1/retry",
                    "/api/v1/experimental/agent3/runs/run-1/confirm",
                    "/api/v1/experimental/agent3/runs/run-1/resume",
                    "/api/v1/experimental/agent3/runs/run-1/cancel",
                ),
                paths.toList(),
            )
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun everyRunScopedMethodRejectsAnotherRunId() {
        val server = server { exchange -> exchange.respond(200, completedEnvelope("run-2")) }
        try {
            val client = Agent3Client(server.baseUrl(), "token")

            listOf<() -> Agent3Run>(
                { client.getRun("run-1") },
                { client.retry("run-1") },
                { client.confirm("run-1", "step-1", "digest", approve = false) },
                { client.resume("run-1") },
                { client.cancel("run-1") },
            ).forEach { request ->
                val error = assertFailsWith<Agent3Exception> { request() }
                assertEquals(
                    "Invalid Agent 3.0 run envelope: server returned another run id",
                    error.message,
                )
            }
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun startKeepsServerAuthoredRunIdentity() {
        val server = server { exchange -> exchange.respond(200, completedEnvelope("server-run")) }
        try {
            val client = Agent3Client(server.baseUrl(), "token")
            assertEquals("server-run", client.startPlan("plan-1").id)
        } finally {
            server.stop(0)
        }
    }

    private fun server(handler: (HttpExchange) -> Unit): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/v1/experimental/agent3") { exchange -> handler(exchange) }
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

    private fun completedEnvelope(runId: String): String = """
        {
          "run": {
            "id": "$runId",
            "state": "completed",
            "current_step": 0,
            "steps": []
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
