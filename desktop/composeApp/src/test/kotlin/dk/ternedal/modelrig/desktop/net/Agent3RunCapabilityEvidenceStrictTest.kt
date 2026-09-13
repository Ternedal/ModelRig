package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class Agent3RunCapabilityEvidenceStrictTest {
    @Test
    fun evidenceReceiptRejectsDefaultableWrongTypes() {
        val cases = listOf(
            validEvidence().replace("\"allowed\": true", "\"allowed\": \"true\""),
            validEvidence().replace("\"required_capability_ids\": [\"tool.read\"]", "\"required_capability_ids\": [1]"),
            validEvidence().replace("\"blockers\": []", "\"blockers\": [1]"),
        )

        cases.forEach { body ->
            val server = server(body)
            try {
                assertFailsWith<Agent3Exception> {
                    Agent3Client(server.baseUrl(), "token")
                        .getRunCapabilityEvidence("server-run")
                }
                assertEquals(1, server.requestCount)
            } finally {
                server.stop(0)
            }
        }
    }

    @Test
    fun evidenceEnvelopeRejectsNonBooleanEvaluationFlags() {
        val server = server(
            validEvidence().replace("\"evaluated\": true", "\"evaluated\": \"true\""),
        )
        try {
            assertFailsWith<Agent3Exception> {
                Agent3Client(server.baseUrl(), "token")
                    .getRunCapabilityEvidence("server-run")
            }
            assertEquals(1, server.requestCount)
        } finally {
            server.stop(0)
        }
    }

    private fun server(body: String): TestServer {
        val http = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        var requests = 0
        http.createContext("/") { exchange ->
            requests += 1
            val bytes = body.toByteArray()
            exchange.responseHeaders.add("Content-Type", "application/json")
            exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.use { it.write(bytes) }
        }
        http.start()
        return TestServer(http) { requests }
    }

    private fun validEvidence(): String = """
        {
          "run_id": "server-run",
          "run_state": "completed",
          "current_step": 0,
          "receipt": {
            "schema": "kaliv-agent3-capability-receipt/v1",
            "graph_sha256": "${"a".repeat(64)}",
            "plan_sha256": "${"b".repeat(64)}",
            "route": "rig-tools",
            "allowed": true,
            "required_capability_ids": ["tool.read"],
            "blockers": [],
            "production_activation": false
          },
          "evaluated": true,
          "executed": false
        }
    """.trimIndent()

    private class TestServer(
        private val server: HttpServer,
        private val count: () -> Int,
    ) {
        val requestCount: Int get() = count()
        fun baseUrl(): String = "http://127.0.0.1:${server.address.port}"
        fun stop(delaySeconds: Int) = server.stop(delaySeconds)
    }
}
