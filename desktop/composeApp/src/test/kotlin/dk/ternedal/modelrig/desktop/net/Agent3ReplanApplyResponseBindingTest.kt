package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.Collections
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class Agent3ReplanApplyResponseBindingTest {
    private val promptHash = "a".repeat(64)
    private val rationale = "replace stale reads"

    @Test
    fun reviewedApplyAcceptsExactConsumedPreviewAndReceipt() {
        val paths = Collections.synchronizedList(mutableListOf<String>())
        val server = server(applyBody(), paths)
        try {
            val result = Agent3ReplanClient(server.baseUrl(), "token")
                .applyReviewed(reviewed())
            assertEquals("run-1", result.run.id)
            assertEquals("preview-1", result.preview.previewId)
            assertEquals(2, result.replan.fromRevision)
            assertEquals(3, result.replan.toRevision)
            assertEquals(5, result.replan.replanNumber)
            assertEquals(
                listOf("/api/v1/experimental/agent3/replan-previews/preview-1/apply"),
                paths.toList(),
            )
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun reviewedApplyAcceptsExplicitNullablePlannerModel() {
        val server = server(applyBody(plannerModelValue = "null"))
        try {
            val result = Agent3ReplanClient(server.baseUrl(), "token")
                .applyReviewed(reviewed(plannerModel = null))
            assertEquals(null, result.preview.plannerModel)
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun reviewedApplyRejectsRunPreviewAndReceiptDrift() {
        val bodies = listOf(
            applyBody(runId = "other-run"),
            applyBody(previewId = "other-preview"),
            applyBody(previewRunId = "other-run"),
            applyBody(plannerModelValue = "\"other-model\""),
            applyBody(promptSha256 = "b".repeat(64)),
            applyBody(returnedRationale = "other rationale"),
            applyBody(reason = "other rationale"),
            applyBody(fromRevisionValue = "1"),
            applyBody(toRevisionValue = "4"),
            applyBody(replanNumberValue = "6"),
        )
        bodies.forEach { body ->
            assertReviewedFailure(body)
        }
    }

    @Test
    fun reviewedApplyRejectsMissingOrWrongTypedAuthorityFields() {
        listOf(
            applyBody(includeFromRevision = false),
            applyBody(fromRevisionValue = "\"2\""),
            applyBody(includePlannerModel = false),
            applyBody(plannerModelValue = "7"),
            applyBody(runIdValueOverride = "7"),
        ).forEach { body ->
            assertReviewedFailure(body)
        }
    }

    @Test
    fun reviewedApplyRejectsRevisionOverflowBeforeNetworkIo() {
        val error = assertFailsWith<Agent3Exception> {
            Agent3ReplanClient("http://127.0.0.1:1", "token")
                .applyReviewed(reviewed().copy(revision = Int.MAX_VALUE))
        }
        assertTrue(error.message.orEmpty().contains("revision authority"))
    }

    @Test
    fun genericApplyKeepsPermissiveCompatibility() {
        val paths = Collections.synchronizedList(mutableListOf<String>())
        val server = server("{}", paths)
        try {
            val result = Agent3ReplanClient(server.baseUrl(), "token").apply("preview-1")
            assertEquals("", result.run.id)
            assertEquals("", result.preview.previewId)
            assertEquals(0, result.replan.fromRevision)
            assertEquals(
                listOf("/api/v1/experimental/agent3/replan-previews/preview-1/apply"),
                paths.toList(),
            )
        } finally {
            server.stop(0)
        }
    }

    private fun assertReviewedFailure(
        body: String,
        preview: Agent3ReplanPreview = reviewed(),
    ) {
        val server = server(body)
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3ReplanClient(server.baseUrl(), "token").applyReviewed(preview)
            }
            assertTrue(error.message.orEmpty().contains("authority mismatch"))
        } finally {
            server.stop(0)
        }
    }

    private fun reviewed(plannerModel: String? = "planner-a"): Agent3ReplanPreview =
        Agent3ReplanPreview(
            previewId = "preview-1",
            runId = "run-1",
            revision = 2,
            replanCount = 4,
            rationale = rationale,
            plannerModel = plannerModel,
            promptSha256 = promptHash,
        )

    private fun applyBody(
        runId: String = "run-1",
        runIdValueOverride: String? = null,
        previewId: String = "preview-1",
        previewRunId: String = "run-1",
        plannerModelValue: String = "\"planner-a\"",
        includePlannerModel: Boolean = true,
        promptSha256: String = promptHash,
        returnedRationale: String = rationale,
        reason: String = rationale,
        fromRevisionValue: String = "2",
        includeFromRevision: Boolean = true,
        toRevisionValue: String = "3",
        replanNumberValue: String = "5",
    ): String {
        val runIdField = runIdValueOverride ?: "\"$runId\""
        val plannerField = if (includePlannerModel) "\"planner_model\":$plannerModelValue," else ""
        val fromRevisionField = if (includeFromRevision) "\"from_revision\":$fromRevisionValue," else ""
        return """
            {
              "run": {"id": $runIdField},
              "replan": {
                "reason": "$reason",
                $fromRevisionField
                "to_revision": $toRevisionValue,
                "replan_number": $replanNumberValue
              },
              "preview": {
                "preview_id": "$previewId",
                "run_id": "$previewRunId",
                $plannerField
                "prompt_sha256": "$promptSha256",
                "rationale": "$returnedRationale"
              }
            }
        """.trimIndent()
    }

    private fun server(
        body: String,
        paths: MutableList<String>? = null,
    ): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/v1/experimental/agent3") { exchange ->
            paths?.add(exchange.requestURI.path)
            exchange.respond(200, body)
        }
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
}
