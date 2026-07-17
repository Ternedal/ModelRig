package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Authenticated client for the human-only scheduler administration surface.
 *
 * It never calls the worker directly. The paired-device token goes only to the
 * Go backend, which authenticates the operator session. Scheduled writes are a
 * three-step flow: preview the complete standing grant, let the user confirm the
 * card, then ask the backend for a short-lived single-use approval token and use
 * it immediately for create/renew. The predictable preview fingerprint is never
 * accepted by the worker as evidence of consent.
 */
class ScheduleClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val jsonType = "application/json".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    fun status(): ScheduleRuntimeStatus = parseStatus(get("/api/v1/schedules/status"))

    fun list(): List<ScheduleItem> {
        val arr = get("/api/v1/schedules").optJSONArray("schedules") ?: JSONArray()
        return (0 until arr.length()).map { parseItem(arr.getJSONObject(it)) }
    }

    fun preview(
        tool: String,
        args: JSONObject,
        cadence: String,
        ttlDays: Int,
        maxRuns: Int,
    ): SchedulePreview {
        val body = JSONObject()
            .put("tool", tool)
            .put("args", args)
            .put("cadence", cadence)
            .put("ttl_days", ttlDays)
            .put("max_runs", maxRuns)
        return parsePreview(post("/api/v1/schedules/preview", body).getJSONObject("preview"))
    }

    fun create(preview: SchedulePreview): ScheduleItem {
        val body = JSONObject()
            .put("tool", preview.tool)
            .put("args", JSONObject(preview.argsJson))
            .put("cadence", preview.cadence)
            .put("ttl_days", preview.ttlDays)
            .put("max_runs", preview.maxRuns)
        approvalTokenForCreate(preview)?.let { body.put("approval_token", it) }
        return parseItem(post("/api/v1/schedules", body).getJSONObject("schedule"))
    }

    fun setEnabled(scheduleId: String, enabled: Boolean): ScheduleItem =
        parseItem(
            post(
                "/api/v1/schedules/$scheduleId/enabled",
                JSONObject().put("enabled", enabled),
            ).getJSONObject("schedule"),
        )

    fun previewRenewal(
        scheduleId: String,
        ttlDays: Int,
        maxRuns: Int,
        enable: Boolean?,
    ): SchedulePreview {
        val body = JSONObject()
            .put("ttl_days", ttlDays)
            .put("max_runs", maxRuns)
        if (enable != null) body.put("enable", enable)
        return parsePreview(
            post("/api/v1/schedules/$scheduleId/renew/preview", body)
                .getJSONObject("preview"),
        )
    }

    fun renew(preview: SchedulePreview): ScheduleItem {
        val scheduleId = preview.scheduleId
            ?: throw ModelRigException("renewal preview mangler schedule id")
        val body = JSONObject()
            .put("ttl_days", preview.ttlDays)
            .put("max_runs", preview.maxRuns)
        if (preview.enable != null) body.put("enable", preview.enable)
        approvalTokenForRenewal(preview, scheduleId)?.let { body.put("approval_token", it) }
        return parseItem(
            post("/api/v1/schedules/$scheduleId/renew", body)
                .getJSONObject("schedule"),
        )
    }

    private fun approvalTokenForCreate(preview: SchedulePreview): String? {
        if (!preview.requiresApproval) return null
        val fingerprint = preview.approvalFingerprint
            ?: throw ModelRigException("write preview mangler serverens preview-fingerprint")
        val body = JSONObject()
            .put("tool", preview.tool)
            .put("args", JSONObject(preview.argsJson))
            .put("cadence", preview.cadence)
            .put("ttl_days", preview.ttlDays)
            .put("max_runs", preview.maxRuns)
            .put("preview_fingerprint", fingerprint)
        return post("/api/v1/schedules/approve", body).getString("approval_token")
    }

    private fun approvalTokenForRenewal(preview: SchedulePreview, scheduleId: String): String? {
        if (!preview.requiresApproval) return null
        val fingerprint = preview.approvalFingerprint
            ?: throw ModelRigException("renewal preview mangler serverens preview-fingerprint")
        val body = JSONObject()
            .put("ttl_days", preview.ttlDays)
            .put("max_runs", preview.maxRuns)
            .put("preview_fingerprint", fingerprint)
        if (preview.enable != null) body.put("enable", preview.enable)
        return post("/api/v1/schedules/$scheduleId/renew/approve", body)
            .getString("approval_token")
    }

    private fun get(path: String): JSONObject = execute(
        Request.Builder().url(base + path).get(),
        "scheduler GET $path",
    )

    private fun post(path: String, payload: JSONObject): JSONObject = execute(
        Request.Builder()
            .url(base + path)
            .post(payload.toString().toRequestBody(jsonType)),
        "scheduler POST $path",
    )

    private fun execute(builder: Request.Builder, label: String): JSONObject {
        builder.header("Authorization", "Bearer $token")
        http.newCall(builder.build()).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val upstreamDetail = runCatching {
                    val json = JSONObject(body)
                    json.optString("detail").ifBlank { json.optString("error") }
                }.getOrDefault("").ifBlank { body }
                val detail = if (response.code == 404) {
                    "Plan-API'et er slået fra på backend. Sæt KALIV_SCHEDULER_API=1 og genstart backend."
                } else {
                    upstreamDetail
                }
                throw ModelRigException("$label failed (${response.code}): $detail")
            }
            if (body.isBlank()) throw ModelRigException("$label returned an empty body")
            return JSONObject(body)
        }
    }

    private fun parseStatus(o: JSONObject) = ScheduleRuntimeStatus(
        configured = o.optBoolean("configured"),
        running = o.optBoolean("running"),
        resourcesOpen = o.optBoolean("resources_open"),
        lastError = o.optString("last_error").takeUnless { it.isBlank() || it == "null" },
    )

    private fun parsePreview(o: JSONObject) = SchedulePreview(
        operation = o.optString("operation", "create"),
        scheduleId = o.optString("schedule_id").takeUnless { it.isBlank() || it == "null" },
        tool = o.getString("tool"),
        argsJson = o.optJSONObject("args")?.toString() ?: "{}",
        cadence = o.getString("cadence"),
        risk = o.optString("risk"),
        sensitivity = o.optString("sensitivity"),
        humanSummary = o.optString("human_summary"),
        requiresApproval = o.optBoolean("requires_approval"),
        approvalFingerprint = o.optString("approval_fingerprint")
            .takeUnless { it.isBlank() || it == "null" },
        dueAt = o.optDouble("due_at"),
        expiresAt = o.optDouble("expires_at"),
        ttlDays = o.optInt("ttl_days"),
        maxRuns = o.optInt("max_runs"),
        enable = if (o.has("enable") && !o.isNull("enable")) o.getBoolean("enable") else null,
    )

    private fun parseItem(o: JSONObject) = ScheduleItem(
        id = o.getString("schedule_id"),
        tool = o.getString("tool"),
        argsJson = o.optJSONObject("args")?.toString() ?: "{}",
        cadence = o.getString("cadence"),
        risk = o.optString("risk"),
        sensitivity = o.optString("sensitivity"),
        expiresAt = o.optDouble("expires_at"),
        expired = o.optBoolean("expired"),
        maxRuns = o.optInt("max_runs"),
        runsUsed = o.optInt("runs_used"),
        budgetExhausted = o.optBoolean("budget_exhausted"),
        dueAt = o.optDouble("due_at"),
        missed = o.optInt("missed"),
        enabled = o.optBoolean("enabled"),
        eligible = o.optBoolean("eligible"),
        approvalValid = o.optBoolean("approval_valid"),
        blockedReason = o.optString("blocked_reason").takeUnless { it.isBlank() || it == "null" },
        toolLayerEnabled = o.optBoolean("tool_layer_enabled"),
        toolDisabled = o.optBoolean("tool_disabled"),
    )
}

data class ScheduleRuntimeStatus(
    val configured: Boolean,
    val running: Boolean,
    val resourcesOpen: Boolean,
    val lastError: String?,
)

data class SchedulePreview(
    val operation: String,
    val scheduleId: String?,
    val tool: String,
    val argsJson: String,
    val cadence: String,
    val risk: String,
    val sensitivity: String,
    val humanSummary: String,
    val requiresApproval: Boolean,
    val approvalFingerprint: String?,
    val dueAt: Double,
    val expiresAt: Double,
    val ttlDays: Int,
    val maxRuns: Int,
    val enable: Boolean?,
)

data class ScheduleItem(
    val id: String,
    val tool: String,
    val argsJson: String,
    val cadence: String,
    val risk: String,
    val sensitivity: String,
    val expiresAt: Double,
    val expired: Boolean,
    val maxRuns: Int,
    val runsUsed: Int,
    val budgetExhausted: Boolean,
    val dueAt: Double,
    val missed: Int,
    val enabled: Boolean,
    val eligible: Boolean,
    val approvalValid: Boolean,
    val blockedReason: String?,
    val toolLayerEnabled: Boolean,
    val toolDisabled: Boolean,
)
