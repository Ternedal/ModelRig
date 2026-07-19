package dk.ternedal.modelrig.net

import org.json.JSONArray
import org.json.JSONObject

private const val CAPABILITY_SCHEMA_V2 = "kaliv-capability/v2"

class CapabilityContractException(message: String, cause: Throwable? = null) :
    IllegalArgumentException(message, cause)

data class CapabilityIsolationV2(
    val mode: String,
    val envAllow: List<String>,
)

data class CapabilitySchedulingV2(
    val allowed: Boolean,
    val reason: String,
)

data class CapabilityConfirmationV2(val mode: String)

data class CapabilityNetworkV2(
    val mode: String,
    val destinations: List<String>,
)

data class CapabilityTerminationV2(val mode: String)

data class CapabilityReplayV2(val idempotent: Boolean)

data class CapabilityDescriptorV2(
    val schema: String,
    val capabilityId: String,
    val kind: String,
    val description: String,
    val access: String,
    val impact: String,
    val dataClass: String,
    val parameters: JSONObject,
    val isolation: CapabilityIsolationV2,
    val scheduling: CapabilitySchedulingV2,
    val confirmation: CapabilityConfirmationV2,
    val network: CapabilityNetworkV2,
    val termination: CapabilityTerminationV2,
    val replay: CapabilityReplayV2,
    val productionActivation: Boolean,
    private val canonical: String,
) {
    fun canonicalJson(): String = canonical

    companion object {
        private val topLevelKeys = setOf(
            "schema",
            "capability_id",
            "kind",
            "description",
            "access",
            "impact",
            "data_class",
            "parameters",
            "isolation",
            "scheduling",
            "confirmation",
            "network",
            "termination",
            "replay",
            "production_activation",
        )
        private val accessValues = setOf("read", "write", "desktop")
        private val impactValues = setOf("read", "write", "desktop", "destructive", "admin")
        private val dataClassValues = setOf("public", "operational", "private", "secret")
        private val isolationModes = setOf("in_process", "process")
        private val confirmationModes = setOf("none", "required")
        private val networkModes = setOf(
            "none",
            "loopback",
            "configured_service",
            "public",
            "undeclared",
        )
        private val terminationModes = setOf("none", "cooperative", "forceable")
        private val capabilityIdPattern = Regex("^tool:[A-Za-z0-9._:-]{1,155}$")

        fun parse(raw: String): CapabilityDescriptorV2 = try {
            parse(JSONObject(raw))
        } catch (exc: CapabilityContractException) {
            throw exc
        } catch (exc: Exception) {
            throw CapabilityContractException("invalid capability descriptor JSON", exc)
        }

        fun parse(source: JSONObject): CapabilityDescriptorV2 {
            requireExactKeys(source, topLevelKeys, "descriptor")
            val schema = requireString(source, "schema")
            val capabilityId = requireString(source, "capability_id")
            val kind = requireString(source, "kind")
            val description = requireString(source, "description")
            val access = requireString(source, "access")
            val impact = requireString(source, "impact")
            val dataClass = requireString(source, "data_class")
            val parameters = requireObject(source, "parameters")
            val isolationObject = requireObject(source, "isolation")
            val schedulingObject = requireObject(source, "scheduling")
            val confirmationObject = requireObject(source, "confirmation")
            val networkObject = requireObject(source, "network")
            val terminationObject = requireObject(source, "termination")
            val replayObject = requireObject(source, "replay")
            val productionActivation = requireBoolean(source, "production_activation")

            requireContract(schema == CAPABILITY_SCHEMA_V2, "unsupported schema: $schema")
            requireContract(capabilityIdPattern.matches(capabilityId), "invalid capability_id")
            requireContract(kind == "tool", "kind must be tool")
            requireContract(description.isNotEmpty(), "description must be non-empty")
            requireContract(access in accessValues, "unsupported access: $access")
            requireContract(impact in impactValues, "unsupported impact: $impact")
            requireContract(dataClass in dataClassValues, "unsupported data_class: $dataClass")
            requireContract(!productionActivation, "capability schema must never activate production")

            requireExactKeys(isolationObject, setOf("mode", "env_allow"), "isolation")
            val isolation = CapabilityIsolationV2(
                mode = requireString(isolationObject, "mode"),
                envAllow = requireStringList(isolationObject, "env_allow"),
            )
            requireContract(isolation.mode in isolationModes, "unsupported isolation.mode")

            requireExactKeys(schedulingObject, setOf("allowed", "reason"), "scheduling")
            val scheduling = CapabilitySchedulingV2(
                allowed = requireBoolean(schedulingObject, "allowed"),
                reason = requireString(schedulingObject, "reason"),
            )
            requireContract(
                (!scheduling.allowed && scheduling.reason.isNotBlank()) ||
                    (scheduling.allowed && scheduling.reason.isEmpty()),
                "scheduling reason contradicts allowed",
            )

            requireExactKeys(confirmationObject, setOf("mode"), "confirmation")
            val confirmation = CapabilityConfirmationV2(
                mode = requireString(confirmationObject, "mode"),
            )
            requireContract(confirmation.mode in confirmationModes, "unsupported confirmation.mode")
            val expectedConfirmation = if (access == "read") "none" else "required"
            requireContract(
                confirmation.mode == expectedConfirmation,
                "confirmation mode contradicts access",
            )

            requireExactKeys(networkObject, setOf("mode", "destinations"), "network")
            val network = CapabilityNetworkV2(
                mode = requireString(networkObject, "mode"),
                destinations = requireStringList(networkObject, "destinations"),
            )
            requireContract(network.mode in networkModes, "unsupported network.mode")
            requireContract(
                network.mode !in setOf("none", "undeclared") || network.destinations.isEmpty(),
                "network destinations require a networked mode",
            )
            requireContract(
                network.mode !in setOf("loopback", "configured_service", "public") ||
                    network.destinations.isNotEmpty(),
                "networked mode requires a destination",
            )

            requireExactKeys(terminationObject, setOf("mode"), "termination")
            val termination = CapabilityTerminationV2(
                mode = requireString(terminationObject, "mode"),
            )
            requireContract(termination.mode in terminationModes, "unsupported termination.mode")

            requireExactKeys(replayObject, setOf("idempotent"), "replay")
            val replay = CapabilityReplayV2(
                idempotent = requireBoolean(replayObject, "idempotent"),
            )

            val immutableCopy = JSONObject(source.toString())
            return CapabilityDescriptorV2(
                schema = schema,
                capabilityId = capabilityId,
                kind = kind,
                description = description,
                access = access,
                impact = impact,
                dataClass = dataClass,
                parameters = JSONObject(parameters.toString()),
                isolation = isolation,
                scheduling = scheduling,
                confirmation = confirmation,
                network = network,
                termination = termination,
                replay = replay,
                productionActivation = productionActivation,
                canonical = canonicalize(immutableCopy),
            )
        }

        private fun requireExactKeys(value: JSONObject, expected: Set<String>, field: String) {
            val actual = value.keys().asSequence().toSet()
            requireContract(actual == expected, "$field fields differ: $actual")
        }

        private fun requireString(value: JSONObject, key: String): String {
            val item = value.get(key)
            if (item !is String) throw CapabilityContractException("$key must be a string")
            return item
        }

        private fun requireBoolean(value: JSONObject, key: String): Boolean {
            val item = value.get(key)
            if (item !is Boolean) throw CapabilityContractException("$key must be boolean")
            return item
        }

        private fun requireObject(value: JSONObject, key: String): JSONObject {
            val item = value.get(key)
            if (item !is JSONObject) throw CapabilityContractException("$key must be an object")
            return item
        }

        private fun requireStringList(value: JSONObject, key: String): List<String> {
            val item = value.get(key)
            if (item !is JSONArray) throw CapabilityContractException("$key must be an array")
            val result = (0 until item.length()).map { index ->
                val entry = item.get(index)
                if (entry !is String || entry.isBlank()) {
                    throw CapabilityContractException("$key contains an empty or non-string value")
                }
                entry
            }
            requireContract(result.size == result.toSet().size, "$key contains duplicates")
            return result
        }

        private fun requireContract(condition: Boolean, message: String) {
            if (!condition) throw CapabilityContractException(message)
        }

        private fun canonicalize(value: Any?): String = when (value) {
            null, JSONObject.NULL -> "null"
            is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(
                prefix = "{",
                postfix = "}",
                separator = ",",
            ) { key -> JSONObject.quote(key) + ":" + canonicalize(value.get(key)) }
            is JSONArray -> (0 until value.length()).joinToString(
                prefix = "[",
                postfix = "]",
                separator = ",",
            ) { index -> canonicalize(value.get(index)) }
            is String -> JSONObject.quote(value)
            is Boolean -> value.toString()
            is Number -> JSONObject.numberToString(value)
            else -> throw CapabilityContractException(
                "unsupported JSON value in canonical descriptor: ${value::class.java.name}",
            )
        }
    }
}
