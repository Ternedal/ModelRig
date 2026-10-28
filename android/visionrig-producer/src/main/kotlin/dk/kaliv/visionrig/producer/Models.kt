package dk.kaliv.visionrig.producer

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class DesiredState(
    @SerialName("schema_id") val schemaId: String,
    @SerialName("source_id") val sourceId: String,
    val enabled: Boolean,
    val revision: Long,
    @SerialName("production_authority") val productionAuthority: Boolean,
) {
    fun validate(expectedSourceId: String) {
        require(schemaId == "visionrig/sensor-desired-state/v2")
        require(sourceId == expectedSourceId)
        require(revision >= 0)
        require(!productionAuthority)
    }
}

@Serializable
data class FrameReceipt(
    @SerialName("schema_id") val schemaId: String,
    val status: String,
    @SerialName("source_id") val sourceId: String,
    @SerialName("source_type") val sourceType: String,
    @SerialName("frame_sequence") val frameSequence: Long,
    @SerialName("event_id") val eventId: String,
    @SerialName("dropped_frames") val droppedFrames: Long,
    @SerialName("production_authority") val productionAuthority: Boolean,
) {
    fun validate(
        expectedSourceId: String,
        expectedSourceType: String,
        expectedSequence: Long,
        expectedDroppedFrames: Long,
    ) {
        require(schemaId == "visionrig/sensor-frame-receipt/v1")
        require(status == "processed")
        require(sourceId == expectedSourceId)
        require(sourceType == expectedSourceType)
        require(frameSequence == expectedSequence)
        require(droppedFrames == expectedDroppedFrames)
        require(eventId.isNotBlank())
        require(!productionAuthority)
    }
}

@Serializable
data class HeartbeatReceipt(
    @SerialName("schema_id") val schemaId: String,
    val status: String,
    @SerialName("source_id") val sourceId: String,
    @SerialName("seen_utc") val seenUtc: String,
    @SerialName("production_authority") val productionAuthority: Boolean,
) {
    fun validate(expectedSourceId: String) {
        require(schemaId == "visionrig/sensor-heartbeat-receipt/v1")
        require(status == "accepted")
        require(sourceId == expectedSourceId)
        require(seenUtc.isNotBlank())
        require(!productionAuthority)
    }
}

@Serializable
data class HeartbeatRequest(
    @SerialName("schema_id") val schemaId: String = "visionrig/sensor-heartbeat/v6",
    @SerialName("source_id") val sourceId: String,
    @SerialName("source_type") val sourceType: String,
    val device: String? = null,
    val capabilities: List<String> = emptyList(),
    @SerialName("capture_active") val captureActive: Boolean,
    @SerialName("applied_revision") val appliedRevision: Long,
    @SerialName("negotiated_max_payload_bytes") val negotiatedMaxPayloadBytes: Long? = null,
    @SerialName("capability_refreshed_utc") val capabilityRefreshedUtc: String? = null,
    @SerialName("capability_refresh_seconds") val capabilityRefreshSeconds: Double? = null,
)

enum class SendStatus {
    ACCEPTED,
    DROPPED_OVERLOAD,
    DROPPED_UNAVAILABLE,
}

data class SendResult(
    val status: SendStatus,
    val frameSequence: Long,
    val pendingDroppedFrames: Long,
    val eventId: String? = null,
)

class ProducerProtocolException(message: String, cause: Throwable? = null) :
    RuntimeException(message, cause)

class ProducerAuthenticationException(message: String) : RuntimeException(message)
