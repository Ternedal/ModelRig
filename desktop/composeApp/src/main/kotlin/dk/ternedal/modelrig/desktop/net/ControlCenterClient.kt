package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

class ControlCenterException(message: String) : RuntimeException(message)

@Serializable
private data class ControlCenterWireStatus(
    val schema: String,
    @SerialName("generated_at") val generatedAt: Double,
    @SerialName("freshness_s") val freshnessSeconds: Double,
    val overall: String,
    val green: Boolean,
    val components: Map<String, ControlCenterWireComponent>,
    val routing: ControlCenterWireRouting,
    val summary: ControlCenterWireSummary,
)

@Serializable
private data class ControlCenterWireComponent(
    val name: String,
    val required: Boolean,
    val state: String,
    val green: Boolean,
    @SerialName("observed_at") val observedAt: Double? = null,
    @SerialName("age_s") val ageSeconds: Double? = null,
    val detail: String? = null,
    val reason: String? = null,
)

@Serializable
private data class ControlCenterWireRouting(
    val state: String,
    val green: Boolean,
    @SerialName("configured_surface") val configuredSurface: String? = null,
    @SerialName("active_surface") val activeSurface: String? = null,
    @SerialName("fallback_reason") val fallbackReason: String? = null,
    @SerialName("observed_at") val observedAt: Double? = null,
    @SerialName("age_s") val ageSeconds: Double? = null,
    val reason: String? = null,
)

@Serializable
private data class ControlCenterWireSummary(
    @SerialName("required_failures") val requiredFailures: List<String>,
)

/**
 * Read-only desktop client for the server-authoritative Control Center status.
 *
 * The desktop never derives health from subsystem values. It accepts only the
 * versioned backend contract and rejects missing freshness evidence, unknown
 * states, and state/green contradictions before a UI can render them.
 */
class ControlCenterClient(baseUrl: String, private val bearer: String) {
    companion object {
        const val SCHEMA = "kaliv-control-center-status/v1"
        private val OVERALL_STATES = setOf("healthy", "attention", "unavailable", "unknown")
        private val COMPONENT_STATES = setOf("healthy", "unavailable", "unknown", "stale", "disabled")
        private val ROUTING_STATES = setOf("healthy", "fallback", "unknown", "stale", "disabled")
        private val REQUIRED_COMPONENTS = setOf("backend", "worker", "models", "agent3")
        private val REQUIRED_HEALTH_COMPONENTS = setOf("backend", "worker", "models")
    }

    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun status(): ControlCenterStatus {
        val request = HttpRequest.newBuilder(
            URI.create(base + "/api/v1/control-center/status"),
        )
            .header("Accept", "application/json")
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(10))
            .GET()
            .build()
        val response = try {
            http.send(request, HttpResponse.BodyHandlers.ofString())
        } catch (exc: Exception) {
            throw ControlCenterException(
                "Control Center status failed: ${exc::class.simpleName}",
            )
        }
        if (response.statusCode() !in 200..299) {
            throw ControlCenterException(
                "Control Center status failed (${response.statusCode()}): " +
                    response.body().take(500),
            )
        }
        return parse(response.body())
    }

    internal fun parse(body: String): ControlCenterStatus {
        val wire = try {
            json.decodeFromString<ControlCenterWireStatus>(body)
        } catch (exc: Exception) {
            throw ControlCenterException(
                "Invalid Control Center status JSON: ${exc::class.simpleName}",
            )
        }
        if (wire.schema != SCHEMA) fail("unsupported schema ${wire.schema}")
        finite("generated_at", wire.generatedAt)
        finite("freshness_s", wire.freshnessSeconds)
        if (wire.freshnessSeconds <= 0.0) fail("freshness_s must be positive")
        if (wire.overall !in OVERALL_STATES) fail("unsupported overall ${wire.overall}")
        if (wire.green != (wire.overall == "healthy")) fail("overall/green contradiction")

        val missing = REQUIRED_COMPONENTS - wire.components.keys
        if (missing.isNotEmpty()) fail("missing components: ${missing.sorted().joinToString()}")
        val components = wire.components.mapValues { (key, value) ->
            validateComponent(key, value)
        }
        val routing = validateRouting(wire.routing)

        if (wire.summary.requiredFailures.any { it !in REQUIRED_HEALTH_COMPONENTS }) {
            fail("summary contains unknown required failure")
        }
        val actualRequiredFailures = REQUIRED_HEALTH_COMPONENTS
            .filter { components.getValue(it).state != "healthy" }
            .sorted()
        if (wire.summary.requiredFailures.sorted() != actualRequiredFailures) {
            fail("summary.required_failures contradiction")
        }
        if (wire.overall == "healthy" && actualRequiredFailures.isNotEmpty()) {
            fail("healthy overall contains required failures")
        }
        if (wire.overall == "healthy" && routing.state !in setOf("healthy", "disabled")) {
            fail("healthy overall contains non-healthy routing")
        }

        return ControlCenterStatus(
            schema = wire.schema,
            generatedAt = wire.generatedAt,
            freshnessSeconds = wire.freshnessSeconds,
            overall = wire.overall,
            green = wire.green,
            components = components,
            routing = routing,
            requiredFailures = wire.summary.requiredFailures,
        )
    }

    private fun validateComponent(
        key: String,
        wire: ControlCenterWireComponent,
    ): ControlCenterComponent {
        if (wire.name != key) fail("component name/key mismatch for $key")
        if (wire.state !in COMPONENT_STATES) fail("unsupported component state ${wire.state}")
        if (wire.green != (wire.state == "healthy")) {
            fail("component $key state/green contradiction")
        }
        wire.observedAt?.let { finite("component $key observed_at", it) }
        wire.ageSeconds?.let {
            finite("component $key age_s", it)
            if (it < 0.0) fail("component $key has negative age")
        }
        if (wire.state == "healthy" && (wire.observedAt == null || wire.ageSeconds == null)) {
            fail("healthy component $key lacks freshness evidence")
        }
        return ControlCenterComponent(
            name = wire.name,
            required = wire.required,
            state = wire.state,
            green = wire.green,
            observedAt = wire.observedAt,
            ageSeconds = wire.ageSeconds,
            detail = wire.detail?.trim()?.takeIf { it.isNotEmpty() },
            reason = wire.reason?.trim()?.takeIf { it.isNotEmpty() },
        )
    }

    private fun validateRouting(wire: ControlCenterWireRouting): ControlCenterRouting {
        if (wire.state !in ROUTING_STATES) fail("unsupported routing state ${wire.state}")
        if (wire.green != (wire.state == "healthy")) fail("routing state/green contradiction")
        val fallbackReason = wire.fallbackReason?.trim()?.takeIf { it.isNotEmpty() }
        if (wire.state == "fallback" && fallbackReason == null) {
            fail("fallback routing lacks server reason")
        }
        wire.observedAt?.let { finite("routing observed_at", it) }
        wire.ageSeconds?.let {
            finite("routing age_s", it)
            if (it < 0.0) fail("routing has negative age")
        }
        if (wire.state == "healthy" && (wire.observedAt == null || wire.ageSeconds == null)) {
            fail("healthy routing lacks freshness evidence")
        }
        return ControlCenterRouting(
            state = wire.state,
            green = wire.green,
            configuredSurface = wire.configuredSurface,
            activeSurface = wire.activeSurface,
            fallbackReason = fallbackReason,
            observedAt = wire.observedAt,
            ageSeconds = wire.ageSeconds,
            reason = wire.reason?.trim()?.takeIf { it.isNotEmpty() },
        )
    }

    private fun finite(name: String, value: Double) {
        if (!value.isFinite()) fail("$name must be finite")
    }

    private fun fail(message: String): Nothing =
        throw ControlCenterException("Invalid Control Center status: $message")
}

data class ControlCenterStatus(
    val schema: String,
    val generatedAt: Double,
    val freshnessSeconds: Double,
    val overall: String,
    val green: Boolean,
    val components: Map<String, ControlCenterComponent>,
    val routing: ControlCenterRouting,
    val requiredFailures: List<String>,
)

data class ControlCenterComponent(
    val name: String,
    val required: Boolean,
    val state: String,
    val green: Boolean,
    val observedAt: Double?,
    val ageSeconds: Double?,
    val detail: String?,
    val reason: String?,
)

data class ControlCenterRouting(
    val state: String,
    val green: Boolean,
    val configuredSurface: String?,
    val activeSurface: String?,
    val fallbackReason: String?,
    val observedAt: Double?,
    val ageSeconds: Double?,
    val reason: String?,
)
