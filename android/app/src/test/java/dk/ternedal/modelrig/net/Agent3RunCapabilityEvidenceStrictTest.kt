package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3RunCapabilityEvidenceStrictTest {
    @Test
    fun evidenceReceiptRejectsDefaultableWrongTypes() {
        val cases = listOf(
            validEvidence().replace("\"allowed\": true", "\"allowed\": \"true\"") to "boolean-binding",
            validEvidence().replace("\"required_capability_ids\": [\"tools\"]", "\"required_capability_ids\": [1]") to
                "required_capability_ids",
            validEvidence().replace("\"blockers\": []", "\"blockers\": [1]") to "blocker",
        )

        cases.forEach { (body, expectedMessage) ->
            val server = MockWebServer()
            server.enqueue(
                MockResponse()
                    .setHeader("Content-Type", "application/json")
                    .setBody(body),
            )
            server.start()
            try {
                val error = runCatching {
                    Agent3Client(server.url("/").toString(), "token")
                        .getRunCapabilityEvidence("server-run")
                }.exceptionOrNull()

                assertTrue(error is ModelRigException)
                assertTrue(error?.message?.contains(expectedMessage) == true)
                assertEquals(1, server.requestCount)
                assertEquals(
                    "/api/v1/experimental/agent3/runs/server-run/capability-receipt",
                    server.takeRequest().path,
                )
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun evidenceEnvelopeRejectsNonBooleanEvaluationFlags() {
        val body = validEvidence().replace("\"evaluated\": true", "\"evaluated\": \"true\"")
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody(body))
        server.start()
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .getRunCapabilityEvidence("server-run")
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("evaluated/executed-binding") == true)
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
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
            "required_capability_ids": ["tools"],
            "blockers": [],
            "production_activation": false
          },
          "evaluated": true,
          "executed": false
        }
    """.trimIndent()
}
