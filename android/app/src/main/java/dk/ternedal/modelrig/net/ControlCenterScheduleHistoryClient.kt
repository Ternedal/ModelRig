package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Strict GET-only Android reader for T-044 occurrence/job history.
 *
 * The server owns all execution semantics. This client validates and preserves
 * that authority; it never derives an occurrence result from JobStore status.
 */
class ControlCenterScheduleHistoryClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    fun history(): ControlCenterScheduleHistory {
        val request = Request.Builder()
            .url(base + "/api/v1/control-center/schedules")
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
                throw ModelRigException(
                    "control center schedule history failed (${response.code}): $detail",
                )
            }
            if (body.isBlank()) {
                throw ModelRigException("control center schedule history returned an empty body")
            }
            val root = runCatching { JSONObject(body) }.getOrElse {
                throw ModelRigException("invalid control center schedule history: response must be a JSON object")
            }
            return parseHistory(root)
        }
    }

    internal fun parseHistory(root: JSONObject): ControlCenterScheduleHistory {
        root.requireExactKeys(TOP_LEVEL_KEYS, "history")
        if (root.requireString("schema") != SCHEMA) fail("wrong schema")
        val generatedAt = root.requireFiniteNumber("generated_at")
        if (root.requireBoolean("production_activation")) fail("production activation must remain false")

        val sources = root.requireObject("sources")
        sources.requireExactKeys(SOURCE_CONTAINER_KEYS, "sources")
        val occurrenceSource = parseSource(
            sources.requireObject("occurrence_ledger"),
            allowedStates = OCCURRENCE_SOURCE_STATES,
            label = "occurrence_ledger",
        )
        val jobsSource = parseSource(
            sources.requireObject("jobs"),
            allowedStates = JOB_SOURCE_STATES,
            label = "jobs",
        )

        val itemsArray = root.requireArray("items")
        val items = buildList {
            for (index in 0 until itemsArray.length()) {
                val raw = itemsArray.opt(index)
                if (raw !is JSONObject) fail("items[$index] must be an object")
                add(parseOccurrence(raw, index))
            }
        }
        val ids = items.map { it.occurrenceId }
        if (ids.size != ids.toSet().size) fail("duplicate occurrence ids")

        if (occurrenceSource.state == "unavailable" && items.isNotEmpty()) {
            fail("unavailable occurrence ledger cannot provide items")
        }
        val anyJobIds = items.any { it.jobId != null }
        val anyJobs = items.any { it.job != null }
        if (jobsSource.state == "not_required" && anyJobIds) {
            fail("jobs source is not_required despite referenced jobs")
        }
        if (jobsSource.state == "ready" && !anyJobIds) {
            fail("ready jobs source requires at least one referenced job")
        }
        if (jobsSource.state == "unavailable" && anyJobs) {
            fail("unavailable jobs source cannot provide job observations")
        }

        return ControlCenterScheduleHistory(
            generatedAt = generatedAt,
            occurrenceSource = occurrenceSource,
            jobsSource = jobsSource,
            items = items,
        )
    }

    private fun parseSource(
        raw: JSONObject,
        *,
        allowedStates: Set<String>,
        label: String,
    ): ControlCenterHistorySource {
        raw.requireExactKeys(SOURCE_KEYS, label)
        val state = raw.requireString("state")
        if (state !in allowedStates) fail("unknown $label source state")
        val reason = raw.requireNullableString("reason")
        if (state == "unavailable" && reason == null) fail("unavailable $label source lacks a reason")
        if (state != "unavailable" && reason != null) fail("$label source reason contradicts state")
        return ControlCenterHistorySource(state = state, reason = reason)
    }

    private fun parseOccurrence(raw: JSONObject, index: Int): ControlCenterOccurrenceHistoryItem {
        raw.requireExactKeys(OCCURRENCE_KEYS, "items[$index]")
        val occurrenceId = raw.requireString("occurrence_id")
        val scheduleId = raw.requireString("schedule_id")
        val tool = raw.requireNullableString("tool")
        val dueAt = raw.requireFiniteNumber("due_at")
        val status = raw.requireString("occurrence_status")
        if (status !in OCCURRENCE_STATUSES) fail("unknown occurrence status")
        val inFlight = raw.requireNullableBoolean("in_flight")
        val terminalOutcome = raw.requireNullableString("terminal_outcome")
        val expectedInFlight: Boolean? = when (status) {
            "reserved", "reserved_noslot" -> true
            "executed", "released", "abandoned", "unknown" -> false
            "unknown_schema_value" -> null
            else -> error("validated occurrence status")
        }
        val expectedOutcome: String? = when (status) {
            "reserved", "reserved_noslot" -> null
            "executed" -> "executed"
            "released" -> "not_run"
            "abandoned" -> "abandoned"
            "unknown", "unknown_schema_value" -> "unknown"
            else -> error("validated occurrence status")
        }
        if (inFlight != expectedInFlight) fail("in_flight contradicts occurrence status")
        if (terminalOutcome != expectedOutcome) fail("terminal outcome contradicts occurrence status")

        val createdAt = raw.requireFiniteNumber("created_at")
        val resolvedAt = raw.requireNullableFiniteNumber("resolved_at")
        val jobId = raw.requireNullableString("job_id")
        val jobRaw = raw.requireNullableObject("job")
        if (jobRaw != null && jobId == null) fail("job observation lacks job_id")
        val job = jobRaw?.let { parseJob(it, index) }

        return ControlCenterOccurrenceHistoryItem(
            occurrenceId = occurrenceId,
            scheduleId = scheduleId,
            tool = tool,
            dueAt = dueAt,
            occurrenceStatus = status,
            inFlight = inFlight,
            terminalOutcome = terminalOutcome,
            createdAt = createdAt,
            resolvedAt = resolvedAt,
            jobId = jobId,
            job = job,
        )
    }

    private fun parseJob(raw: JSONObject, index: Int): ControlCenterObservedJob {
        raw.requireExactKeys(JOB_KEYS, "items[$index].job")
        val status = raw.requireString("status")
        if (status !in JOB_STATUSES) fail("unknown job status")
        return ControlCenterObservedJob(
            status = status,
            kind = raw.requireString("kind"),
            progressCompleted = raw.requireNonNegativeLong("progress_completed"),
            progressTotal = raw.requireNonNegativeLong("progress_total"),
            createdAt = raw.requireFiniteNumber("created_at"),
            updatedAt = raw.requireFiniteNumber("updated_at"),
        )
    }

    private fun JSONObject.requireExactKeys(expected: Set<String>, label: String) {
        val actual = keys().asSequence().toSet()
        if (actual != expected) fail("$label fields do not match the v1 contract")
    }

    private fun JSONObject.requireString(key: String): String {
        if (!has(key) || isNull(key) || get(key) !is String) fail("$key must be a string")
        return getString(key).trim().takeIf { it.isNotEmpty() } ?: fail("blank $key")
    }

    private fun JSONObject.requireNullableString(key: String): String? {
        if (!has(key)) fail("missing $key")
        if (isNull(key)) return null
        val raw = get(key)
        if (raw !is String) fail("$key must be string or null")
        return raw.trim().takeIf { it.isNotEmpty() } ?: fail("blank $key")
    }

    private fun JSONObject.requireBoolean(key: String): Boolean {
        if (!has(key) || isNull(key) || get(key) !is Boolean) fail("$key must be boolean")
        return getBoolean(key)
    }

    private fun JSONObject.requireNullableBoolean(key: String): Boolean? {
        if (!has(key)) fail("missing $key")
        if (isNull(key)) return null
        val raw = get(key)
        if (raw !is Boolean) fail("$key must be boolean or null")
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

    private fun JSONObject.requireNullableFiniteNumber(key: String): Double? {
        if (!has(key)) fail("missing $key")
        if (isNull(key)) return null
        return requireFiniteNumber(key)
    }

    private fun JSONObject.requireNonNegativeLong(key: String): Long {
        if (!has(key) || isNull(key)) fail("$key must be an integer")
        val value = when (val raw = get(key)) {
            is Int -> raw.toLong()
            is Long -> raw
            else -> fail("$key must be an integer")
        }
        if (value < 0L) fail("$key must be non-negative")
        return value
    }

    private fun JSONObject.requireObject(key: String): JSONObject {
        if (!has(key) || isNull(key) || get(key) !is JSONObject) fail("$key must be an object")
        return getJSONObject(key)
    }

    private fun JSONObject.requireNullableObject(key: String): JSONObject? {
        if (!has(key)) fail("missing $key")
        if (isNull(key)) return null
        val raw = get(key)
        if (raw !is JSONObject) fail("$key must be object or null")
        return raw
    }

    private fun JSONObject.requireArray(key: String): JSONArray {
        if (!has(key) || isNull(key) || get(key) !is JSONArray) fail("$key must be an array")
        return getJSONArray(key)
    }

    private fun fail(message: String): Nothing =
        throw ModelRigException("invalid control center schedule history: $message")

    private companion object {
        const val SCHEMA = "kaliv-control-center-schedule-history/v1"

        val TOP_LEVEL_KEYS = setOf("schema", "generated_at", "sources", "items", "production_activation")
        val SOURCE_CONTAINER_KEYS = setOf("occurrence_ledger", "jobs")
        val SOURCE_KEYS = setOf("state", "reason")
        val OCCURRENCE_KEYS = setOf(
            "occurrence_id",
            "schedule_id",
            "tool",
            "due_at",
            "occurrence_status",
            "in_flight",
            "terminal_outcome",
            "created_at",
            "resolved_at",
            "job_id",
            "job",
        )
        val JOB_KEYS = setOf(
            "status",
            "kind",
            "progress_completed",
            "progress_total",
            "created_at",
            "updated_at",
        )
        val OCCURRENCE_SOURCE_STATES = setOf("ready", "unavailable")
        val JOB_SOURCE_STATES = setOf("ready", "unavailable", "not_required")
        val OCCURRENCE_STATUSES = setOf(
            "reserved",
            "reserved_noslot",
            "executed",
            "released",
            "abandoned",
            "unknown",
            "unknown_schema_value",
        )
        val JOB_STATUSES = setOf(
            "queued",
            "running",
            "completed",
            "failed",
            "cancelled",
            "interrupted",
            "unknown_schema_value",
        )
    }
}

data class ControlCenterScheduleHistory(
    val generatedAt: Double,
    val occurrenceSource: ControlCenterHistorySource,
    val jobsSource: ControlCenterHistorySource,
    val items: List<ControlCenterOccurrenceHistoryItem>,
)

data class ControlCenterHistorySource(
    val state: String,
    val reason: String?,
)

data class ControlCenterOccurrenceHistoryItem(
    val occurrenceId: String,
    val scheduleId: String,
    val tool: String?,
    val dueAt: Double,
    val occurrenceStatus: String,
    val inFlight: Boolean?,
    val terminalOutcome: String?,
    val createdAt: Double,
    val resolvedAt: Double?,
    val jobId: String?,
    val job: ControlCenterObservedJob?,
)

data class ControlCenterObservedJob(
    val status: String,
    val kind: String,
    val progressCompleted: Long,
    val progressTotal: Long,
    val createdAt: Double,
    val updatedAt: Double,
)
