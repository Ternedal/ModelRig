package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

/**
 * Read-only desktop projection of scheduler runtime + standing grants.
 *
 * The client deliberately exposes only the existing authenticated GET routes.
 * It contains no preview/create/pause/renew/approval method and never promotes
 * standing-grant metadata into occurrence/job execution truth.
 */
class ControlCenterSchedulesClient(baseUrl: String, private val bearer: String) {
    companion object {
        private val SCHEDULE_ID = Regex("^[0-9a-f]{12}$")
        private val INTEGER_TEXT = Regex("^-?(0|[1-9][0-9]*)$")
    }

    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true }
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun snapshot(): ControlCenterScheduleSnapshot = ControlCenterScheduleSnapshot(
        runtime = parseRuntime(get("/api/v1/schedules/status", "scheduler status")),
        schedules = parseSchedules(get("/api/v1/schedules", "scheduler list")),
    )

    internal fun parseRuntime(body: String): ControlCenterScheduleRuntime {
        val root = parseObject(body, "scheduler status")
        val configured = root.strictBoolean("configured")
        val running = root.strictBoolean("running")
        val resourcesOpen = root.strictBoolean("resources_open")
        val lastError = root.optionalNullableString("last_error")
        val maxConcurrency = root.strictNonNegativeInt("max_concurrency")
        val queueCapacity = root.strictNonNegativeInt("queue_capacity")
        val activeExecutions = root.strictNonNegativeInt("active_executions")
        val acceptedTicks = root.strictNonNegativeInt("accepted_ticks")
        val overlapRejections = root.strictNonNegativeInt("overlap_rejections")

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

    internal fun parseSchedules(body: String): List<ControlCenterScheduleGrant> {
        val root = parseObject(body, "scheduler list")
        val array = root["schedules"] as? JsonArray ?: fail("schedules must be an array")
        val parsed = array.mapIndexed { index, element ->
            val item = element as? JsonObject ?: fail("schedules[$index] must be an object")
            parseGrant(item, index)
        }
        val ids = parsed.map { it.id }
        if (ids.size != ids.toSet().size) fail("duplicate schedule ids")
        return parsed.sortedWith(compareBy<ControlCenterScheduleGrant> { it.dueAt }.thenBy { it.id })
    }

    private fun parseGrant(item: JsonObject, index: Int): ControlCenterScheduleGrant {
        val prefix = "schedules[$index]"
        val id = item.strictString("schedule_id", prefix)
        if (!SCHEDULE_ID.matches(id)) fail("invalid schedule id")
        val tool = item.strictString("tool", prefix)
        val cadence = item.strictString("cadence", prefix)
        val timezone = item.strictString("timezone", prefix)
        val misfirePolicy = item.strictString("misfire_policy", prefix)
        val dueAtLocal = item.strictString("due_at_local", prefix)
        val risk = item.strictString("risk", prefix)
        val sensitivity = item.strictString("sensitivity", prefix)
        val expiresAt = item.strictFiniteNumber("expires_at", prefix)
        val expired = item.strictBoolean("expired", prefix)
        val maxRuns = item.strictNonNegativeInt("max_runs", prefix)
        val runsUsed = item.strictNonNegativeInt("runs_used", prefix)
        val budgetExhausted = item.strictBoolean("budget_exhausted", prefix)
        val dueAt = item.strictFiniteNumber("due_at", prefix)
        val missed = item.strictNonNegativeInt("missed", prefix)
        val enabled = item.strictBoolean("enabled", prefix)
        val structurallyEligible = item.strictBoolean("structurally_eligible", prefix)
        val runtimeGateChecked = item.strictBoolean("runtime_gate_checked", prefix)
        val blockedReason = item.optionalNullableString("blocked_reason", prefix)

        if (runtimeGateChecked) fail("admin list must not claim the runtime gate was checked")
        if (maxRuns > 0 && runsUsed > maxRuns) fail("runs_used exceeds max_runs")
        val expectedBudgetExhausted = maxRuns > 0 && runsUsed >= maxRuns
        if (budgetExhausted != expectedBudgetExhausted) {
            fail("budget exhaustion contradicts run counters")
        }
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

    private fun get(path: String, label: String): String {
        val request = HttpRequest.newBuilder(URI.create(base + path))
            .header("Accept", "application/json")
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(10))
            .GET()
            .build()
        val response = try {
            http.send(request, HttpResponse.BodyHandlers.ofString())
        } catch (exc: Exception) {
            throw ControlCenterException("Control Center $label failed: ${exc::class.simpleName}")
        }
        if (response.statusCode() !in 200..299) {
            throw ControlCenterException(
                "Control Center $label failed (${response.statusCode()}): ${response.body().take(500)}",
            )
        }
        if (response.body().isBlank()) {
            throw ControlCenterException("Control Center $label returned an empty body")
        }
        return response.body()
    }

    private fun parseObject(body: String, label: String): JsonObject = try {
        json.parseToJsonElement(body).jsonObject
    } catch (exc: Exception) {
        fail("$label invalid JSON: ${exc::class.simpleName}")
    }

    private fun JsonObject.strictString(key: String, prefix: String? = null): String {
        val field = prefix?.let { "$it.$key" } ?: key
        val primitive = this[key] as? JsonPrimitive ?: fail("$field must be a string")
        if (!primitive.isString) fail("$field must be a string")
        return primitive.content.trim().takeIf { it.isNotEmpty() } ?: fail("blank $field")
    }

    private fun JsonObject.strictBoolean(key: String, prefix: String? = null): Boolean {
        val field = prefix?.let { "$it.$key" } ?: key
        val primitive = this[key] as? JsonPrimitive ?: fail("$field must be boolean")
        if (primitive.isString) fail("$field must be boolean")
        return primitive.booleanOrNull ?: fail("$field must be boolean")
    }

    private fun JsonObject.strictNonNegativeInt(key: String, prefix: String? = null): Int {
        val field = prefix?.let { "$it.$key" } ?: key
        val primitive = this[key] as? JsonPrimitive ?: fail("$field must be an integer")
        if (primitive.isString || !INTEGER_TEXT.matches(primitive.content)) {
            fail("$field must be an integer")
        }
        val value = primitive.content.toIntOrNull() ?: fail("$field must be an integer")
        if (value < 0) fail("$field must be non-negative")
        return value
    }

    private fun JsonObject.strictFiniteNumber(key: String, prefix: String? = null): Double {
        val field = prefix?.let { "$it.$key" } ?: key
        val primitive = this[key] as? JsonPrimitive ?: fail("$field must be numeric")
        if (primitive.isString) fail("$field must be numeric")
        val value = primitive.doubleOrNull ?: fail("$field must be numeric")
        if (!value.isFinite()) fail("$field must be finite")
        return value
    }

    private fun JsonObject.optionalNullableString(key: String, prefix: String? = null): String? {
        val element = this[key] ?: return null
        if (element is JsonNull) return null
        val field = prefix?.let { "$it.$key" } ?: key
        val primitive = element as? JsonPrimitive ?: fail("$field must be string or null")
        if (!primitive.isString) fail("$field must be string or null")
        return primitive.content.trim().takeIf { it.isNotEmpty() }
    }

    private fun fail(message: String): Nothing =
        throw ControlCenterException("Invalid Control Center schedules: $message")
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
