package dk.ternedal.modelrig.net

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
    )

    fun preview(runId: String, plannerModel: String? = null): Preview {
        val body = JSONObject()
        plannerModel?.takeIf { it.isNotBlank() }?.let { body.put("planner_model", it) }
        val root = post("/api/v1/experimental/agent3/runs/$runId/replan-preview", body)
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

    fun apply(previewId: String): ApplyResult {
        val root = post(
            "/api/v1/experimental/agent3/replan-previews/$previewId/apply",
            JSONObject(),
        )
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
        )
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
    )

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

    private fun JSONObject.nullableDouble(name: String): Double? =
        if (!has(name) || isNull(name)) null else optDouble(name)
}
