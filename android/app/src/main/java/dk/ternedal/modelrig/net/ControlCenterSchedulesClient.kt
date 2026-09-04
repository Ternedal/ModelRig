package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Read-only Control Center projection of scheduler runtime + standing grants.
 *
 * This client intentionally knows only the two existing GET routes. It has no
 * preview/create/pause/renew/approval method, so the operations view cannot
 * acquire scheduler administration authority by accident.
 *
 * A standing grant is NOT an execution outcome. `structurally_eligible` is
 * therefore rendered only as grant metadata; occurrence/job truth is a later
 * ledger-backed Control Center slice.
 */
class ControlCenterSchedulesClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    fun snapshot(): ControlCenterScheduleSnapshot = ControlCenterScheduleSnapshot(
        runtime = parseRuntime(get("/api/v1/schedules/status", "scheduler status")),
        schedules = parseSchedules(get("/api/v1/schedules", "scheduler list")),
    )

    private fun get(path: String, label: String): JSONObject {
        val request = Request.Builder()
            .url(base + path)
            .header("Authorization", "Bearer $token")
            .get()
            .build()
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val root = JSONObject(body)
                    root.optString("error").ifBlank { root.optString("detail") }
                }.getOrDefault("").ifBlank { body }.take(500)
                throw ModelRigException("control center $label failed (${response.code}): $detail")
            }
            if (body.isBlank()) throw ModelRigException("control center $label returned an empty body")
            return JSONObject(body)
        }
    }

    internal fun parseRuntime(root: JSONObject): ControlCenterScheduleRuntime {
        val configured = root.requireBoolean("configured")
        val running = root.requireBoolean("running")
        val resourcesOpen = root.requireBoolean("resources_open")
        val lastError = root.optionalNullableString("last_error")
        val maxConcurrency = root.requireNonNegativeInt("max_concurrency")
        val queueCapacity = root.requireNonNegativeInt("queue_capacity")
        val activeExecutions = root.requireNonNegativeInt("active_executions")
        val acceptedTicks = root.requireNonNegativeInt("accepted_ticks")
        val overlapRejections = root.requireNonNegativeInt("overlap_rejections")

        if (running && !configured) fail("running runtime is not configured")
        if (activeExecutions > maxConcurrency) fail("active executions exceed max concurrency")

        return ControlCenterScheduleRuntime(
            configured = configured,
            running = running,
            resourcesOpen = resourcesOpen,
            lastError = lastError,
            maxConcurrency = maxConcurrency,
            queueCapacity = queueCapacity,
            activeExecutions = activeExecutions,
            acceptedTicks = acceptedTicks,
            overlapRejections = overlapRejections,
        )
    }

    internal fun parseSchedules(root: JSONObject): List<ControlCenterScheduleGrant> {
        val array = root.optJSONArray("schedules") ?: fail("schedules must be an array")
        val parsed = buildList {
            for (index in 0 until array.length()) {
                val item = array.optJSONObject(index) ?: fail("schedules[$index] must be an object")
                add(parseGrant(item))
            }
        }
        val ids = parsed.map { it.id }
        if (ids.size != ids.toSet().size) fail("duplicate schedule ids")
        return parsed.sortedWith(compareBy<ControlCenterScheduleGrant> { it.dueAt }.thenBy { it.id })
    }

    private fun parseGrant(item: JSONObject): ControlCenterScheduleGrant {
        val id = item.requireString("schedule_id")
        if (!Regex("^[0-9a-f]{12}$").matches(id)) fail("invalid schedule id")
        val tool = item.requireString("tool")
        val cadence = item.requireString("cadence")
        val timezone = item.requireString("timezone")
        val misfirePolicy = item.requireString("misfire_policy")
        val dueAtLocal = item.requireString("due_at_local")
        val risk = item.requireString("risk")
        val sensitivity = item.requireString("sensitivity")
        val expiresAt = item.requireFiniteNumber("expires_at")
        val expired = item.requireBoolean("expired")
        val maxRuns = item.requireNonNegativeInt("max_runs")
        val runsUsed = item.requireNonNegativeInt("runs_used")
        val budgetExhausted = item.requireBoolean("budget_exhausted")
        val dueAt = item.requireFiniteNumber("due_at")
        val missed = item.requireNonNegativeInt("missed")
        val enabled = item.requireBoolean("enabled")
        val structurallyEligible = item.requireBoolean("structurally_eligible")
        val runtimeGateChecked = item.requireBoolean("runtime_gate_checked")
        val blockedReason = item.optionalNullableString("blocked_reason")

        if (runtimeGateChecked) fail("admin list must not claim the runtime gate was checked")
        if (maxRuns > 0 && runsUsed > maxRuns) fail("runs_used exceeds max_runs")
        val expectedBudgetExhausted = maxRuns > 0 && runsUsed >= maxRuns
        if (budgetExhausted != expectedBudgetExhausted) fail("budget exhaustion contradicts run counters")
        if (structurallyEligible && (!enabled || expired || budgetExhausted || blockedReason != null)) {
            fail("structural eligibility contradicts grant state")
        }
        if (!structurallyEligible && blockedReason == null && enabled && !expired && !budgetExhausted) {
            fail("ineligible grant lacks a reason")
        }

        return ControlCenterScheduleGrant(
            id = id,
            tool = tool,
            cadence = cadence,
            timezone = timezone,
            misfirePolicy = misfirePolicy,
            dueAtLocal = dueAtLocal,
            risk = risk,
            sensitivity = sensitivity,
            expiresAt = expiresAt,
            expired = expired,
            maxRuns = maxRuns,
            runsUsed = runsUsed,
            budgetExhausted = budgetExhausted,
            dueAt = dueAt,
            missed = missed,
            enabled = enabled,
            structurallyEligible = structurallyEligible,
            blockedReason = blockedReason,
        )
    }

    private fun JSONObject.requireString(key: String): String {
        if (!has(key) || isNull(key) || get(key) !is String) fail("$key must be a string")
        return getString(key).trim().takeIf { it.isNotEmpty() } ?: fail("blank $key")
    }

    private fun JSONObject.requireBoolean(key: String): Boolean {
        if (!has(key) || isNull(key) || get(key) !is Boolean) fail("$key must be boolean")
        return getBoolean(key)
    }

    private fun JSONObject.requireNonNegativeInt(key: String): Int {
        if (!has(key) || isNull(key)) fail("$key must be an integer")
        val raw = get(key)
        if (raw !is Int) fail("$key must be an integer")
        if (raw < 0) fail("$key must be non-negative")
        return raw
    }

    private fun JSONObject.requireFiniteNumber(key: String): Double {
        if (!has(key) || isNull(key)) fail("$key must be numeric")
        val raw = get(key)
        if (raw !is Number || raw is Boolean) fail("$key must be numeric")
        val value = raw.toDouble()
        if (!value.isFinite()) fail("$key must be finite")
        return value
    }

    private fun JSONObject.optionalNullableString(key: String): String? {
        if (!has(key) || isNull(key)) return null
        val raw = get(key)
        if (raw !is String) fail("$key must be string or null")
        return raw.trim().takeIf { it.isNotEmpty() }
    }

    private fun fail(message: String): Nothing =
        throw ModelRigException("invalid control center schedules: $message")
}

data class ControlCenterScheduleSnapshot(
    val runtime: ControlCenterScheduleRuntime,
    val schedules: List<ControlCenterScheduleGrant>,
)

data class ControlCenterScheduleRuntime(
    val configured: Boolean,
    val running: Boolean,
    val resourcesOpen: Boolean,
    val lastError: String?,
    val maxConcurrency: Int,
    val queueCapacity: Int,
    val activeExecutions: Int,
    val acceptedTicks: Int,
    val overlapRejections: Int,
)

data class ControlCenterScheduleGrant(
    val id: String,
    val tool: String,
    val cadence: String,
    val timezone: String,
    val misfirePolicy: String,
    val dueAtLocal: String,
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
    val structurallyEligible: Boolean,
    val blockedReason: String?,
)
