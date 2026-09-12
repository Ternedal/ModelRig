package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedStartRawModeRecoveryTest {
    @Test
    fun rawModeConflictRecoversOnlyFromFreshExpectedModeTruth() {
        val server = server(
            startEnvelope(reviewReads = false),
            runEnvelope(readReviewEnabled = true, answer = "fresh-truth"),
        )
        try {
            val envelope = Agent3Client(server.url("/").toString(), "token")
                .startReviewedPlanEnvelope("plan-1", true, null)

            assertEquals("server-run", envelope.run.id)
            assertEquals("fresh-truth", envelope.run.answer)
            assertTrue(envelope.readReview.enabled)
            assertEquals(2, server.requestCount)
            assertEquals(
                "/api/v1/experimental/agent3/plans/plan-1/start",
                server.takeRequest().path,
            )
            assertEquals(
                "/api/v1/experimental/agent3/runs/server-run",
                server.takeRequest().path,
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun rawModeConflictCannotCreateRecoveryReferenceBeforeExactPlanBinding() {
        val server = server(startEnvelope(reviewReads = false, planId = "other-plan"))
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope("plan-1", true, null)
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertEquals(
                "Ugyldigt Agent 3.0 Start-svar: serveren returnerede et andet plan-id",
                error?.message,
            )
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun rawModeConflictCannotCreateRecoveryReferenceBeforeCapabilityBinding() {
        val server = server(
            startEnvelope(
                reviewReads = false,
                capabilityReceiptJson = receiptJson(),
            ),
        )
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope("plan-1", true, null)
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertEquals(
                "Ugyldigt Agent 3.0 Start-svar: capability receipt matcher ikke previewet",
                error?.message,
            )
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun freshWrongModeAfterRawConflictFailsClosedAndIsNeverAdopted() {
        val server = server(
            startEnvelope(reviewReads = false),
            runEnvelope(readReviewEnabled = false, answer = "wrong-mode-truth"),
        )
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope("plan-1", true, null)
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertTrue(error?.message?.contains("kun recovery-reference") == true)
            assertTrue(error?.message?.contains("Frisk run-recovery fejlede") == true)
            assertTrue(error?.message?.contains("Read review-state matcher ikke runnet") == true)
            assertEquals(2, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun ordinaryStartStillRejectsRawModeConflictBeforeAdoption() {
        val server = server(startEnvelope(reviewReads = false))
        try {
            val error = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startPlanEnvelope("plan-1", expectedReviewReads = true)
            }.exceptionOrNull()

            assertTrue(error is ModelRigException)
            assertEquals(
                "Ugyldigt Agent 3.0 Start-svar: serverens Read review matcher ikke previewet",
                error?.message,
            )
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    private fun server(vararg bodies: String): MockWebServer = MockWebServer().also { server ->
        bodies.forEach { body ->
            server.enqueue(
                MockResponse()
                    .setHeader("Content-Type", "application/json")
                    .setBody(body),
            )
        }
        server.start()
    }

    private fun startEnvelope(
        reviewReads: Boolean,
        planId: String = "plan-1",
        capabilityReceiptJson: String? = null,
    ): String {
        val capabilityField = capabilityReceiptJson
            ?.let { "\"capability_receipt\":$it," }
            .orEmpty()
        return """
            {
              "run": {
                "id": "server-run",
                "state": "completed",
                "current_step": 0,
                "steps": []
              },
              "plan_id": "$planId",
              "review_reads": $reviewReads,
              "read_review": {"enabled":$reviewReads,"waiting":false},
              $capabilityField
              "termination": ${terminationJson()}
            }
        """.trimIndent()
    }

    private fun runEnvelope(
        readReviewEnabled: Boolean,
        answer: String,
    ): String = """
        {
          "run": {
            "id": "server-run",
            "state": "completed",
            "current_step": 0,
            "steps": [],
            "answer": "$answer"
          },
          "read_review": {"enabled":$readReviewEnabled,"waiting":false},
          "termination": ${terminationJson()}
        }
    """.trimIndent()

    private fun terminationJson(): String = """
        {
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

    private fun receiptJson(): String = """
        {
          "schema": "kaliv-agent3-capability-receipt/v1",
          "graph_sha256": "${"a".repeat(64)}",
          "plan_sha256": "${"b".repeat(64)}",
          "route": "rig-tools",
          "allowed": true,
          "required_capability_ids": ["tools"],
          "blockers": [],
          "production_activation": false
        }
    """.trimIndent()
}
