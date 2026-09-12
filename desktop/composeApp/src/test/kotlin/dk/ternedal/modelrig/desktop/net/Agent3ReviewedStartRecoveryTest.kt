package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.ArrayDeque
import java.util.Collections
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReviewedStartRecoveryTest {
    @Test
    fun rejectedParsedReviewStateRecoversFreshExactRunTruthWithoutReviewedReceipt() {
        val server = server(
            startEnvelope(
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                answer = "rejected-start-payload",
            ),
            runEnvelope(
                runId = "server-run",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
                answer = "fresh-server-truth",
            ),
        )
        try {
            val envelope = client(server).startReviewedPlanEnvelope(
                planId = "plan-1",
                expectedReviewReads = true,
                expectedCapabilityReceipt = null,
            )

            assertEquals("server-run", envelope.run.id)
            assertEquals("fresh-server-truth", envelope.run.answer)
            assertEquals(true, envelope.readReview.enabled)
            assertNull(envelope.capabilityReceipt)
            assertTwoRecoveryRequests(server)
        } finally {
            server.stop()
        }
    }

    @Test
    fun recoveryPreservesReviewedReceiptWhenCurrentGraphChangesButPlanMatches() {
        val expected = receipt()
        val current = receipt(
            graphSha = "c".repeat(64),
            allowed = false,
            blockers = listOf(
                Agent3CapabilityBlocker("tool.read", "degraded", "fresh graph changed")
            ),
        )
        val server = server(
            startEnvelope(
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(expected),
                answer = "rejected-start-payload",
            ),
            runEnvelope(
                runId = "server-run",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(current),
                answer = "fresh-server-truth",
            ),
        )
        try {
            val envelope = client(server).startReviewedPlanEnvelope(
                planId = "plan-1",
                expectedReviewReads = true,
                expectedCapabilityReceipt = expected,
            )

            assertEquals(expected, envelope.capabilityReceipt)
            assertEquals("fresh-server-truth", envelope.run.answer)
            assertTwoRecoveryRequests(server)
        } finally {
            server.stop()
        }
    }

    @Test
    fun rawModeConflictRecoveryUsesSameSnapshotPlanEvidence() {
        val expected = receipt()
        val server = server(
            startEnvelope(
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(expected),
                answer = "rejected-mode-start-payload",
                reviewReads = false,
            ),
            runEnvelope(
                runId = "server-run",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(expected),
                answer = "fresh-reviewed-truth",
            ),
        )
        try {
            val envelope = client(server).startReviewedPlanEnvelope(
                planId = "plan-1",
                expectedReviewReads = true,
                expectedCapabilityReceipt = expected,
            )

            assertEquals(expected, envelope.capabilityReceipt)
            assertEquals("fresh-reviewed-truth", envelope.run.answer)
            assertTwoRecoveryRequests(server)
        } finally {
            server.stop()
        }
    }

    @Test
    fun changedSameSnapshotPlanDigestFailsClosedBeforeAnyThirdRequest() {
        val server = recoveryServer(receipt(planSha = "d".repeat(64)))
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = receipt(),
                )
            }
            assertTrue(error.message?.contains("Fresh run recovery failed") == true)
            assertTrue(error.message?.contains("current run plan does not match reviewed Preview") == true)
            assertEquals(2, server.requests.size)
        } finally {
            server.stop()
        }
    }

    @Test
    fun changedSameSnapshotRouteOrRequiredCapabilitiesFailClosed() {
        val variants = listOf(
            receipt(route = "other-route"),
            receipt(requiredIds = listOf("tool.read", "rag")),
        )
        variants.forEach { current ->
            val server = recoveryServer(current)
            try {
                val error = assertFailsWith<Agent3Exception> {
                    client(server).startReviewedPlanEnvelope(
                        planId = "plan-1",
                        expectedReviewReads = true,
                        expectedCapabilityReceipt = receipt(),
                    )
                }
                assertTrue(error.message?.contains("current run plan does not match reviewed Preview") == true)
                assertEquals(2, server.requests.size)
            } finally {
                server.stop()
            }
        }
    }

    @Test
    fun missingSameSnapshotEvidenceFailsClosedWhenReviewedReceiptExists() {
        val expected = receipt()
        val server = server(
            startEnvelope(
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(expected),
                answer = "rejected-start-payload",
            ),
            runEnvelope(
                runId = "server-run",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
                answer = "fresh-without-evidence",
            ),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = expected,
                )
            }
            assertTrue(error.message?.contains("same-snapshot capability evidence is missing") == true)
            assertEquals(2, server.requests.size)
        } finally {
            server.stop()
        }
    }

    @Test
    fun currentReceiptDoesNotInventHistoricalAuthorityWhenReviewedReceiptWasNull() {
        val server = server(
            startEnvelope(
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                answer = "rejected-start-payload",
            ),
            runEnvelope(
                runId = "server-run",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(receipt()),
                answer = "fresh-server-truth",
            ),
        )
        try {
            val envelope = client(server).startReviewedPlanEnvelope(
                planId = "plan-1",
                expectedReviewReads = true,
                expectedCapabilityReceipt = null,
            )
            assertNull(envelope.capabilityReceipt)
            assertTwoRecoveryRequests(server)
        } finally {
            server.stop()
        }
    }

    @Test
    fun capabilityMismatchNeverCreatesRecoveryAuthority() {
        val expected = receipt()
        val server = server(
            startEnvelope(
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                capabilityReceiptJson = receiptJson(receipt(route = "other-route")),
            ),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = expected,
                )
            }
            assertEquals(
                "Invalid Agent 3.0 Start envelope: capability receipt does not match reviewed Preview",
                error.message,
            )
            assertEquals(
                listOf("POST /api/v1/experimental/agent3/plans/plan-1/start"),
                server.requests,
            )
        } finally {
            server.stop()
        }
    }

    @Test
    fun invalidFreshCheckpointFailsClosedWithoutRejectedPayloadFallback() {
        val server = server(
            startEnvelope(
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
                answer = "rejected-start-payload",
            ),
            runEnvelope(
                runId = "server-run",
                readReviewJson = "{\"enabled\":true,\"waiting\":false,\"window_start\":1}",
                answer = "invalid-fresh-payload",
            ),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(server).startReviewedPlanEnvelope(
                    planId = "plan-1",
                    expectedReviewReads = true,
                    expectedCapabilityReceipt = null,
                )
            }
            assertTrue(error.message?.contains("Fresh run recovery failed") == true)
            assertTrue(error.message?.contains("stale cleared read_review checkpoint") == true)
            assertEquals(2, server.requests.size)
        } finally {
            server.stop()
        }
    }

    @Test
    fun reviewedGetEnvelopeBindsExactRunIdAndReviewMode() {
        val wrongRun = server(
            runEnvelope(
                runId = "other-run",
                readReviewJson = "{\"enabled\":true,\"waiting\":false}",
            ),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(wrongRun).getRunEnvelope("run-1", expectedReviewReads = true)
            }
            assertEquals(
                "Invalid Agent 3.0 run envelope: server returned another run id",
                error.message,
            )
        } finally {
            wrongRun.stop()
        }

        val wrongMode = server(
            runEnvelope(
                runId = "run-1",
                readReviewJson = "{\"enabled\":false,\"waiting\":false}",
            ),
        )
        try {
            val error = assertFailsWith<Agent3Exception> {
                client(wrongMode).getRunEnvelope("run-1", expectedReviewReads = true)
            }
            assertEquals(
                "Invalid Agent 3.0 run envelope: read_review state does not match reviewed run",
                error.message,
            )
        } finally {
            wrongMode.stop()
        }
    }

    private fun recoveryServer(current: Agent3CapabilityReceipt): QueueServer = server(
        startEnvelope(
            readReviewJson = "{\"enabled\":false,\"waiting\":false}",
            capabilityReceiptJson = receiptJson(receipt()),
            answer = "rejected-start-payload",
        ),
        runEnvelope(
            runId = "server-run",
            readReviewJson = "{\"enabled\":true,\"waiting\":false}",
            capabilityReceiptJson = receiptJson(current),
            answer = "fresh-server-truth",
        ),
    )

    private fun client(server: QueueServer) = Agent3Client(server.baseUrl(), "token")

    private fun assertTwoRecoveryRequests(server: QueueServer) {
        assertEquals(
            listOf(
                "POST /api/v1/experimental/agent3/plans/plan-1/start",
                "GET /api/v1/experimental/agent3/runs/server-run",
            ),
            server.requests,
        )
    }

    private fun receipt(
        graphSha: String = "a".repeat(64),
        planSha: String = "b".repeat(64),
        route: String = "rig",
        allowed: Boolean = true,
        requiredIds: List<String> = listOf("tool.read"),
        blockers: List<Agent3CapabilityBlocker> = emptyList(),
    ): Agent3CapabilityReceipt = Agent3CapabilityReceipt(
        schema = "kaliv-agent3-capability-receipt/v1",
        graphSha256 = graphSha,
        planSha256 = planSha,
        route = route,
        allowed = allowed,
        requiredCapabilityIds = requiredIds,
        blockers = blockers,
        productionActivation = false,
    )

    private fun receiptJson(receipt: Agent3CapabilityReceipt): String {
        val required = receipt.requiredCapabilityIds.joinToString(",") { "\"$it\"" }
        val blockers = receipt.blockers.joinToString(",") {
            """{"capability_id":"${it.capabilityId}","state":"${it.state}","reason":"${it.reason}"}"""
        }
        return """
            {
              "schema": "${receipt.schema}",
              "graph_sha256": "${receipt.graphSha256}",
              "plan_sha256": "${receipt.planSha256}",
              "route": "${receipt.route}",
              "allowed": ${receipt.allowed},
              "required_capability_ids": [$required],
              "blockers": [$blockers],
              "production_activation": false
            }
        """.trimIndent()
    }

    private fun startEnvelope(
        readReviewJson: String,
        capabilityReceiptJson: String? = null,
        answer: String? = null,
        reviewReads: Boolean = true,
    ): String {
        val capabilityField = capabilityReceiptJson
            ?.let { "\"capability_receipt\":$it," }
            .orEmpty()
        val answerField = answer?.let { "\"answer\":\"$it\"," }.orEmpty()
        return """
            {
              "run": {
                "id": "server-run",
                "state": "completed",
                "current_step": 0,
                $answerField
                "steps": []
              },
              "plan_id": "plan-1",
              "review_reads": $reviewReads,
              "read_review": $readReviewJson,
              $capabilityField
              ${terminationJson()}
            }
        """.trimIndent()
    }

    private fun runEnvelope(
        runId: String,
        readReviewJson: String,
        answer: String? = null,
        capabilityReceiptJson: String? = null,
    ): String {
        val answerField = answer?.let { "\"answer\":\"$it\"," }.orEmpty()
        val capabilityField = capabilityReceiptJson
            ?.let { "\"capability_receipt\":$it," }
            .orEmpty()
        return """
            {
              "run": {
                "id": "$runId",
                "state": "completed",
                "current_step": 0,
                $answerField
                "steps": []
              },
              "review_reads": true,
              "read_review": $readReviewJson,
              $capabilityField
              ${terminationJson()}
            }
        """.trimIndent()
    }

    private fun terminationJson(): String = """
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
    """.trimIndent()

    private fun server(vararg bodies: String): QueueServer = QueueServer(bodies.toList())

    private inner class QueueServer(bodies: List<String>) {
        private val responses = ArrayDeque(bodies)
        val requests: MutableList<String> = Collections.synchronizedList(mutableListOf())
        private val httpServer = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).also { server ->
            server.createContext("/api/v1/experimental/agent3") { exchange ->
                requests += "${exchange.requestMethod} ${exchange.requestURI.path}"
                val body = synchronized(responses) {
                    if (responses.isEmpty()) null else responses.removeFirst()
                }
                if (body == null) {
                    exchange.respond(500, "no fixture response queued")
                } else {
                    exchange.respond(200, body)
                }
            }
            server.start()
        }

        fun baseUrl(): String = "http://127.0.0.1:${httpServer.address.port}"

        fun stop() = httpServer.stop(0)
    }

    private fun HttpExchange.respond(status: Int, body: String) {
        val bytes = body.toByteArray(Charsets.UTF_8)
        responseHeaders.add("Content-Type", "application/json")
        sendResponseHeaders(status, bytes.size.toLong())
        responseBody.use { it.write(bytes) }
    }
}
