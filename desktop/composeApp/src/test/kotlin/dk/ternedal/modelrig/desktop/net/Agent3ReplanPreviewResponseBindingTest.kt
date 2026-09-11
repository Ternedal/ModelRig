package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.Collections
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReplanPreviewResponseBindingTest {
    private val promptHash = "a".repeat(64)

    @Test
    fun reviewedPreviewAcceptsExactExplicitAuthorityAndUsesSameEndpoint() {
        val paths = Collections.synchronizedList(mutableListOf<String>())
        val requestBodies = Collections.synchronizedList(mutableListOf<String>())
        val server = server(validBody(), paths, requestBodies)
        try {
            val preview = Agent3ReplanClient(server.baseUrl(), "token")
                .previewReviewed("  run-1  ", "  planner-a  ")

            assertEquals("preview-1", preview.previewId)
            assertEquals(300, preview.expiresInSeconds)
            assertEquals("run-1", preview.runId)
            assertEquals(2, preview.revision)
            assertEquals(4, preview.replanCount)
            assertEquals("planner-a", preview.plannerModel)
            assertEquals(promptHash, preview.promptSha256)
            assertFalse(preview.executed)
            assertEquals(listOf("read-old"), preview.window.removableStepIds)
            assertEquals("list_models", preview.plan.single().tool)
            assertEquals("read", preview.plan.single().risk)
            assertEquals("local", preview.plan.single().egress)
            assertEquals(
                listOf("/api/v1/experimental/agent3/runs/run-1/replan-preview"),
                paths.toList(),
            )
            assertTrue(requestBodies.single().contains("\"planner_model\":\"planner-a\""))
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun reviewedPreviewAcceptsNullableModelAndEmptyReplacementPlan() {
        val server = server(
            validBody(
                plannerModelValue = "null",
                planJson = "[]",
            )
        )
        try {
            val preview = Agent3ReplanClient(server.baseUrl(), "token")
                .previewReviewed("run-1")
            assertNull(preview.plannerModel)
            assertTrue(preview.plan.isEmpty())
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun reviewedPreviewRejectsMissingFieldsThatDtoDefaultsWouldHide() {
        listOf(
            validBody(includePreviewId = false),
            validBody(includeExpires = false),
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
            validBody(runIdValue = "\"other-run\""),
            validBody(revisionValue = "\"2\""),
            validBody(replanCountValue = "-1"),
            validBody(expiresValue = "0"),
            validBody(rationaleValue = "\"\""),
            validBody(plannerModelValue = "\"other-model\""),
            validBody(promptValue = "\"${"B".repeat(64)}\""),
            validBody(observationValue = "-1"),
            validBody(executedValue = "true"),
            validBody(executedValue = "\"false\""),
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
    fun reviewedPreviewRejectsMalformedOrUnsafeReplacementStepShape() {
        listOf(
            validBody(planJson = """[{"args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]"""),
            validBody(planJson = """[{"tool":"list_models","args":[],"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]"""),
            validBody(planJson = """[{"tool":"list_models","args":{},"risk":"write","sensitivity":"operational","egress":"local","summary":"list models"}]"""),
            validBody(planJson = """[{"tool":"list_models","args":{},"risk":"read","sensitivity":"","egress":"local","summary":"list models"}]"""),
            validBody(planJson = """[{"tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"cloud","summary":"list models"}]"""),
            validBody(planJson = """[{"tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":7}]"""),
        ).forEach(::assertReviewedFailure)
    }

    @Test
    fun genericPreviewKeepsPermissiveCompatibility() {
        val paths = Collections.synchronizedList(mutableListOf<String>())
        val server = server("{}", paths)
        try {
            val preview = Agent3ReplanClient(server.baseUrl(), "token").preview("run-1")
            assertEquals("", preview.previewId)
            assertEquals(0, preview.revision)
            assertEquals(0, preview.expiresInSeconds)
            assertEquals(
                listOf("/api/v1/experimental/agent3/runs/run-1/replan-preview"),
                paths.toList(),
            )
        } finally {
            server.stop(0)
        }
    }

    private fun assertReviewedFailure(body: String) {
        val server = server(body)
        try {
            val error = assertFailsWith<Agent3Exception> {
                Agent3ReplanClient(server.baseUrl(), "token")
                    .previewReviewed("run-1", "planner-a")
            }
            assertTrue(error.message.orEmpty().contains("Preview response authority mismatch"))
        } finally {
            server.stop(0)
        }
    }

    private fun validBody(
        runIdValue: String = "\"run-1\"",
        expiresValue: String = "300",
        revisionValue: String = "2",
        replanCountValue: String = "4",
        rationaleValue: String = "\"replace stale reads\"",
        plannerModelValue: String = "\"planner-a\"",
        promptValue: String = "\"$promptHash\"",
        observationValue: String = "42",
        executedValue: String = "false",
        windowStart: Int = 1,
        windowEnd: Int = 2,
        removableIds: List<String> = listOf("read-old"),
        prefixIds: List<String> = listOf("done-1"),
        tailIds: List<String> = listOf("write-1"),
        removableIdsJson: String? = null,
        planJson: String = """[{"tool":"list_models","args":{},"risk":"read","sensitivity":"operational","egress":"local","summary":"list models"}]""",
        includePreviewId: Boolean = true,
        includeExpires: Boolean = true,
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
        if (includeExpires) fields += "\"expires_in_seconds\":$expiresValue"
        fields += "\"run_id\":$runIdValue"
        if (includeRevision) fields += "\"revision\":$revisionValue"
        if (includeReplanCount) fields += "\"replan_count\":$replanCountValue"
        if (includeRationale) fields += "\"rationale\":$rationaleValue"
        if (includePlannerModel) fields += "\"planner_model\":$plannerModelValue"
        if (includePrompt) fields += "\"prompt_sha256\":$promptValue"
        if (includeObservation) fields += "\"observation_characters\":$observationValue"
        if (includeWindow) {
            fields += """"window":{"start":$windowStart,"end":$windowEnd,"removable_step_ids":$removable,"immutable_prefix_ids":[${ids(prefixIds)}],"immutable_tail_ids":[${ids(tailIds)}]}"""
        }
        if (includePlan) fields += "\"plan\":$planJson"
        if (includeExecuted) fields += "\"executed\":$executedValue"
        return "{${fields.joinToString(",")}}"
    }

    private fun server(
        body: String,
        paths: MutableList<String> = Collections.synchronizedList(mutableListOf()),
        requestBodies: MutableList<String> = Collections.synchronizedList(mutableListOf()),
    ): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/v1/experimental/agent3") { exchange ->
            paths += exchange.requestURI.path
            requestBodies += exchange.requestBody.bufferedReader().use { it.readText() }
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
