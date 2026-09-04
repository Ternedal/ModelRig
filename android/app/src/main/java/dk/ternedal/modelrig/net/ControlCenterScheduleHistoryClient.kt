package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Read-only client for the durable Control Center schedule occurrence/job projection.
 *
 * Occurrence state is the execution authority. Job state is intentionally parsed as
 * an independent observation and never used to infer or rewrite occurrence outcome.
 */
class ControlCenterScheduleHistoryClient(baseUrl: String, private val token: String) {
    companion object {
        const val SCHEMA = "kaliv-control-center-schedule-history/v1"
        private val OCCURRENCE_SOURCE_STATES = setOf("ready", "unavailable")
        private val JOB_SOURCE_STATES = setOf("ready", "unavailable", "not_required")
        private val OCCURRENCE_STATES = setOf(
            "reserved",
            "reserved_noslot",
            "executed",
            "released",
            "abandoned",
            "unknown",
            "unknown_schema_value",
        )
        private val JOB_STATES = setOf(
            "queued",
            "running",
            "completed",
            "failed",
            "cancelled",
            "interrupted",
            "unknown_schema_value",
        )
        private val TERMINAL_OUTCOMES = setOf("executed", "not_run", "abandoned", "unknown")
    }

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
                throw ModelRigException("control center schedule history failed (${response.code}): $detail")
            }
            if (body.isBlank()) {
                throw ModelRigException("control center schedule history returned an empty body")
            }
            return parse(JSONObject(body))
        }
    }

    internal fun parse(root: JSONObject): ControlCenterScheduleHistory {
        val schema = root.requireString("schema")
        if (schema != SCHEMA) fail("unsupported schema $schema")
        val generatedAt = root.requireFiniteNumber("generated_at")
        val productionActivation = root.requireBoolean("production_activation")
        if (productionActivation) fail("production_activation must remain false")

        val sources = root.requireObject("sources")
        val occurrenceSource = parseSource(
            sources.requireObject("occurrence_ledger"),
            "occurrence_ledger",
            OCCURRENCE_SOURCE_STATES,
        )
        val jobsSource = parseSource(
            sources.requireObject("jobs"),
            "jobs",
            JOB_SOURCE_STATES,
        )

        val array = root.optJSONArray("items") ?: fail("items must be an array")
        val items = buildList {
            for (index in 0 until array.length()) {
                val item = array.optJSONObject(index) ?: fail("items[$index] must be an object")
                add(parseOccurrence(item, index))
            }
        }
        val ids = items.map { it.occurrenceId }
        if (ids.size != ids.toSet().size) fail("duplicate occurrence ids")
        if (occurrenceSource.state != "ready" && items.isNotEmpty()) {
            fail("unavailable occurrence source cannot expose items")
        }
        if (jobsSource.state != "ready" && items.any { it.job != null }) {
            fail("non-ready jobs source cannot expose job observations")
        }
        if (jobsSource.state == "not_required" && items.any { it.jobId != null }) {
            fail("not_required jobs source contradicts referenced jobs")
        }

        return ControlCenterScheduleHistory(
            schema = schema,
            generatedAt = generatedAt,
            occurrenceSource = occurrenceSource,
            jobsSource = jobsSource,
            items = items,
            productionActivation = productionActivation,
        )
    }

    private fun parseSource(
        source: JSONObject,
        label: String,
        allowedStates: Set<String>,
    ): ControlCenterHistorySource {
        val state = source.requireString("state")
        if (state !in allowedStates) fail("unsupported $label source state $state")
        val reason = source.optionalNullableString("reason")
        if (state == "unavailable" && reason == null) fail("$label unavailable source lacks reason")
        if (state != "unavailable" && reason != null) fail("$label ready source must not carry a reason")
        return ControlCenterHistorySource(state = state, reason = reason)
    }

    private fun parseOccurrence(item: JSONObject, index: Int): ControlCenterScheduleOccurrence {
        val occurrenceId = item.requireString("occurrence_id")
        val scheduleId = item.requireString("schedule_id")
        val tool = item.optionalNullableString("tool")
        val dueAt = item.requireFiniteNumber("due_at")
        val status = item.requireString("occurrence_status")
        if (status !in OCCURRENCE_STATES) fail("unsupported occurrence status $status")
        val inFlight = item.requireNullableBoolean("in_flight")
        val terminalOutcome = item.optionalNullableString("terminal_outcome")
        if (terminalOutcome != null && terminalOutcome !in TERMINAL_OUTCOMES) {
            fail("unsupported terminal outcome $terminalOutcome")
        }
        validateOccurrenceState(status, inFlight, terminalOutcome)

        val createdAt = item.requireFiniteNumber("created_at")
        val resolvedAt = item.optionalFiniteNumber("resolved_at")
        val jobId = item.optionalNullableString("job_id")
        val job = when {
            !item.has("job") || item.isNull("job") -> null
            else -> parseJob(item.optJSONObject("job") ?: fail("items[$index].job must be object or null"))
        }
        if (job != null && jobId == null) fail("job observation lacks job_id")

        return ControlCenterScheduleOccurrence(
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

    private fun validateOccurrenceState(status: String, inFlight: Boolean?, outcome: String?) {
        when (status) {
            "reserved", "reserved_noslot" -> {
                if (inFlight != true || outcome != null) fail("pending occurrence state contradiction")
            }
            "executed" -> {
                if (inFlight != false || outcome != "executed") fail("executed occurrence state contradiction")
            }
            "released" -> {
                if (inFlight != false || outcome != "not_run") fail("released occurrence state contradiction")
            }
            "abandoned" -> {
                if (inFlight != false || outcome != "abandoned") fail("abandoned occurrence state contradiction")
            }
            "unknown" -> {
                if (inFlight != false || outcome != "unknown") fail("unknown occurrence state contradiction")
            }
            "unknown_schema_value" -> {
                if (inFlight != null || outcome != "unknown") fail("future occurrence state must remain unknown")
            }
        }
    }

    private fun parseJob(job: JSONObject): ControlCenterObservedJob {
        val status = job.requireString("status")
        if (status !in JOB_STATES) fail("unsupported job status $status")
        val kind = job.requireString("kind")
        val completed = job.requireNonNegativeLong("progress_completed")
        val total = job.requireNonNegativeLong("progress_total")
        if (total > 0 && completed > total) fail("job progress exceeds total")
        return ControlCenterObservedJob(
            status = status,
            kind = kind,
            progressCompleted = completed,
            progressTotal = total,
            createdAt = job.requireFiniteNumber("created_at"),
            updatedAt = job.requireFiniteNumber("updated_at"),
        )
    }

    private fun JSONObject.requireObject(key: String): JSONObject =
        optJSONObject(key) ?: fail("$key must be an object")

    private fun JSONObject.requireString(key: String): String {
        if (!has(key) || isNull(key) || get(key) !is String) fail("$key must be a string")
        return getString(key).trim().takeIf { it.isNotEmpty() } ?: fail("blank $key")
    }

    private fun JSONObject.optionalNullableString(key: String): String? {
        if (!has(key) || isNull(key)) return null
        if (get(key) !is String) fail("$key must be string or null")
        return getString(key).trim().takeIf { it.isNotEmpty() }
    }

    private fun JSONObject.requireBoolean(key: String): Boolean {
        if (!has(key) || isNull(key) || get(key) !is Boolean) fail("$key must be boolean")
        return getBoolean(key)
    }

    private fun JSONObject.requireNullableBoolean(key: String): Boolean? {
        if (!has(key)) fail("missing $key")
        if (isNull(key)) return null
        if (get(key) !is Boolean) fail("$key must be boolean or null")
        return getBoolean(key)
    }

    private fun JSONObject.requireNonNegativeLong(key: String): Long {
        if (!has(key) || isNull(key)) fail("$key must be an integer")
        val raw = get(key)
        val value = when (raw) {
            is Int -> raw.toLong()
            is Long -> raw
            else -> fail("$key must be an integer")
        }
        if (value < 0) fail("$key must be non-negative")
        return value
    }

    private fun JSONObject.requireFiniteNumber(key: String): Double {
        if (!has(key) || isNull(key)) fail("$key must be numeric")
        val raw = get(key)
        if (raw !is Number || raw is Boolean) fail("$key must be numeric")
        val value = raw.toDouble()
        if (!value.isFinite()) fail("$key must be finite")
        return value
    }

    private fun JSONObject.optionalFiniteNumber(key: String): Double? {
        if (!has(key) || isNull(key)) return null
        return requireFiniteNumber(key)
    }

    private fun fail(message: String): Nothing =
        throw ModelRigException("invalid control center schedule history: $message")
}

data class ControlCenterScheduleHistory(
    val schema: String,
    val generatedAt: Double,
    val occurrenceSource: ControlCenterHistorySource,
    val jobsSource: ControlCenterHistorySource,
    val items: List<ControlCenterScheduleOccurrence>,
    val productionActivation: Boolean,
)

data class ControlCenterHistorySource(
    val state: String,
    val reason: String?,
)

data class ControlCenterScheduleOccurrence(
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
