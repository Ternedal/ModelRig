package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.Collections
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class Agent3ReplanApplyResponseBindingTest {
    private val promptHash = "a".repeat(64)
    private val rationale = "replace stale reads"

    @Test
    fun reviewedApplyAcceptsExactConsumedPreviewReceiptAndClearedCheckpoint() {
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
            assertTrue(result.readReview.enabled)
            assertFalse(result.readReview.waiting)
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
    fun reviewedApplyAcceptsWaitingCheckpointBoundToReturnedRun() {
        val server = server(
            applyBody(
                runJson = waitingRunJson(),
                readReviewJson = waitingReviewJson(),
            )
        )
        try {
            val result = Agent3ReplanClient(server.baseUrl(), "token")
                .applyReviewed(reviewed())
            assertTrue(result.readReview.enabled)
            assertTrue(result.readReview.waiting)
            assertEquals(1, result.readReview.windowStart)
            assertEquals(2, result.readReview.windowEnd)
            assertEquals(listOf("read-2"), result.readReview.removableStepIds)
            assertEquals("read-1", result.readReview.completedStepId)
            assertEquals("rig_status", result.readReview.completedTool)
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun reviewedApplyAcceptsClearedDisabledCheckpoint() {
        val server = server(
            applyBody(
                readReviewJson = """{"enabled":false,"waiting":false,"removable_step_ids":[]}""",
            )
        )
        try {
            val result = Agent3ReplanClient(server.baseUrl(), "token")
                .applyReviewed(reviewed())
            assertFalse(result.readReview.enabled)
            assertFalse(result.readReview.waiting)
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
    fun reviewedApplyRejectsMissingOrMalformedReadReviewEnvelope() {
        listOf(
            applyBody(includeReadReview = false),
            applyBody(readReviewJson = """{"enabled":"true","waiting":false,"removable_step_ids":[]}"""),
            applyBody(readReviewJson = """{"enabled":true,"waiting":"false","removable_step_ids":[]}"""),
            applyBody(readReviewJson = """{"enabled":true,"waiting":false}"""),
            applyBody(readReviewJson = """{"enabled":true,"waiting":false,"removable_step_ids":[7]}"""),
        ).forEach { body ->
            assertCheckpointFailure(body)
        }
    }

    @Test
    fun reviewedApplyRejectsWaitingCheckpointRunAndWindowDrift() {
        listOf(
            applyBody(
                runJson = waitingRunJson(state = "completed"),
                readReviewJson = waitingReviewJson(),
            ),
            applyBody(
                runJson = waitingRunJson(),
                readReviewJson = waitingReviewJson(windowStart = 0),
            ),
            applyBody(
                runJson = waitingRunJson(),
                readReviewJson = waitingReviewJson(windowEnd = 1),
            ),
            applyBody(
                runJson = waitingRunJson(),
                readReviewJson = waitingReviewJson(windowEnd = 4),
            ),
            applyBody(
                runJson = waitingRunJson(windowRisk = "write"),
                readReviewJson = waitingReviewJson(),
            ),
            applyBody(
                runJson = waitingRunJson(windowState = "succeeded"),
                readReviewJson = waitingReviewJson(),
            ),
            applyBody(
                runJson = waitingRunJson(),
                readReviewJson = waitingReviewJson(removableIds = "[\"other\"]"),
            ),
            applyBody(
                runJson = waitingRunJson(),
                readReviewJson = waitingReviewJson(completedStepId = ""),
            ),
            applyBody(
                runJson = waitingRunJson(),
                readReviewJson = waitingReviewJson(completedTool = ""),
            ),
        ).forEach { body ->
            assertCheckpointFailure(body)
        }
    }

    @Test
    fun reviewedApplyRejectsStalePayloadWhenCheckpointIsCleared() {
        listOf(
            """{"enabled":true,"waiting":false,"window_start":1,"removable_step_ids":[]}""",
            """{"enabled":true,"waiting":false,"window_end":2,"removable_step_ids":[]}""",
            """{"enabled":true,"waiting":false,"removable_step_ids":["read-2"]}""",
            """{"enabled":true,"waiting":false,"removable_step_ids":[],"completed_step_id":"read-1"}""",
            """{"enabled":true,"waiting":false,"removable_step_ids":[],"completed_tool":"rig_status"}""",
        ).forEach { review ->
            assertCheckpointFailure(applyBody(readReviewJson = review))
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
            assertFalse(result.readReview.enabled)
            assertFalse(result.readReview.waiting)
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

    private fun assertCheckpointFailure(body: String) {
        val server = server(body)
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3ReplanClient(server.baseUrl(), "token").applyReviewed(reviewed())
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
        runJson: String? = null,
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
        readReviewJson: String = """{"enabled":true,"waiting":false,"removable_step_ids":[]}""",
        includeReadReview: Boolean = true,
    ): String {
        val runIdField = runIdValueOverride ?: "\"$runId\""
        val effectiveRun = runJson ?: "{\"id\":$runIdField}"
        val plannerField = if (includePlannerModel) "\"planner_model\":$plannerModelValue," else ""
        val fromRevisionField = if (includeFromRevision) "\"from_revision\":$fromRevisionValue," else ""
        val readReviewField = if (includeReadReview) "\"read_review\":$readReviewJson," else ""
        return """
            {
              "run": $effectiveRun,
              "replan": {
                "reason": "$reason",
                $fromRevisionField
                "to_revision": $toRevisionValue,
                "replan_number": $replanNumberValue
              },
              $readReviewField
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

    private fun waitingRunJson(
        state: String = "running",
        windowRisk: String = "read",
        windowState: String = "pending",
    ): String = """
        {
          "id":"run-1",
          "state":"$state",
          "current_step":1,
          "steps":[
            {"id":"read-1","tool":"rig_status","risk":"read","state":"succeeded"},
            {"id":"read-2","tool":"list_models","risk":"$windowRisk","state":"$windowState"},
            {"id":"write-1","tool":"note_append","risk":"write","state":"pending"}
          ]
        }
    """.trimIndent()

    private fun waitingReviewJson(
        windowStart: Int = 1,
        windowEnd: Int = 2,
        removableIds: String = "[\"read-2\"]",
        completedStepId: String = "read-1",
        completedTool: String = "rig_status",
    ): String = """
        {
          "enabled":true,
          "waiting":true,
          "window_start":$windowStart,
          "window_end":$windowEnd,
          "removable_step_ids":$removableIds,
          "completed_step_id":"$completedStepId",
          "completed_tool":"$completedTool"
        }
    """.trimIndent()

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
