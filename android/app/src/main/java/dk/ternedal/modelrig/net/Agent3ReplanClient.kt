package dk.ternedal.modelrig.net

import java.nio.charset.StandardCharsets
import java.net.URLEncoder
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Developer-only transport for reviewed Agent 3.0 read replans. */
class Agent3ReplanClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val jsonType = "application/json".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)
        .build()

    data class Window(
        val start: Int,
        val end: Int,
        val removableStepIds: List<String>,
        val immutablePrefixIds: List<String>,
        val immutableTailIds: List<String>,
    )

    data class Preview(
        val previewId: String,
        val expiresInSeconds: Int,
        val runId: String,
        val revision: Int,
        val replanCount: Int,
        val rationale: String,
        val plannerModel: String?,
        val promptSha256: String,
        val observationCharacters: Int,
        val window: Window,
        val plan: List<Agent3Client.Step>,
        val executed: Boolean,
    )

    data class Receipt(
        val reason: String,
        val fromRevision: Int,
        val toRevision: Int,
        val replanNumber: Int,
        val removedTools: List<String>,
        val addedTools: List<String>,
        val immutableTailIds: List<String>,
    )

    data class AppliedPreview(
        val previewId: String,
        val runId: String,
        val plannerModel: String?,
        val promptSha256: String,
        val rationale: String,
    )

    data class ApplyResult(
        val run: Agent3Client.Run,
        val replan: Receipt,
        val preview: AppliedPreview,
        val readReview: Agent3Client.ReadReview,
    )

    fun preview(runId: String, plannerModel: String? = null): Preview {
        val body = JSONObject()
        plannerModel?.takeIf { it.isNotBlank() }?.let { body.put("planner_model", it) }
        val root = post("/api/v1/experimental/agent3/runs/${seg(runId)}/replan-preview", body)
        val window = root.optJSONObject("window") ?: JSONObject()
        return Preview(
            previewId = root.optString("preview_id"),
            expiresInSeconds = root.optInt("expires_in_seconds"),
            runId = root.optString("run_id"),
            revision = root.optInt("revision"),
            replanCount = root.optInt("replan_count"),
            rationale = root.optString("rationale"),
            plannerModel = root.nullableString("planner_model"),
            promptSha256 = root.optString("prompt_sha256"),
            observationCharacters = root.optInt("observation_characters"),
            window = Window(
                start = window.optInt("start"),
                end = window.optInt("end"),
                removableStepIds = window.optJSONArray("removable_step_ids").toStrings(),
                immutablePrefixIds = window.optJSONArray("immutable_prefix_ids").toStrings(),
                immutableTailIds = window.optJSONArray("immutable_tail_ids").toStrings(),
            ),
            plan = parseSteps(root.optJSONArray("plan") ?: JSONArray()),
            executed = root.optBoolean("executed", false),
        )
    }

    /** Generic compatibility path: parses the Apply response without reviewed-preview binding. */
    fun apply(previewId: String): ApplyResult = parseApplyResult(postApply(previewId))

    /**
     * Reviewed Apply boundary. The worker response must prove that the consumed
     * single-use preview, deterministic revision receipt and read-review checkpoint
     * belong to the exact reviewed run before any result is returned to UI state.
     */
    fun applyReviewed(reviewedPreview: Preview): ApplyResult {
        if (reviewedPreview.revision == Int.MAX_VALUE || reviewedPreview.replanCount == Int.MAX_VALUE) {
            throw ModelRigException("Agent 3.0 replan reviewed Preview has invalid revision authority")
        }
        val root = postApply(reviewedPreview.previewId)
        validateReviewedApplyResponse(root, reviewedPreview)
        return parseApplyResult(root)
    }

    private fun postApply(previewId: String): JSONObject = post(
        "/api/v1/experimental/agent3/replan-previews/${seg(previewId)}/apply",
        JSONObject(),
    )

    private fun parseApplyResult(root: JSONObject): ApplyResult {
        val receipt = root.optJSONObject("replan") ?: JSONObject()
        val preview = root.optJSONObject("preview") ?: JSONObject()
        return ApplyResult(
            run = parseRun(root.requireObject("run")),
            replan = Receipt(
                reason = receipt.optString("reason"),
                fromRevision = receipt.optInt("from_revision"),
                toRevision = receipt.optInt("to_revision"),
                replanNumber = receipt.optInt("replan_number"),
                removedTools = receipt.optJSONArray("removed_tools").toStrings(),
                addedTools = receipt.optJSONArray("added_tools").toStrings(),
                immutableTailIds = receipt.optJSONArray("immutable_tail_ids").toStrings(),
            ),
            preview = AppliedPreview(
                previewId = preview.optString("preview_id"),
                runId = preview.optString("run_id"),
                plannerModel = preview.nullableString("planner_model"),
                promptSha256 = preview.optString("prompt_sha256"),
                rationale = preview.optString("rationale"),
            ),
            readReview = parseReadReview(root.optJSONObject("read_review")),
        )
    }

    private fun validateReviewedApplyResponse(root: JSONObject, reviewed: Preview) {
        val run = root.requireObject("run")
        val receipt = root.requireObject("replan")
        val appliedPreview = root.requireObject("preview")
        val readReview = root.requireObject("read_review")

        run.requireExactString("id", reviewed.runId, "run")
        appliedPreview.requireExactString("preview_id", reviewed.previewId, "preview")
        appliedPreview.requireExactString("run_id", reviewed.runId, "preview")
        appliedPreview.requireExactNullableString("planner_model", reviewed.plannerModel, "preview")
        appliedPreview.requireExactString("prompt_sha256", reviewed.promptSha256, "preview")
        appliedPreview.requireExactString("rationale", reviewed.rationale, "preview")

        receipt.requireExactString("reason", reviewed.rationale, "replan")
        receipt.requireExactInt("from_revision", reviewed.revision, "replan")
        receipt.requireExactInt("to_revision", reviewed.revision + 1, "replan")
        receipt.requireExactInt("replan_number", reviewed.replanCount + 1, "replan")

        validateReviewedReadReview(readReview, run)
    }

    private fun validateReviewedReadReview(review: JSONObject, run: JSONObject) {
        val enabled = review.requireBoolean("enabled", "read_review")
        val waiting = review.requireBoolean("waiting", "read_review")
        val windowStart = review.requireNullableInt("window_start", "read_review")
        val windowEnd = review.requireNullableInt("window_end", "read_review")
        val removableStepIds = review.requireStringArray("removable_step_ids", "read_review")
        val completedStepId = review.requireNullableString("completed_step_id", "read_review")
        val completedTool = review.requireNullableString("completed_tool", "read_review")
        review.requireNullableFiniteDouble("updated_at", "read_review")

        if (!waiting) {
            if (
                windowStart != null ||
                windowEnd != null ||
                removableStepIds.isNotEmpty() ||
                completedStepId != null ||
                completedTool != null
            ) {
                throw ModelRigException(
                    "Agent 3.0 replan Apply response authority mismatch: read_review contains stale non-waiting checkpoint authority",
                )
            }
            return
        }

        if (!enabled) {
            throw ModelRigException(
                "Agent 3.0 replan Apply response authority mismatch: read_review.waiting requires enabled review",
            )
        }

        val currentStep = run.requireInt("current_step", "run")
        val steps = run.optJSONArray("steps")
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: run.steps")
        val start = windowStart
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: read_review.window_start")
        val end = windowEnd
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: read_review.window_end")
        if (currentStep <= 0 || start != currentStep || end <= start || end > steps.length()) {
            throw ModelRigException(
                "Agent 3.0 replan Apply response authority mismatch: read_review window does not match run.current_step",
            )
        }

        val expectedRemovableIds = buildList {
            for (index in start until end) {
                val step = steps.optJSONObject(index)
                    ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: run.steps[$index]")
                if (
                    step.requireString("risk", "run.steps[$index]") != "read" ||
                    step.requireString("state", "run.steps[$index]") != "pending"
                ) {
                    throw ModelRigException(
                        "Agent 3.0 replan Apply response authority mismatch: read_review window is not contiguous pending reads",
                    )
                }
                add(step.requireNonBlankString("id", "run.steps[$index]"))
            }
        }
        if (expectedRemovableIds != removableStepIds) {
            throw ModelRigException(
                "Agent 3.0 replan Apply response authority mismatch: read_review.removable_step_ids",
            )
        }
        if (end < steps.length()) {
            val next = steps.optJSONObject(end)
                ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: run.steps[$end]")
            val nextRisk = next.requireString("risk", "run.steps[$end]")
            val nextState = next.requireString("state", "run.steps[$end]")
            if (nextRisk == "read" && nextState == "pending") {
                throw ModelRigException(
                    "Agent 3.0 replan Apply response authority mismatch: read_review window is not maximal",
                )
            }
        }

        val completed = steps.optJSONObject(start - 1)
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: completed read step")
        if (
            completed.requireString("risk", "completed read step") != "read" ||
            completed.requireString("state", "completed read step") != "succeeded" ||
            completedStepId != completed.requireNonBlankString("id", "completed read step") ||
            completedTool != completed.requireNonBlankString("tool", "completed read step")
        ) {
            throw ModelRigException(
                "Agent 3.0 replan Apply response authority mismatch: read_review completed read identity",
            )
        }
    }

    private fun JSONObject.requireExactString(name: String, expected: String, context: String) {
        val actual = if (has(name) && !isNull(name)) opt(name) as? String else null
        if (actual != expected) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
    }

    private fun JSONObject.requireExactNullableString(name: String, expected: String?, context: String) {
        if (!has(name)) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
        if (isNull(name)) {
            if (expected != null) {
                throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
            }
            return
        }
        val actual = opt(name) as? String
        if (actual != expected) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
    }

    private fun JSONObject.requireExactInt(name: String, expected: Int, context: String) {
        val actual = strictInt(name)
        if (actual != expected) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
    }

    private fun JSONObject.requireBoolean(name: String, context: String): Boolean {
        if (!has(name) || isNull(name)) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
        return (opt(name) as? Boolean)
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
    }

    private fun JSONObject.requireInt(name: String, context: String): Int =
        strictInt(name)
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")

    private fun JSONObject.strictInt(name: String): Int? {
        val raw = if (has(name) && !isNull(name)) opt(name) else null
        return when (raw) {
            is Int -> raw
            is Long -> raw.takeIf { it in Int.MIN_VALUE.toLong()..Int.MAX_VALUE.toLong() }?.toInt()
            else -> null
        }
    }

    private fun JSONObject.requireString(name: String, context: String): String {
        if (!has(name) || isNull(name)) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
        return (opt(name) as? String)
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
    }

    private fun JSONObject.requireNonBlankString(name: String, context: String): String =
        requireString(name, context).takeIf { it.isNotBlank() }
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")

    private fun JSONObject.requireNullableString(name: String, context: String): String? {
        if (!has(name)) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
        if (isNull(name)) return null
        return (opt(name) as? String)
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
    }

    private fun JSONObject.requireNullableInt(name: String, context: String): Int? {
        if (!has(name)) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
        if (isNull(name)) return null
        return strictInt(name)
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
    }

    private fun JSONObject.requireNullableFiniteDouble(name: String, context: String): Double? {
        if (!has(name)) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
        if (isNull(name)) return null
        val raw = opt(name)
        val value = (raw as? Number)?.toDouble()
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        if (!value.isFinite() || value < 0.0) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
        return value
    }

    private fun JSONObject.requireStringArray(name: String, context: String): List<String> {
        val values = optJSONArray(name)
            ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        val result = buildList {
            for (index in 0 until values.length()) {
                val value = values.opt(index) as? String
                    ?: throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name[$index]")
                if (value.isBlank()) {
                    throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name[$index]")
                }
                add(value)
            }
        }
        if (result.distinct().size != result.size) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
        return result
    }

    private fun post(path: String, payload: JSONObject): JSONObject = execute(
        Request.Builder()
            .url(base + path)
            .post(payload.toString().toRequestBody(jsonType))
            .header("Authorization", "Bearer $token")
            .build(),
    )

    private fun execute(request: Request): JSONObject {
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val root = JSONObject(text)
                    root.optString("error").ifBlank { root.optString("detail") }
                }.getOrNull()?.ifBlank { null } ?: text.take(500)
                throw ModelRigException("Agent 3.0 replan failed (${response.code}): $detail")
            }
            return runCatching { JSONObject(text) }
                .getOrElse { throw ModelRigException("Agent 3.0 replan returned invalid JSON") }
        }
    }

    private fun parseRun(o: JSONObject): Agent3Client.Run = Agent3Client.Run(
        id = o.optString("id"),
        state = o.optString("state"),
        routeKind = o.optJSONObject("route")?.optString("kind").orEmpty(),
        currentStep = o.optInt("current_step"),
        steps = parseSteps(o.optJSONArray("steps") ?: JSONArray()),
        answer = o.nullableString("answer"),
        error = o.nullableString("error"),
        termination = null,
    )

    private fun parseReadReview(o: JSONObject?): Agent3Client.ReadReview {
        val review = o ?: JSONObject()
        return Agent3Client.ReadReview(
            enabled = review.optBoolean("enabled", false),
            waiting = review.optBoolean("waiting", false),
            windowStart = review.nullableInt("window_start"),
            windowEnd = review.nullableInt("window_end"),
            removableStepIds = review.optJSONArray("removable_step_ids").toStrings(),
            completedStepId = review.nullableString("completed_step_id"),
            completedTool = review.nullableString("completed_tool"),
            updatedAt = review.nullableDouble("updated_at"),
        )
    }

    private fun parseSteps(arr: JSONArray): List<Agent3Client.Step> = buildList {
        for (index in 0 until arr.length()) {
            val step = arr.optJSONObject(index) ?: continue
            add(
                Agent3Client.Step(
                    id = step.nullableString("id"),
                    tool = step.optString("tool"),
                    args = step.optJSONObject("args")?.toString() ?: "{}",
                    risk = step.optString("risk"),
                    sensitivity = step.optString("sensitivity"),
                    egress = step.optString("egress"),
                    summary = step.optString("summary"),
                    state = step.nullableString("state"),
                    confirmationDigest = step.nullableString("confirmation_digest"),
                    confirmationExpiresAt = step.nullableDouble("confirmation_expires_at"),
                    error = step.nullableString("error"),
                )
            )
        }
    }

    private fun JSONArray?.toStrings(): List<String> = buildList {
        val values = this@toStrings ?: return@buildList
        for (index in 0 until values.length()) {
            values.optString(index).takeIf { it.isNotBlank() }?.let(::add)
        }
    }

    private fun JSONObject.requireObject(name: String): JSONObject =
        optJSONObject(name) ?: throw ModelRigException("Agent 3.0 replan response missing '$name'")

    private fun JSONObject.nullableString(name: String): String? =
        if (!has(name) || isNull(name)) null else optString(name).ifBlank { null }

    private fun JSONObject.nullableInt(name: String): Int? =
        if (!has(name) || isNull(name)) null else optInt(name)

    private fun JSONObject.nullableDouble(name: String): Double? =
        if (!has(name) || isNull(name)) null else optDouble(name)

    /**
     * Encode een sti-komponent.
     *
     * Uden den aendrer et misdannet id HVILKET endpoint der rammes: maalt
     * 27/07-2026 gav runId="../../healthz" stien
     * /api/v1/experimental/healthz/confirm, fordi traversalen oploeses foer
     * requesten sendes. Id'erne kommer fra serveren i dag, saa det var ikke
     * udnytteligt -- men en klient boer ikke lade en vaerdi vaelge sin rute.
     *
     * Agent3MemoryClient gjorde det allerede; de oevrige gjorde ikke. Samme
     * form her, saa de fire klienter opfoerer sig ens.
     */
    private fun seg(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8.toString()).replace("+", "%20")

}
