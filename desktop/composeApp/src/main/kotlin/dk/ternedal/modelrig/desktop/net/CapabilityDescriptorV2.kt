package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.encodeToJsonElement

private const val CAPABILITY_SCHEMA_V2 = "kaliv-capability/v2"

class CapabilityContractException(message: String, cause: Throwable? = null) :
    IllegalArgumentException(message, cause)

@Serializable
data class CapabilityIsolationV2(
    val mode: String,
    @SerialName("env_allow") val envAllow: List<String>,
)

@Serializable
data class CapabilitySchedulingV2(
    val allowed: Boolean,
    val reason: String,
)

@Serializable
data class CapabilityConfirmationV2(val mode: String)

@Serializable
data class CapabilityNetworkV2(
    val mode: String,
    val destinations: List<String>,
)

@Serializable
data class CapabilityTerminationV2(val mode: String)

@Serializable
data class CapabilityReplayV2(val idempotent: Boolean)

@Serializable
data class CapabilityDescriptorV2(
    val schema: String,
    @SerialName("capability_id") val capabilityId: String,
    val kind: String,
    val description: String,
    val access: String,
    val impact: String,
    @SerialName("data_class") val dataClass: String,
    val parameters: JsonObject,
    val isolation: CapabilityIsolationV2,
    val scheduling: CapabilitySchedulingV2,
    val confirmation: CapabilityConfirmationV2,
    val network: CapabilityNetworkV2,
    val termination: CapabilityTerminationV2,
    val replay: CapabilityReplayV2,
    @SerialName("production_activation") val productionActivation: Boolean,
) {
    fun canonicalJson(): String {
        val encoded = capabilityJson.encodeToJsonElement(serializer(), this)
        return capabilityJson.encodeToString(JsonElement.serializer(), encoded.sortedKeys())
    }

    private fun validate(): CapabilityDescriptorV2 {
        requireContract(schema == CAPABILITY_SCHEMA_V2, "unsupported schema: $schema")
        requireContract(
            Regex("^tool:[A-Za-z0-9._:-]{1,155}$").matches(capabilityId),
            "invalid capability_id",
        )
        requireContract(kind == "tool", "kind must be tool")
        requireContract(description.isNotEmpty(), "description must be non-empty")
        requireContract(access in setOf("read", "write", "desktop"), "unsupported access")
        requireContract(
            impact in setOf("read", "write", "desktop", "destructive", "admin"),
            "unsupported impact",
        )
        requireContract(
            dataClass in setOf("public", "operational", "private", "secret"),
            "unsupported data_class",
        )
        requireContract(
            isolation.mode in setOf("in_process", "process"),
            "unsupported isolation.mode",
        )
        validateStringList(isolation.envAllow, "isolation.env_allow")
        requireContract(
            (scheduling.allowed && scheduling.reason.isEmpty()) ||
                (!scheduling.allowed && scheduling.reason.isNotBlank()),
            "scheduling reason contradicts allowed",
        )
        requireContract(
            confirmation.mode in setOf("none", "required"),
            "unsupported confirmation.mode",
        )
        val expectedConfirmation = if (access == "read") "none" else "required"
        requireContract(
            confirmation.mode == expectedConfirmation,
            "confirmation mode contradicts access",
        )
        requireContract(
            network.mode in setOf(
                "none",
                "loopback",
                "configured_service",
                "public",
                "undeclared",
            ),
            "unsupported network.mode",
        )
        validateStringList(network.destinations, "network.destinations")
        requireContract(
            network.mode !in setOf("none", "undeclared") || network.destinations.isEmpty(),
            "network destinations require a networked mode",
        )
        requireContract(
            network.mode !in setOf("loopback", "configured_service", "public") ||
                network.destinations.isNotEmpty(),
            "networked mode requires a destination",
        )
        requireContract(
            termination.mode in setOf("none", "cooperative", "forceable"),
            "unsupported termination.mode",
        )
        requireContract(!productionActivation, "capability schema must never activate production")
        return this
    }

    companion object {
        fun parse(raw: String): CapabilityDescriptorV2 = try {
            capabilityJson.decodeFromString(serializer(), raw).validate()
        } catch (exc: CapabilityContractException) {
            throw exc
        } catch (exc: SerializationException) {
            throw CapabilityContractException("invalid capability descriptor JSON", exc)
        } catch (exc: IllegalArgumentException) {
            throw CapabilityContractException("invalid capability descriptor", exc)
        }

        private fun requireContract(condition: Boolean, message: String) {
            if (!condition) throw CapabilityContractException(message)
        }

        private fun validateStringList(values: List<String>, field: String) {
            requireContract(values.all { it.isNotBlank() }, "$field contains an empty value")
            requireContract(values.size == values.toSet().size, "$field contains duplicates")
        }
    }
}

private val capabilityJson = Json {
    ignoreUnknownKeys = false
    isLenient = false
    explicitNulls = true
    encodeDefaults = true
}

private fun JsonElement.sortedKeys(): JsonElement = when (this) {
    is JsonObject -> JsonObject(
        entries.sortedBy { it.key }.associate { (key, value) -> key to value.sortedKeys() },
    )
    is JsonArray -> JsonArray(map { it.sortedKeys() })
    else -> this
}
