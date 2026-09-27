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
private data class ControlCenterVisionStatusEnvelope(
    val vision: VisionWireSnapshot,
)

@Serializable
private data class VisionWireSnapshot(
    val schema: String,
    val available: Boolean,
    val reason: String? = null,
    @SerialName("sensor_state_revision") val sensorStateRevision: Long? = null,
    @SerialName("control_available") val controlAvailable: Boolean = false,
    val consistency: String = "unknown",
    val total: Int = 0,
    @SerialName("sensors_returned") val sensorsReturned: Int = 0,
    @SerialName("sensors_truncated") val sensorsTruncated: Boolean = false,
    @SerialName("attention_total") val attentionTotal: Int = 0,
    @SerialName("attention_truncated") val attentionTruncated: Boolean = false,
    val sensors: List<VisionWireSensor>,
    @SerialName("production_activation") val productionActivation: Boolean,
)

@Serializable
private data class VisionEnabledWireReceipt(
    val schema: String,
    @SerialName("source_id") val sourceId: String,
    val enabled: Boolean,
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
    val lifecycle: String = "active",
    @SerialName("desired_revision") val desiredRevision: Long = 0,
    @SerialName("applied_revision") val appliedRevision: Long? = null,
    @SerialName("pending_seconds") val pendingSeconds: Double? = null,
    @SerialName("transport_status") val transportStatus: String = "unknown",
    @SerialName("payload_utilization") val payloadUtilization: Double? = null,
    @SerialName("capability_refresh_status") val capabilityRefreshStatus: String = "unknown",
    @SerialName("negotiated_max_payload_bytes") val negotiatedMaxPayloadBytes: Long? = null,
    @SerialName("negotiated_packet_compression") val negotiatedPacketCompression: String? = null,
    @SerialName("negotiated_packet_target_utilization") val negotiatedPacketTargetUtilization: Double? = null,
    @SerialName("first_seen_utc") val firstSeenUtc: String? = null,
    @SerialName("last_seen_utc") val lastSeenUtc: String? = null,
    @SerialName("runtime_last_seen_utc") val runtimeLastSeenUtc: String? = null,
    @SerialName("observation_count") val observationCount: Int,
)

class ControlCenterVisionClient(baseUrl: String, private val bearer: String) {
    companion object {
        const val SCHEMA = "kaliv-control-center-vision/v1"
        const val ENABLED_SCHEMA = "kaliv-control-center-vision-enabled/v1"
        private val PRESENCE = setOf("online", "stale", "offline", "unknown")
        private val CONVERGENCE = setOf("converged", "pending", "unknown")
        private val LIFECYCLE = setOf("active", "retired")
        private val TRANSPORT = setOf("normal", "warning", "critical", "unknown")
        private val REFRESH = setOf("current", "stale", "unknown")
        private val CONSISTENCY = setOf("synced", "registry_ahead", "journal_ahead", "unknown")
        private val SOURCE_TYPE = Regex("^[a-z][a-z0-9_-]{0,31}$")
    }

    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun snapshot(): ControlCenterVisionSnapshot {
        val envelope = decode<ControlCenterVisionStatusEnvelope>(
            get("/api/v1/control-center/status", "VisionRig status"),
            "VisionRig status",
        )
        return validateSnapshot(envelope.vision)
    }

    internal fun parseSnapshot(body: String): ControlCenterVisionSnapshot =
        validateSnapshot(decode<VisionWireSnapshot>(body, "VisionRig status"))

    fun setEnabled(sourceId: String, enabled: Boolean): ControlCenterVisionEnabledReceipt {
        val normalized = sourceId.trim()
        if (normalized.isEmpty() || normalized.length > 128) {
            throw ControlCenterException("Invalid VisionRig source id")
        }
        val wire = decode<VisionEnabledWireReceipt>(
            patch(
                "/api/v1/control-center/vision/sensors/${seg(normalized)}/enabled",
                """{"enabled":$enabled}""",
                "VisionRig sensor control",
            ),
            "VisionRig sensor control",
        )
        if (wire.schema != ENABLED_SCHEMA) {
            throw ControlCenterException("Invalid VisionRig sensor control receipt schema")
        }
        if (wire.sourceId != normalized || wire.enabled != enabled) {
            throw ControlCenterException("VisionRig sensor control receipt does not match request")
        }
        return ControlCenterVisionEnabledReceipt(wire.sourceId, wire.enabled)
    }

    private fun validateSnapshot(wire: VisionWireSnapshot): ControlCenterVisionSnapshot {
        if (wire.schema != SCHEMA) fail("unsupported schema ${wire.schema}")
        if (wire.productionActivation) fail("production_activation must be false")
        if (!wire.available && wire.sensors.isNotEmpty()) fail("unavailable snapshot contains sensors")
        if (wire.available && !wire.reason.isNullOrBlank()) fail("available snapshot contains failure reason")
        if (wire.consistency !in CONSISTENCY) fail("unsupported consistency ${wire.consistency}")
        if (wire.total < 0 || wire.sensorsReturned < 0 || wire.attentionTotal < 0) {
            fail("negative summary count")
        }
        wire.sensorStateRevision?.let { if (it < 0) fail("negative state revision") }

        val sensors = wire.sensors.mapIndexed { index, sensor ->
            val path = "sensors[$index]"
            val sourceId = sensor.sourceId.trim()
            if (sourceId.isEmpty() || sourceId.length > 128) fail("$path.source_id is invalid")
            if (!SOURCE_TYPE.matches(sensor.sourceType)) fail("$path.source_type is invalid")
            if (sensor.presence !in PRESENCE) fail("$path.presence is invalid")
            if (sensor.convergence !in CONVERGENCE) fail("$path.convergence is invalid")
            if (sensor.lifecycle !in LIFECYCLE) fail("$path.lifecycle is invalid")
            if (sensor.transportStatus !in TRANSPORT) fail("$path.transport_status is invalid")
            if (sensor.capabilityRefreshStatus !in REFRESH) fail("$path.capability_refresh_status is invalid")
            if (sensor.observationCount < 0) fail("$path.observation_count is negative")
            if (sensor.desiredRevision < 0) fail("$path.desired_revision is negative")
            sensor.appliedRevision?.let { if (it < 0) fail("$path.applied_revision is negative") }
            sensor.pendingSeconds?.let {
                if (!it.isFinite() || it < 0.0) fail("$path.pending_seconds is invalid")
            }
            sensor.payloadUtilization?.let {
                if (!it.isFinite() || it < 0.0) fail("$path.payload_utilization is invalid")
            }
            sensor.negotiatedPacketTargetUtilization?.let {
                if (!it.isFinite() || it <= 0.0 || it >= 1.0) {
                    fail("$path.negotiated target utilization is invalid")
                }
            }
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
                lifecycle = sensor.lifecycle,
                desiredRevision = sensor.desiredRevision,
                appliedRevision = sensor.appliedRevision,
                pendingSeconds = sensor.pendingSeconds,
                transportStatus = sensor.transportStatus,
                payloadUtilization = sensor.payloadUtilization,
                capabilityRefreshStatus = sensor.capabilityRefreshStatus,
                negotiatedMaxPayloadBytes = sensor.negotiatedMaxPayloadBytes,
                negotiatedPacketCompression = sensor.negotiatedPacketCompression,
                negotiatedPacketTargetUtilization = sensor.negotiatedPacketTargetUtilization,
                firstSeenUtc = sensor.firstSeenUtc,
                lastSeenUtc = sensor.lastSeenUtc,
                runtimeLastSeenUtc = sensor.runtimeLastSeenUtc,
                observationCount = sensor.observationCount,
            )
        }
        if (sensors.map { it.sourceId }.distinct().size != sensors.size) {
            fail("duplicate source ids")
        }
        if (wire.sensorsReturned != sensors.size) {
            fail("sensors_returned contradicts sensor list")
        }
        if (wire.available && !wire.sensorsTruncated && wire.total != sensors.size) {
            fail("total contradicts untruncated sensor list")
        }
        if (wire.available && wire.sensorsTruncated && wire.total <= sensors.size) {
            fail("truncated snapshot requires hidden sensors")
        }
        return ControlCenterVisionSnapshot(
            available = wire.available,
            reason = wire.reason?.trim()?.takeIf { it.isNotEmpty() },
            sensorStateRevision = wire.sensorStateRevision,
            controlAvailable = wire.controlAvailable,
            consistency = wire.consistency,
            total = wire.total,
            sensorsReturned = wire.sensorsReturned,
            sensorsTruncated = wire.sensorsTruncated,
            attentionTotal = wire.attentionTotal,
            attentionTruncated = wire.attentionTruncated,
            sensors = sensors.sortedBy { it.sourceId },
        )
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
            .header("Authorization", "Bearer $bearer")
            .header("Content-Type", "application/json")
            .timeout(Duration.ofSeconds(10))
            .method("PATCH", HttpRequest.BodyPublishers.ofString(body))
            .build()
        return execute(request, label)
    }

    private fun seg(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20")

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


    private fun fail(message: String): Nothing =
        throw ControlCenterException("Invalid Control Center VisionRig payload: $message")
}

data class ControlCenterVisionSnapshot(
    val available: Boolean,
    val reason: String?,
    val sensorStateRevision: Long?,
    val controlAvailable: Boolean,
    val consistency: String,
    val total: Int,
    val sensorsReturned: Int,
    val sensorsTruncated: Boolean,
    val attentionTotal: Int,
    val attentionTruncated: Boolean,
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
    val lifecycle: String,
    val desiredRevision: Long,
    val appliedRevision: Long?,
    val pendingSeconds: Double?,
    val transportStatus: String,
    val payloadUtilization: Double?,
    val capabilityRefreshStatus: String,
    val negotiatedMaxPayloadBytes: Long?,
    val negotiatedPacketCompression: String?,
    val negotiatedPacketTargetUtilization: Double?,
    val firstSeenUtc: String?,
    val lastSeenUtc: String?,
    val runtimeLastSeenUtc: String?,
    val observationCount: Int,
) {
    val title: String get() = displayName ?: sourceId
}


data class ControlCenterVisionEnabledReceipt(
    val sourceId: String,
    val enabled: Boolean,
)

