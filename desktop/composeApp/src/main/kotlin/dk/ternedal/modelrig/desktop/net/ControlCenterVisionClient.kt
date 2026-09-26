package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.charset.StandardCharsets
import java.time.Duration

@Serializable
private data class VisionWireSnapshot(
    val schema: String,
    val available: Boolean,
    val reason: String? = null,
    val sensors: List<VisionWireSensor>,
    @SerialName("production_activation") val productionActivation: Boolean,
)

@Serializable
private data class VisionWireSensor(
    @SerialName("source_id") val sourceId: String,
    @SerialName("display_name") val displayName: String? = null,
    val location: String? = null,
    val role: String? = null,
    @SerialName("source_type") val sourceType: String,
    val device: String? = null,
    val capabilities: List<String> = emptyList(),
    val presence: String,
    @SerialName("desired_enabled") val desiredEnabled: Boolean,
    @SerialName("effective_capture_active") val effectiveCaptureActive: Boolean? = null,
    val convergence: String,
    @SerialName("first_seen_utc") val firstSeenUtc: String? = null,
    @SerialName("last_seen_utc") val lastSeenUtc: String? = null,
    @SerialName("runtime_last_seen_utc") val runtimeLastSeenUtc: String? = null,
    @SerialName("observation_count") val observationCount: Int,
)

@Serializable
private data class VisionEnabledWireReceipt(
    val schema: String,
    @SerialName("source_id") val sourceId: String,
    val enabled: Boolean,
)

class ControlCenterVisionClient(baseUrl: String, private val bearer: String) {
    companion object {
        const val SCHEMA = "kaliv-control-center-vision/v1"
        const val ENABLED_SCHEMA = "kaliv-control-center-vision-enabled/v1"
        private val PRESENCE = setOf("online", "stale", "offline", "unknown")
        private val CONVERGENCE = setOf("converged", "pending", "unknown")
        private val SOURCE_TYPE = Regex("^[a-z][a-z0-9_-]{0,31}$")
    }

    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun snapshot(): ControlCenterVisionSnapshot =
        parseSnapshot(get("/api/v1/control-center/vision", "VisionRig status"))

    fun setEnabled(sourceId: String, enabled: Boolean): VisionSensorEnabledReceipt {
        require(sourceId.isNotBlank() && sourceId.length <= 128) { "invalid source id" }
        val payload = if (enabled) "{\"enabled\":true}" else "{\"enabled\":false}"
        val path = "/api/v1/control-center/vision/sensors/${seg(sourceId)}/enabled"
        return parseEnabled(patch(path, payload, "VisionRig sensor control"), sourceId, enabled)
    }

    internal fun parseSnapshot(body: String): ControlCenterVisionSnapshot {
        val wire = decode<VisionWireSnapshot>(body, "VisionRig status")
        if (wire.schema != SCHEMA) fail("unsupported schema ${wire.schema}")
        if (wire.productionActivation) fail("production_activation must be false")
        if (!wire.available && wire.sensors.isNotEmpty()) fail("unavailable snapshot contains sensors")
        if (wire.available && !wire.reason.isNullOrBlank()) fail("available snapshot contains failure reason")

        val sensors = wire.sensors.mapIndexed { index, sensor ->
            val path = "sensors[$index]"
            val sourceId = sensor.sourceId.trim()
            if (sourceId.isEmpty() || sourceId.length > 128) fail("$path.source_id is invalid")
            if (!SOURCE_TYPE.matches(sensor.sourceType)) fail("$path.source_type is invalid")
            if (sensor.presence !in PRESENCE) fail("$path.presence is invalid")
            if (sensor.convergence !in CONVERGENCE) fail("$path.convergence is invalid")
            if (sensor.observationCount < 0) fail("$path.observation_count is negative")
            if (sensor.convergence == "converged" &&
                sensor.effectiveCaptureActive != sensor.desiredEnabled
            ) {
                fail("$path convergence contradicts effective state")
            }
            if (sensor.convergence == "pending" &&
                (sensor.effectiveCaptureActive == null ||
                    sensor.effectiveCaptureActive == sensor.desiredEnabled)
            ) {
                fail("$path pending state is contradictory")
            }
            ControlCenterVisionSensor(
                sourceId = sourceId,
                displayName = sensor.displayName?.trim()?.takeIf { it.isNotEmpty() },
                location = sensor.location?.trim()?.takeIf { it.isNotEmpty() },
                role = sensor.role?.trim()?.takeIf { it.isNotEmpty() },
                sourceType = sensor.sourceType,
                device = sensor.device?.trim()?.takeIf { it.isNotEmpty() },
                capabilities = sensor.capabilities.map { it.trim().lowercase() }
                    .filter { it.isNotEmpty() }.distinct().sorted(),
                presence = sensor.presence,
                desiredEnabled = sensor.desiredEnabled,
                effectiveCaptureActive = sensor.effectiveCaptureActive,
                convergence = sensor.convergence,
                firstSeenUtc = sensor.firstSeenUtc,
                lastSeenUtc = sensor.lastSeenUtc,
                runtimeLastSeenUtc = sensor.runtimeLastSeenUtc,
                observationCount = sensor.observationCount,
            )
        }
        if (sensors.map { it.sourceId }.distinct().size != sensors.size) {
            fail("duplicate source ids")
        }
        return ControlCenterVisionSnapshot(
            available = wire.available,
            reason = wire.reason?.trim()?.takeIf { it.isNotEmpty() },
            sensors = sensors.sortedBy { it.sourceId },
        )
    }

    internal fun parseEnabled(
        body: String,
        expectedSourceId: String,
        expectedEnabled: Boolean,
    ): VisionSensorEnabledReceipt {
        val wire = decode<VisionEnabledWireReceipt>(body, "VisionRig sensor control")
        if (wire.schema != ENABLED_SCHEMA) fail("unsupported enabled receipt schema")
        if (wire.sourceId != expectedSourceId) fail("enabled receipt source mismatch")
        if (wire.enabled != expectedEnabled) fail("enabled receipt state mismatch")
        return VisionSensorEnabledReceipt(wire.sourceId, wire.enabled)
    }

    private inline fun <reified T> decode(body: String, label: String): T = try {
        json.decodeFromString<T>(body)
    } catch (exc: Exception) {
        throw ControlCenterException("Invalid Control Center $label JSON: ${exc::class.simpleName}")
    }

    private fun get(path: String, label: String): String {
        val request = HttpRequest.newBuilder(URI.create(base + path))
            .header("Accept", "application/json")
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(10))
            .GET()
            .build()
        return execute(request, label)
    }

    private fun patch(path: String, body: String, label: String): String {
        val request = HttpRequest.newBuilder(URI.create(base + path))
            .header("Accept", "application/json")
            .header("Content-Type", "application/json")
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(10))
            .method("PATCH", HttpRequest.BodyPublishers.ofString(body))
            .build()
        return execute(request, label)
    }

    private fun execute(request: HttpRequest, label: String): String {
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

    private fun seg(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8.toString()).replace("+", "%20")

    private fun fail(message: String): Nothing =
        throw ControlCenterException("Invalid Control Center VisionRig payload: $message")
}

data class ControlCenterVisionSnapshot(
    val available: Boolean,
    val reason: String?,
    val sensors: List<ControlCenterVisionSensor>,
)

data class ControlCenterVisionSensor(
    val sourceId: String,
    val displayName: String?,
    val location: String?,
    val role: String?,
    val sourceType: String,
    val device: String?,
    val capabilities: List<String>,
    val presence: String,
    val desiredEnabled: Boolean,
    val effectiveCaptureActive: Boolean?,
    val convergence: String,
    val firstSeenUtc: String?,
    val lastSeenUtc: String?,
    val runtimeLastSeenUtc: String?,
    val observationCount: Int,
) {
    val title: String get() = displayName ?: sourceId
}

data class VisionSensorEnabledReceipt(
    val sourceId: String,
    val enabled: Boolean,
)
