package dk.ternedal.modelrig.desktop.net

import java.nio.charset.StandardCharsets
import java.net.URLEncoder
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

@Serializable
data class Agent3ReplanWindow(
    val start: Int = 0,
    val end: Int = 0,
    @SerialName("removable_step_ids") val removableStepIds: List<String> = emptyList(),
    @SerialName("immutable_prefix_ids") val immutablePrefixIds: List<String> = emptyList(),
    @SerialName("immutable_tail_ids") val immutableTailIds: List<String> = emptyList(),
)

@Serializable
data class Agent3ReplanPreview(
    @SerialName("preview_id") val previewId: String = "",
    @SerialName("expires_in_seconds") val expiresInSeconds: Int = 0,
    @SerialName("run_id") val runId: String = "",
    val revision: Int = 0,
    @SerialName("replan_count") val replanCount: Int = 0,
    val rationale: String = "",
    @SerialName("planner_model") val plannerModel: String? = null,
    @SerialName("prompt_sha256") val promptSha256: String = "",
    @SerialName("observation_characters") val observationCharacters: Int = 0,
    val window: Agent3ReplanWindow = Agent3ReplanWindow(),
    val plan: List<Agent3Step> = emptyList(),
    val executed: Boolean = false,
)

@Serializable
data class Agent3ReplanReceipt(
    val reason: String = "",
    @SerialName("from_revision") val fromRevision: Int = 0,
    @SerialName("to_revision") val toRevision: Int = 0,
    @SerialName("replan_number") val replanNumber: Int = 0,
    val start: Int = 0,
    @SerialName("old_end") val oldEnd: Int = 0,
    @SerialName("new_end") val newEnd: Int = 0,
    @SerialName("removed_step_ids") val removedStepIds: List<String> = emptyList(),
    @SerialName("removed_tools") val removedTools: List<String> = emptyList(),
    @SerialName("added_step_ids") val addedStepIds: List<String> = emptyList(),
    @SerialName("added_tools") val addedTools: List<String> = emptyList(),
    @SerialName("immutable_prefix_ids") val immutablePrefixIds: List<String> = emptyList(),
    @SerialName("immutable_tail_ids") val immutableTailIds: List<String> = emptyList(),
)

@Serializable
data class Agent3AppliedPreview(
    @SerialName("preview_id") val previewId: String = "",
    @SerialName("run_id") val runId: String = "",
    @SerialName("planner_model") val plannerModel: String? = null,
    @SerialName("prompt_sha256") val promptSha256: String = "",
    val rationale: String = "",
)

@Serializable
data class Agent3ReplanApplyResult(
    val run: Agent3Run = Agent3Run(),
    val replan: Agent3ReplanReceipt = Agent3ReplanReceipt(),
    val preview: Agent3AppliedPreview = Agent3AppliedPreview(),
    @SerialName("read_review") val readReview: Agent3ReadReview = Agent3ReadReview(),
)

@Serializable
private data class ReplanPreviewRequest(
    @SerialName("planner_model") val plannerModel: String? = null,
)

/** Developer-only transport for reviewed Agent 3.0 read replans. */
class Agent3ReplanClient(baseUrl: String, private val bearer: String) {
    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = false }
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .build()

    fun preview(runId: String, plannerModel: String? = null): Agent3ReplanPreview {
        val body = json.encodeToString(ReplanPreviewRequest(plannerModel?.takeIf { it.isNotBlank() }))
        return decode(post("/api/v1/experimental/agent3/runs/${seg(runId)}/replan-preview", body))
    }

    fun apply(previewId: String): Agent3ReplanApplyResult =
        decode(postApply(previewId))

    /**
     * Reviewed Apply boundary. A 2xx response may describe a replan that is
     * already committed, so raw response authority is proven before permissive
     * typed defaults are allowed to reach operator-visible state.
     */
    fun applyReviewed(reviewedPreview: Agent3ReplanPreview): Agent3ReplanApplyResult {
        if (reviewedPreview.revision == Int.MAX_VALUE || reviewedPreview.replanCount == Int.MAX_VALUE) {
            throw Agent3Exception("Invalid Agent 3.0 reviewed replan Preview revision authority")
        }
        val body = postApply(reviewedPreview.previewId)
        val root = parseObject(body)
        val rawReadReview = root.requireObject("read_review")
        validateReviewedApplyResponse(root, reviewedPreview)
        validateReviewedReplanCheckpointShape(rawReadReview)
        val result = decode<Agent3ReplanApplyResult>(body)
        validateReviewedReplanCheckpoint(rawReadReview, result)
        return result
    }

    private fun postApply(previewId: String): String =
        post("/api/v1/experimental/agent3/replan-previews/${seg(previewId)}/apply", "{}")

    private fun validateReviewedApplyResponse(
        root: JsonObject,
        reviewed: Agent3ReplanPreview,
    ) {
        val run = root.requireObject("run")
        val receipt = root.requireObject("replan")
        val appliedPreview = root.requireObject("preview")

        run.requireExactString("id", reviewed.runId, "run")
        appliedPreview.requireExactString("preview_id", reviewed.previewId, "preview")
        appliedPreview.requireExactString("run_id", reviewed.runId, "preview")
        appliedPreview.requireExactNullableString(
            "planner_model",
            reviewed.plannerModel,
            "preview",
        )
        appliedPreview.requireExactString("prompt_sha256", reviewed.promptSha256, "preview")
        appliedPreview.requireExactString("rationale", reviewed.rationale, "preview")

        receipt.requireExactString("reason", reviewed.rationale, "replan")
        receipt.requireExactInt("from_revision", reviewed.revision, "replan")
        receipt.requireExactInt("to_revision", reviewed.revision + 1, "replan")
        receipt.requireExactInt("replan_number", reviewed.replanCount + 1, "replan")
    }

    private fun parseObject(body: String): JsonObject = try {
        json.parseToJsonElement(body) as? JsonObject
            ?: throw Agent3Exception("Agent 3.0 replan returned invalid JSON object")
    } catch (e: Agent3Exception) {
        throw e
    } catch (e: Exception) {
        throw Agent3Exception("Agent 3.0 replan returned invalid JSON: ${e.message}")
    }

    private fun JsonObject.requireObject(name: String): JsonObject =
        this[name] as? JsonObject ?: authorityMismatch(name)

    private fun JsonObject.requireExactString(name: String, expected: String, context: String) {
        val raw = this[name]
        val actual = (raw as? JsonPrimitive)?.takeIf { it.isString }?.content
        if (actual != expected) authorityMismatch("$context.$name")
    }

    private fun JsonObject.requireExactNullableString(name: String, expected: String?, context: String) {
        val raw = this[name] ?: authorityMismatch("$context.$name")
        if (raw === JsonNull) {
            if (expected != null) authorityMismatch("$context.$name")
            return
        }
        val actual = (raw as? JsonPrimitive)?.takeIf { it.isString }?.content
        if (expected == null || actual != expected) authorityMismatch("$context.$name")
    }

    private fun JsonObject.requireExactInt(name: String, expected: Int, context: String) {
        val raw = this[name] as? JsonPrimitive
        val actual = raw?.takeIf { !it.isString }?.content?.toIntOrNull()
        if (actual != expected) authorityMismatch("$context.$name")
    }

    private fun authorityMismatch(field: String): Nothing =
        throw Agent3Exception("Agent 3.0 replan Apply response authority mismatch: $field")

    private fun builder(path: String): HttpRequest.Builder = HttpRequest.newBuilder(URI.create(base + path))
        .header("Content-Type", "application/json")
        .header("Authorization", "Bearer $bearer")
        .timeout(Duration.ofMinutes(5))

    private fun post(path: String, body: String): String = send(
        builder(path).POST(HttpRequest.BodyPublishers.ofString(body)).build()
    )

    private fun send(request: HttpRequest): String {
        val response = http.send(request, HttpResponse.BodyHandlers.ofString())
        if (response.statusCode() !in 200..299) {
            throw Agent3Exception(
                "Agent 3.0 replan failed (${response.statusCode()}): ${response.body().take(500)}"
            )
        }
        return response.body()
    }

    private inline fun <reified T> decode(body: String): T = try {
        json.decodeFromString(body)
    } catch (e: Exception) {
        throw Agent3Exception("Agent 3.0 replan returned invalid JSON: ${e.message}")
    }

    /**
     * Encode een sti-komponent. Se Agent3PathSegmentTest paa Android-siden:
     * maalt 27/07-2026 gav runId="../../healthz" stien
     * /api/v1/experimental/healthz/confirm, fordi traversalen oploeses foer
     * requesten sendes. Desktop havde samme eksponering; den blev overset da
     * Android blev rettet.
     */
    private fun seg(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20")

}
