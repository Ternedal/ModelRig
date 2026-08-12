package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

@Serializable
private data class ScheduleHistorySourceWire(
    val state: String,
    val reason: String?,
)

@Serializable
private data class ScheduleHistorySourcesWire(
    @SerialName("occurrence_ledger") val occurrenceLedger: ScheduleHistorySourceWire,
    val jobs: ScheduleHistorySourceWire,
)

@Serializable
private data class ScheduleHistoryJobWire(
    val status: String,
    val kind: String,
    @SerialName("progress_completed") val progressCompleted: JsonElement,
    @SerialName("progress_total") val progressTotal: JsonElement,
    @SerialName("created_at") val createdAt: JsonElement,
    @SerialName("updated_at") val updatedAt: JsonElement,
)

@Serializable
private data class ScheduleHistoryOccurrenceWire(
    @SerialName("occurrence_id") val occurrenceId: String,
    @SerialName("schedule_id") val scheduleId: String,
    val tool: String?,
    @SerialName("due_at") val dueAt: JsonElement,
    @SerialName("occurrence_status") val occurrenceStatus: String,
    @SerialName("in_flight") val inFlight: JsonElement?,
    @SerialName("terminal_outcome") val terminalOutcome: String?,
    @SerialName("created_at") val createdAt: JsonElement,
    @SerialName("resolved_at") val resolvedAt: JsonElement?,
    @SerialName("job_id") val jobId: String?,
    val job: ScheduleHistoryJobWire?,
)

@Serializable
private data class ScheduleHistoryWire(
    val schema: String,
    @SerialName("generated_at") val generatedAt: JsonElement,
    val sources: ScheduleHistorySourcesWire,
    val items: List<ScheduleHistoryOccurrenceWire>,
    @SerialName("production_activation") val productionActivation: JsonElement,
)

/**
 * Read-only desktop client for the durable schedule occurrence/job projection.
 *
 * Occurrence state is the execution authority. JobStore is parsed only as an
 * independent observation and can never rewrite the occurrence outcome.
 */
class ControlCenterScheduleHistoryClient(baseUrl: String, private val bearer: String) {
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
        private val INTEGER_TEXT = Regex("^-?(0|[1-9][0-9]*)$")
    }

    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = false; explicitNulls = true }
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun history(): ControlCenterScheduleHistory {
        val request = HttpRequest.newBuilder(URI.create(base + "/api/v1/control-center/schedules"))
            .header("Accept", "application/json")
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(10))
            .GET()
            .build()
        val response = try {
            http.send(request, HttpResponse.BodyHandlers.ofString())
        } catch (exc: Exception) {
            throw ControlCenterException(
                "Control Center schedule history failed: ${exc::class.simpleName}",
            )
        }
        if (response.statusCode() !in 200..299) {
            throw ControlCenterException(
                "Control Center schedule history failed (${response.statusCode()}): " +
                    response.body().take(500),
            )
        }
        return parse(response.body())
    }

    internal fun parse(body: String): ControlCenterScheduleHistory {
        val wire = try {
            json.decodeFromString<ScheduleHistoryWire>(body)
        } catch (exc: Exception) {
            fail("invalid payload: ${exc::class.simpleName}")
        }
        if (wire.schema != SCHEMA) fail("unsupported schema ${wire.schema}")
        val generatedAt = requireFiniteNumber("generated_at", wire.generatedAt)
        val productionActivation = requireBoolean("production_activation", wire.productionActivation)
        if (productionActivation) fail("production_activation must remain false")

        val occurrenceSource = parseSource(
            "occurrence_ledger",
            wire.sources.occurrenceLedger,
            OCCURRENCE_SOURCE_STATES,
        )
        val jobsSource = parseSource("jobs", wire.sources.jobs, JOB_SOURCE_STATES)
        val items = wire.items.mapIndexed { index, item -> parseOccurrence(index, item) }
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
            schema = wire.schema,
            generatedAt = generatedAt,
            occurrenceSource = occurrenceSource,
            jobsSource = jobsSource,
            items = items,
            productionActivation = productionActivation,
        )
    }

    private fun parseSource(
        label: String,
        wire: ScheduleHistorySourceWire,
        allowedStates: Set<String>,
    ): ControlCenterHistorySource {
        if (wire.state !in allowedStates) fail("unsupported $label source state ${wire.state}")
        val reason = wire.reason?.trim()?.takeIf { it.isNotEmpty() }
        if (wire.state == "unavailable" && reason == null) fail("$label unavailable source lacks reason")
        if (wire.state != "unavailable" && reason != null) fail("$label ready source must not carry a reason")
        return ControlCenterHistorySource(wire.state, reason)
    }

    private fun parseOccurrence(
        index: Int,
        wire: ScheduleHistoryOccurrenceWire,
    ): ControlCenterScheduleOccurrence {
        val occurrenceId = requireText("items[$index].occurrence_id", wire.occurrenceId)
        val scheduleId = requireText("items[$index].schedule_id", wire.scheduleId)
        val tool = wire.tool?.trim()?.takeIf { it.isNotEmpty() }
        val dueAt = requireFiniteNumber("items[$index].due_at", wire.dueAt)
        val createdAt = requireFiniteNumber("items[$index].created_at", wire.createdAt)
        val resolvedAt = wire.resolvedAt?.let {
            requireFiniteNumber("items[$index].resolved_at", it)
        }
        val inFlight = wire.inFlight?.let {
            requireBoolean("items[$index].in_flight", it)
        }
        if (wire.occurrenceStatus !in OCCURRENCE_STATES) {
            fail("unsupported occurrence status ${wire.occurrenceStatus}")
        }
        val outcome = wire.terminalOutcome?.also {
            if (it !in TERMINAL_OUTCOMES) fail("unsupported terminal outcome $it")
        }
        validateOccurrenceState(wire.occurrenceStatus, inFlight, outcome)

        val jobId = wire.jobId?.trim()?.takeIf { it.isNotEmpty() }
        val job = wire.job?.let { parseJob(index, it) }
        if (job != null && jobId == null) fail("job observation lacks job_id")

        return ControlCenterScheduleOccurrence(
            occurrenceId = occurrenceId,
            scheduleId = scheduleId,
            tool = tool,
            dueAt = dueAt,
            occurrenceStatus = wire.occurrenceStatus,
            inFlight = inFlight,
            terminalOutcome = outcome,
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

    private fun parseJob(index: Int, wire: ScheduleHistoryJobWire): ControlCenterObservedJob {
        if (wire.status !in JOB_STATES) fail("unsupported job status ${wire.status}")
        val kind = requireText("items[$index].job.kind", wire.kind)
        val progressCompleted = requireInteger(
            "items[$index].job.progress_completed",
            wire.progressCompleted,
        )
        val progressTotal = requireInteger(
            "items[$index].job.progress_total",
            wire.progressTotal,
        )
        if (progressCompleted < 0 || progressTotal < 0) fail("job progress must be non-negative")
        if (progressTotal > 0 && progressCompleted > progressTotal) {
            fail("job progress exceeds total")
        }
        val createdAt = requireFiniteNumber("items[$index].job.created_at", wire.createdAt)
        val updatedAt = requireFiniteNumber("items[$index].job.updated_at", wire.updatedAt)
        return ControlCenterObservedJob(
            status = wire.status,
            kind = kind,
            progressCompleted = progressCompleted,
            progressTotal = progressTotal,
            createdAt = createdAt,
            updatedAt = updatedAt,
        )
    }

    private fun requireBoolean(field: String, value: JsonElement): Boolean {
        val primitive = value as? JsonPrimitive ?: fail("$field must be boolean")
        if (primitive.isString) fail("$field must be boolean")
        return primitive.booleanOrNull ?: fail("$field must be boolean")
    }

    private fun requireInteger(field: String, value: JsonElement): Long {
        val primitive = value as? JsonPrimitive ?: fail("$field must be an integer")
        if (primitive.isString || !INTEGER_TEXT.matches(primitive.content)) {
            fail("$field must be an integer")
        }
        return primitive.content.toLongOrNull() ?: fail("$field must be an integer")
    }

    private fun requireFiniteNumber(field: String, value: JsonElement): Double {
        val primitive = value as? JsonPrimitive ?: fail("$field must be numeric")
        if (primitive.isString) fail("$field must be numeric")
        val parsed = primitive.doubleOrNull ?: fail("$field must be numeric")
        if (!parsed.isFinite()) fail("$field must be finite")
        return parsed
    }

    private fun requireText(field: String, value: String): String =
        value.trim().takeIf { it.isNotEmpty() } ?: fail("blank $field")

    private fun fail(message: String): Nothing =
        throw ControlCenterException("Invalid Control Center schedule history: $message")
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
