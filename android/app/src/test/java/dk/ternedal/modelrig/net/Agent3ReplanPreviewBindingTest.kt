package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReplanPreviewBindingTest {
    private val promptHash = "a".repeat(64)

    @Test
    fun reviewedPreviewAcceptsExactAuthorityAndBindsTrimmedRequest() {
        val server = server(validBody())
        try {
            val preview = Agent3ReplanClient(server.url("/").toString(), "token")
                .previewReviewed("  run-1  ", "  planner-a  ")

            assertEquals("preview-1", preview.previewId)
            assertEquals(300, preview.expiresInSeconds)
            assertEquals("run-1", preview.runId)
            assertEquals(2, preview.revision)
            assertEquals(4, preview.replanCount)
            assertEquals("replace stale reads", preview.rationale)
            assertEquals("planner-a", preview.plannerModel)
            assertEquals(promptHash, preview.promptSha256)
            assertEquals(42, preview.observationCharacters)
            assertFalse(preview.executed)
            assertEquals(listOf("read-old"), preview.window.removableStepIds)
            assertEquals("read-new", preview.plan.single().id)
            assertEquals("list_models", preview.plan.single().tool)
            assertEquals("read", preview.plan.single().risk)
            assertEquals("local", preview.plan.single().egress)

            val request = server.takeRequest()
            assertEquals(
                "/api/v1/experimental/agent3/runs/run-1/replan-preview",
                request.path,
            )
            assertTrue(request.body.readUtf8().contains("\"planner_model\":\"planner-a\""))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedPreviewAcceptsExplicitNullModelAndEmptyReplacementPlan() {
        val server = server(validBody(plannerModelJson = "null", planJson = "[]"))
        try {
            val preview = Agent3ReplanClient(server.url("/").toString(), "token")
                .previewReviewed("run-1")
            assertNull(preview.plannerModel)
            assertTrue(preview.plan.isEmpty())
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedPreviewRejectsMissingFieldsThatOptDefaultsWouldHide() {
        listOf(
            validBody(includePreviewId = false),
            validBody(includeExpires = false),
            validBody(includeRunId = false),
            validBody(includeRevision = false),
            validBody(includeReplanCount = false),
            validBody(includeRationale = false),
            validBody(includePlannerModel = false),
            validBody(includePrompt = false),
            validBody(includeObservation = false),
            validBody(includeExecuted = false),
            validBody(includeWindow = false),
            validBody(includePlan = false),
        ).forEach(::assertReviewedFailure)
    }

    @Test
    fun reviewedPreviewRejectsWrongTypedOrDriftedMetadata() {
        listOf(
            validBody(runIdJson = "\"other-run\""),
            validBody(expiresJson = "0"),
            validBody(revisionJson = "\"2\""),
            validBody(replanCountJson = "-1"),
            validBody(rationaleJson = "\"\""),
            validBody(rationaleJson = "\"${"x".repeat(501)}\""),
            validBody(plannerModelJson = "\"planner-other\""),
            validBody(promptJson = "\"${"B".repeat(64)}\""),
            validBody(observationJson = "-1"),
            validBody(executedJson = "true"),
            validBody(executedJson = "\"false\""),
        ).forEach(::assertReviewedFailure)
    }

    @Test
    fun reviewedPreviewRejectsInvalidWindowAuthority() {
        listOf(
            validBody(windowStart = 2, windowEnd = 2),
            validBody(windowStart = -1, windowEnd = 0),
            validBody(windowStart = 1, windowEnd = 3, removableIds = listOf("read-old")),
            validBody(windowStart = 2, windowEnd = 3, prefixIds = listOf("done-1")),
            validBody(prefixIds = listOf("same"), removableIds = listOf("same")),
            validBody(removableIdsJson = "[7]"),
        ).forEach(::assertReviewedFailure)
    }

    @Test
    fun reviewedPreviewRejectsMissingBlankOrWrongTypedReplacementIds() {
        listOf(
            validBody(
                planJson = """[{"tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]""",
            ),
            validBody(
                planJson = """[{"id":null,"tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]""",
            ),
            validBody(
                planJson = """[{"id":" ","tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]""",
            ),
            validBody(
                planJson = """[{"id":7,"tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]""",
            ),
        ).forEach(::assertReviewedFailure)
    }

    @Test
    fun reviewedPreviewRejectsDuplicateOrImmutableCollidingReplacementIds() {
        listOf(
            validBody(
                planJson = """[{"id":"read-new","tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"},{"id":"read-new","tool":"rig_status","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"status"}]""",
            ),
            validBody(
                planJson = """[{"id":"done-1","tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]""",
            ),
            validBody(
                planJson = """[{"id":"write-1","tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]""",
            ),
        ).forEach(::assertReviewedFailure)
    }

    @Test
    fun reviewedPreviewAllowsReplacementIdReuseFromRemovableWindow() {
        val server = server(
            validBody(
                planJson = """[{"id":"read-old","tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]""",
            ),
        )
        try {
            val preview = Agent3ReplanClient(server.url("/").toString(), "token")
                .previewReviewed("run-1", "planner-a")
            assertEquals("read-old", preview.plan.single().id)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedPreviewRejectsMalformedOrUnsafeReplacementStepShape() {
        listOf(
            validBody(
                planJson = """[{"id":"read-new","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]""",
            ),
            validBody(
                planJson = """[{"id":"read-new","tool":"list_models","args":[],"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]""",
            ),
            validBody(
                planJson = """[{"id":"read-new","tool":"list_models","args":{},"risk":"write","sensitivity":"operational","egress":"local","summary":"list models"}]""",
            ),
            validBody(
                planJson = """[{"id":"read-new","tool":"list_models","args":{},"risk":"read","sensitivity":"","egress":"local","summary":"list models"}]""",
            ),
            validBody(
                planJson = """[{"id":"read-new","tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"cloud","summary":"list models"}]""",
            ),
            validBody(
                planJson = """[{"id":"read-new","tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":7}]""",
            ),
        ).forEach(::assertReviewedFailure)
    }

    @Test
    fun reviewedPreviewRejectsBlankRunIdBeforeNetworkAuthority() {
        val server = MockWebServer()
        server.start()
        try {
            val error = runCatching {
                Agent3ReplanClient(server.url("/").toString(), "token")
                    .previewReviewed("   ")
            }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertEquals(0, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun genericPreviewKeepsPermissiveCompatibilityContract() {
        val server = server("{}")
        try {
            val preview = Agent3ReplanClient(server.url("/").toString(), "token")
                .preview("run-1")
            assertEquals("", preview.previewId)
            assertEquals(0, preview.expiresInSeconds)
            assertEquals(0, preview.revision)
            assertEquals(0, preview.replanCount)
            assertFalse(preview.executed)
            assertTrue(preview.plan.isEmpty())
        } finally {
            server.shutdown()
        }
    }

    private fun assertReviewedFailure(body: String) {
        val server = server(body)
        try {
            val error = runCatching {
                Agent3ReplanClient(server.url("/").toString(), "token")
                    .previewReviewed("run-1", "planner-a")
            }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertTrue(error?.message.orEmpty().contains("Preview response authority mismatch"))
        } finally {
            server.shutdown()
        }
    }

    private fun validBody(
        runIdJson: String = "\"run-1\"",
        expiresJson: String = "300",
        revisionJson: String = "2",
        replanCountJson: String = "4",
        rationaleJson: String = "\"replace stale reads\"",
        plannerModelJson: String = "\"planner-a\"",
        promptJson: String = "\"$promptHash\"",
        observationJson: String = "42",
        executedJson: String = "false",
        windowStart: Int = 1,
        windowEnd: Int = 2,
        removableIds: List<String> = listOf("read-old"),
        prefixIds: List<String> = listOf("done-1"),
        tailIds: List<String> = listOf("write-1"),
        removableIdsJson: String? = null,
        planJson: String = """[{"id":"read-new","tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]""",
        includePreviewId: Boolean = true,
        includeExpires: Boolean = true,
        includeRunId: Boolean = true,
        includeRevision: Boolean = true,
        includeReplanCount: Boolean = true,
        includeRationale: Boolean = true,
        includePlannerModel: Boolean = true,
        includePrompt: Boolean = true,
        includeObservation: Boolean = true,
        includeWindow: Boolean = true,
        includePlan: Boolean = true,
        includeExecuted: Boolean = true,
    ): String {
        fun ids(values: List<String>): String = values.joinToString(",") { "\"$it\"" }
        val removable = removableIdsJson ?: "[${ids(removableIds)}]"
        val fields = mutableListOf<String>()
        if (includePreviewId) fields += "\"preview_id\":\"preview-1\""
        if (includeExpires) fields += "\"expires_in_seconds\":$expiresJson"
        if (includeRunId) fields += "\"run_id\":$runIdJson"
        if (includeRevision) fields += "\"revision\":$revisionJson"
        if (includeReplanCount) fields += "\"replan_count\":$replanCountJson"
        if (includeRationale) fields += "\"rationale\":$rationaleJson"
        if (includePlannerModel) fields += "\"planner_model\":$plannerModelJson"
        if (includePrompt) fields += "\"prompt_sha256\":$promptJson"
        if (includeObservation) fields += "\"observation_characters\":$observationJson"
        if (includeWindow) {
            fields += "\"window\":{\"start\":$windowStart,\"end\":$windowEnd,\"removable_step_ids\":$removable,\"immutable_prefix_ids\":[${ids(prefixIds)}],\"immutable_tail_ids\":[${ids(tailIds)}]}"
        }
        if (includePlan) fields += "\"plan\":$planJson"
        if (includeExecuted) fields += "\"executed\":$executedJson"
        return "{${fields.joinToString(",")}}"
    }

    private fun server(body: String): MockWebServer = MockWebServer().also { server ->
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(body),
        )
        server.start()
    }
}
