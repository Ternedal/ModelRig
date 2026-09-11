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
        val start: Int,
        val oldEnd: Int,
        val newEnd: Int,
        val removedStepIds: List<String>,
        val removedTools: List<String>,
        val addedStepIds: List<String>,
        val addedTools: List<String>,
        val immutablePrefixIds: List<String>,
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

    private data class ReviewedPreviewStepAuthority(
        val id: String,
        val tool: String,
        val args: String,
        val risk: String,
        val sensitivity: String,
        val egress: String,
        val summary: String,
    )

    private data class ReviewedPreviewAuthority(
        val previewId: String,
        val expiresInSeconds: Int,
        val runId: String,
        val revision: Int,
        val replanCount: Int,
        val rationale: String,
        val plannerModel: String?,
        val promptSha256: String,
        val observationCharacters: Int,
        val windowStart: Int,
        val windowEnd: Int,
        val removableStepIds: List<String>,
        val immutablePrefixIds: List<String>,
        val immutableTailIds: List<String>,
        val steps: List<ReviewedPreviewStepAuthority>,
    )

    fun preview(runId: String, plannerModel: String? = null): Preview {
        val body = JSONObject()
        plannerModel?.takeIf { it.isNotBlank() }?.let { body.put("planner_model", it) }
        val root = post("/api/v1/experimental/agent3/runs/${seg(runId)}/replan-preview", body)
        return parsePreview(root)
    }

    /**
     * Reviewed Preview boundary. Every server-owned field shown to the operator
     * must be explicit and type-safe before permissive JSONObject defaults can
     * represent the stored proposal.
     */
    fun previewReviewed(runId: String, plannerModel: String? = null): Preview {
        val expectedRunId = runId.trim()
        if (expectedRunId.isBlank()) {
            throw ModelRigException("Invalid Agent 3.0 reviewed replan run id")
        }
        val expectedPlannerModel = plannerModel?.trim()?.takeIf { it.isNotEmpty() }
        val body = JSONObject()
        expectedPlannerModel?.let { body.put("planner_model", it) }
        val root = post(
            "/api/v1/experimental/agent3/runs/${seg(expectedRunId)}/replan-preview",
            body,
        )
        val authority = validateReviewedPreviewResponse(
            root = root,
            expectedRunId = expectedRunId,
            expectedPlannerModel = expectedPlannerModel,
        )
        val preview = parsePreview(root)
        validateTypedReviewedPreview(preview, authority)
        return preview
    }

    private fun parsePreview(root: JSONObject): Preview {
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
     * single-use preview, deterministic revision receipt and post-Apply review
     * checkpoint are coherent before any result is returned to UI state.
     */
    fun applyReviewed(reviewedPreview: Preview): ApplyResult {
        if (reviewedPreview.revision == Int.MAX_VALUE || reviewedPreview.replanCount == Int.MAX_VALUE) {
            throw ModelRigException("Agent 3.0 replan reviewed Preview has invalid revision authority")
        }
        val root = postApply(reviewedPreview.previewId)
        val readReviewObject = root.requireObject("read_review")
        val receiptObject = root.requireObject("replan")
        validateReviewedApplyResponse(root, reviewedPreview)
        val receiptAuthority = validateReviewedReplanReceiptShape(receiptObject, reviewedPreview)
        val result = parseApplyResult(root)
        validateReviewedReplanReceiptBinding(receiptAuthority, result)
        validateReviewedReadReview(readReviewObject, result.run, result.readReview)
        return result
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
                start = receipt.optInt("start"),
                oldEnd = receipt.optInt("old_end"),
                newEnd = receipt.optInt("new_end"),
                removedStepIds = receipt.optJSONArray("removed_step_ids").toStrings(),
                removedTools = receipt.optJSONArray("removed_tools").toStrings(),
                addedStepIds = receipt.optJSONArray("added_step_ids").toStrings(),
                addedTools = receipt.optJSONArray("added_tools").toStrings(),
                immutablePrefixIds = receipt.optJSONArray("immutable_prefix_ids").toStrings(),
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

    private fun validateReviewedPreviewResponse(
        root: JSONObject,
        expectedRunId: String,
        expectedPlannerModel: String?,
    ): ReviewedPreviewAuthority {
        val previewId = root.requirePreviewNonBlankString("preview_id")
        val expiresInSeconds = root.requirePreviewInt("expires_in_seconds")
        if (expiresInSeconds <= 0) previewMismatch("expires_in_seconds")

        val runId = root.requirePreviewNonBlankString("run_id")
        if (runId != expectedRunId) previewMismatch("run_id")

        val revision = root.requirePreviewInt("revision")
        val replanCount = root.requirePreviewInt("replan_count")
        if (revision < 0 || revision == Int.MAX_VALUE) previewMismatch("revision")
        if (replanCount < 0 || replanCount == Int.MAX_VALUE) previewMismatch("replan_count")

        val rationale = root.requirePreviewNonBlankString("rationale")
        if (rationale.length > 500) previewMismatch("rationale")

        val plannerModel = root.requirePreviewNullableString("planner_model")
        if (plannerModel != expectedPlannerModel) previewMismatch("planner_model")

        val promptSha256 = root.requirePreviewNonBlankString("prompt_sha256")
        if (!Regex("^[0-9a-f]{64}$").matches(promptSha256)) previewMismatch("prompt_sha256")

        val observationCharacters = root.requirePreviewInt("observation_characters")
        if (observationCharacters < 0) previewMismatch("observation_characters")

        val executed = root.requirePreviewBoolean("executed")
        if (executed) previewMismatch("executed")

        val window = root.requirePreviewObject("window")
        val windowStart = window.requirePreviewInt("start", "window")
        val windowEnd = window.requirePreviewInt("end", "window")
        val removableStepIds = window.requirePreviewStringArray("removable_step_ids", "window")
        val immutablePrefixIds = window.requirePreviewStringArray("immutable_prefix_ids", "window")
        val immutableTailIds = window.requirePreviewStringArray("immutable_tail_ids", "window")
        if (
            windowStart < 0 ||
            windowEnd <= windowStart ||
            removableStepIds.size != windowEnd - windowStart ||
            immutablePrefixIds.size != windowStart
        ) {
            previewMismatch("window")
        }
        val allWindowIds = immutablePrefixIds + removableStepIds + immutableTailIds
        if (allWindowIds.size != allWindowIds.distinct().size) {
            previewMismatch("window.step_ids")
        }

        val rawPlan = root.opt("plan") as? JSONArray ?: previewMismatch("plan")
        val steps = buildList {
            for (index in 0 until rawPlan.length()) {
                val step = rawPlan.opt(index) as? JSONObject ?: previewMismatch("plan[$index]")
                val id = step.requirePreviewNonBlankString("id", "plan[$index]")
                val tool = step.requirePreviewNonBlankString("tool", "plan[$index]")
                val args = step.requirePreviewObject("args", "plan[$index]")
                val risk = step.requirePreviewNonBlankString("risk", "plan[$index]")
                val sensitivity = step.requirePreviewNonBlankString("sensitivity", "plan[$index]")
                val egress = step.requirePreviewNonBlankString("egress", "plan[$index]")
                val summary = step.requirePreviewString("summary", "plan[$index]")
                if (risk != "read") previewMismatch("plan[$index].risk")
                if (egress != "local") previewMismatch("plan[$index].egress")
                add(
                    ReviewedPreviewStepAuthority(
                        id = id,
                        tool = tool,
                        args = args.toString(),
                        risk = risk,
                        sensitivity = sensitivity,
                        egress = egress,
                        summary = summary,
                    ),
                )
            }
        }
        val replacementIds = steps.map { it.id }
        if (replacementIds.size != replacementIds.distinct().size) {
            previewMismatch("plan.step_ids")
        }
        val immutableIds = (immutablePrefixIds + immutableTailIds).toSet()
        if (replacementIds.any { it in immutableIds }) {
            previewMismatch("plan.step_ids")
        }

        return ReviewedPreviewAuthority(
            previewId = previewId,
            expiresInSeconds = expiresInSeconds,
            runId = runId,
            revision = revision,
            replanCount = replanCount,
            rationale = rationale,
            plannerModel = plannerModel,
            promptSha256 = promptSha256,
            observationCharacters = observationCharacters,
            windowStart = windowStart,
            windowEnd = windowEnd,
            removableStepIds = removableStepIds,
            immutablePrefixIds = immutablePrefixIds,
            immutableTailIds = immutableTailIds,
            steps = steps,
        )
    }

    private fun validateTypedReviewedPreview(
        preview: Preview,
        authority: ReviewedPreviewAuthority,
    ) {
        val typedSteps = preview.plan.mapIndexed { index, step ->
            ReviewedPreviewStepAuthority(
                id = step.id?.takeIf { it.isNotBlank() }
                    ?: previewMismatch("typed_preview.plan[$index].id"),
                tool = step.tool,
                args = step.args,
                risk = step.risk,
                sensitivity = step.sensitivity,
                egress = step.egress,
                summary = step.summary,
            )
        }
        if (
            preview.previewId != authority.previewId ||
            preview.expiresInSeconds != authority.expiresInSeconds ||
            preview.runId != authority.runId ||
            preview.revision != authority.revision ||
            preview.replanCount != authority.replanCount ||
            preview.rationale != authority.rationale ||
            preview.plannerModel != authority.plannerModel ||
            preview.promptSha256 != authority.promptSha256 ||
            preview.observationCharacters != authority.observationCharacters ||
            preview.executed ||
            preview.window.start != authority.windowStart ||
            preview.window.end != authority.windowEnd ||
            preview.window.removableStepIds != authority.removableStepIds ||
            preview.window.immutablePrefixIds != authority.immutablePrefixIds ||
            preview.window.immutableTailIds != authority.immutableTailIds ||
            typedSteps != authority.steps
        ) {
            previewMismatch("typed_preview")
        }
    }

    private fun validateReviewedApplyResponse(root: JSONObject, reviewed: Preview) {
        val run = root.requireObject("run")
        val receipt = root.requireObject("replan")
        val appliedPreview = root.requireObject("preview")

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
    }

    private fun validateReviewedReadReview(
        raw: JSONObject,
        run: Agent3Client.Run,
        review: Agent3Client.ReadReview,
    ) {
        val enabled = raw.requireBoolean("enabled", "read_review")
        val waiting = raw.requireBoolean("waiting", "read_review")
        val rawRemovable = raw.opt("removable_step_ids") as? JSONArray
            ?: throw ModelRigException(
                "Agent 3.0 replan Apply response authority mismatch: read_review.removable_step_ids",
            )
        val removableIds = rawRemovable.requireNonBlankStrings("read_review.removable_step_ids")

        if (enabled != review.enabled || waiting != review.waiting || removableIds != review.removableStepIds) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: read_review")
        }

        if (!waiting) {
            if (
                review.windowStart != null ||
                review.windowEnd != null ||
                removableIds.isNotEmpty() ||
                review.completedStepId != null ||
                review.completedTool != null
            ) {
                throw ModelRigException(
                    "Agent 3.0 replan Apply response authority mismatch: cleared read_review checkpoint",
                )
            }
            return
        }

        if (!enabled || run.state != "running") {
            throw ModelRigException(
                "Agent 3.0 replan Apply response authority mismatch: waiting read_review state",
            )
        }
        val start = raw.requireInt("window_start", "read_review")
        val end = raw.requireInt("window_end", "read_review")
        if (
            review.windowStart != start ||
            review.windowEnd != end ||
            start != run.currentStep ||
            start < 0 ||
            end <= start ||
            end > run.steps.size
        ) {
            throw ModelRigException(
                "Agent 3.0 replan Apply response authority mismatch: read_review window",
            )
        }

        val window = run.steps.subList(start, end)
        if (window.any { it.id.isNullOrBlank() || it.risk != "read" || it.state != "pending" }) {
            throw ModelRigException(
                "Agent 3.0 replan Apply response authority mismatch: read_review window steps",
            )
        }
        val expectedIds = window.map { requireNotNull(it.id) }
        if (removableIds != expectedIds) {
            throw ModelRigException(
                "Agent 3.0 replan Apply response authority mismatch: read_review.removable_step_ids",
            )
        }
        raw.requireNonBlankString("completed_step_id", "read_review")
        raw.requireNonBlankString("completed_tool", "read_review")
        if (review.completedStepId.isNullOrBlank() || review.completedTool.isNullOrBlank()) {
            throw ModelRigException(
                "Agent 3.0 replan Apply response authority mismatch: read_review completed checkpoint",
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
        val actual = rawInt(name)
        if (actual != expected) {
            throw ModelRigException("Agent 3.0 replan Apply response authority mismatch: $context.$name")
        }
    }

    private fun JSONObject.requireBoolean(name: String, context: String): Boolean {
        val actual = if (has(name) && !isNull(name)) opt(name) as? Boolean else null
        return actual ?: throw ModelRigException(
            "Agent 3.0 replan Apply response authority mismatch: $context.$name",
        )
    }

    private fun JSONObject.requireInt(name: String, context: String): Int =
        rawInt(name) ?: throw ModelRigException(
            "Agent 3.0 replan Apply response authority mismatch: $context.$name",
        )

    private fun JSONObject.requireNonBlankString(name: String, context: String): String {
        val actual = if (has(name) && !isNull(name)) opt(name) as? String else null
        return actual?.takeIf { it.isNotBlank() } ?: throw ModelRigException(
            "Agent 3.0 replan Apply response authority mismatch: $context.$name",
        )
    }

    private fun JSONObject.requirePreviewObject(name: String, context: String = ""): JSONObject =
        (opt(name) as? JSONObject)
            ?: previewMismatch(if (context.isBlank()) name else "$context.$name")

    private fun JSONObject.requirePreviewString(name: String, context: String = ""): String =
        (opt(name) as? String)
            ?: previewMismatch(if (context.isBlank()) name else "$context.$name")

    private fun JSONObject.requirePreviewNonBlankString(name: String, context: String = ""): String =
        requirePreviewString(name, context).takeIf { it.isNotBlank() }
            ?: previewMismatch(if (context.isBlank()) name else "$context.$name")

    private fun JSONObject.requirePreviewNullableString(name: String): String? {
        if (!has(name)) previewMismatch(name)
        if (isNull(name)) return null
        return (opt(name) as? String)?.takeIf { it.isNotBlank() } ?: previewMismatch(name)
    }

    private fun JSONObject.requirePreviewInt(name: String, context: String = ""): Int =
        rawInt(name) ?: previewMismatch(if (context.isBlank()) name else "$context.$name")

    private fun JSONObject.requirePreviewBoolean(name: String): Boolean =
        (opt(name) as? Boolean) ?: previewMismatch(name)

    private fun JSONObject.requirePreviewStringArray(name: String, context: String): List<String> {
        val raw = opt(name) as? JSONArray ?: previewMismatch("$context.$name")
        return buildList {
            for (index in 0 until raw.length()) {
                val value = raw.opt(index) as? String
                if (value.isNullOrBlank()) previewMismatch("$context.$name")
                add(value)
            }
        }
    }

    private fun previewMismatch(field: String): Nothing =
        throw ModelRigException("Agent 3.0 replan Preview response authority mismatch: $field")

    private fun JSONObject.rawInt(name: String): Int? {
        val raw = if (has(name) && !isNull(name)) opt(name) else null
        return when (raw) {
            is Int -> raw
            is Long -> raw.takeIf { it in Int.MIN_VALUE.toLong()..Int.MAX_VALUE.toLong() }?.toInt()
            else -> null
        }
    }

    private fun JSONArray.requireNonBlankStrings(context: String): List<String> = buildList {
        for (index in 0 until length()) {
            val value = opt(index) as? String
            if (value.isNullOrBlank()) {
                throw ModelRigException(
                    "Agent 3.0 replan Apply response authority mismatch: $context",
                )
            }
            add(value)
        }
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
