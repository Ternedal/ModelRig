package dk.kaliv.visionrig.producer

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class ProducerCapabilities(
    val schema: String,
    @SerialName("max_payload_bytes") val maxPayloadBytes: Long,
    @SerialName("gateway_max_payload_bytes") val gatewayMaxPayloadBytes: Long,
    @SerialName("core_max_payload_bytes") val coreMaxPayloadBytes: Long,
    @SerialName("sensor_packet_schemas") val sensorPacketSchemas: List<String>,
    @SerialName("sensor_packet_compressions") val sensorPacketCompressions: List<String>,
    @SerialName("packet_payload_warning_utilization")
    val packetPayloadWarningUtilization: Double? = null,
    @SerialName("packet_payload_critical_utilization")
    val packetPayloadCriticalUtilization: Double? = null,
) {
    fun validate() {
        require(schema == "visionrig/producer-capabilities/v2")
        require(maxPayloadBytes in 1024..64L * 1024 * 1024)
        require(gatewayMaxPayloadBytes in 1024..64L * 1024 * 1024)
        require(coreMaxPayloadBytes in 1024..64L * 1024 * 1024)
        require(maxPayloadBytes == minOf(gatewayMaxPayloadBytes, coreMaxPayloadBytes))
        val warning = packetPayloadWarningUtilization
            ?: throw IllegalArgumentException("producer capabilities lack warning threshold")
        val critical = packetPayloadCriticalUtilization
            ?: throw IllegalArgumentException("producer capabilities lack critical threshold")
        require(warning > 0.0 && warning < critical)
        require(critical <= 1.0)
    }
}
