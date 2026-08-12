package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonObject
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

@Serializable
private data class CapabilityIsolationWire(
    val mode: String,
    @SerialName("env_allow") val envAllow: List<String>,
)

@Serializable
private data class CapabilitySchedulingWire(
    val allowed: Boolean,
    val reason: String,
)

@Serializable
private data class CapabilityConfirmationWire(val mode: String)

@Serializable
private data class CapabilityNetworkWire(
    val mode: String,
    val destinations: List<String>,
)

@Serializable
private data class CapabilityTerminationWire(val mode: String)

@Serializable
private data class CapabilityReplayWire(val idempotent: Boolean)

@Serializable
private data class CapabilityDescriptorWire(
    val schema: String,
    @SerialName("capability_id") val capabilityId: String,
    val kind: String,
    val description: String,
    val access: String,
    val impact: String,
    @SerialName("data_class") val dataClass: String,
    val parameters: JsonObject,
    val isolation: CapabilityIsolationWire,
    val scheduling: CapabilitySchedulingWire,
    val confirmation: CapabilityConfirmationWire,
    val network: CapabilityNetworkWire,
    val termination: CapabilityTerminationWire,
    val replay: CapabilityReplayWire,
    @SerialName("production_activation") val productionActivation: Boolean,
)

/**
 * Read-only desktop projection of T-030's canonical capability descriptors.
 * Runtime ToolGate state is parsed separately from the immutable descriptor.
 */
class ControlCenterCapabilitiesClient(baseUrl: String, private val bearer: String) {
    companion object {
        const val SCHEMA = "kaliv-capability/v2"

        private val ACCESS = setOf("read", "write", "desktop")
        private val IMPACT = setOf("read", "write", "desktop", "destructive", "admin")
        private val DATA_CLASS = setOf("public", "operational", "private", "secret")
        private val ISOLATION = setOf("in_process", "process")
        private val CONFIRMATION = setOf("none", "required")
        private val NETWORK = setOf("none", "loopback", "configured_service", "public", "undeclared")
        private val TERMINATION = setOf("none", "cooperative", "forceable")
        private val CAPABILITY_ID = Regex("^tool:[A-Za-z0-9._:-]{1,155}$")
    }

    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = false; explicitNulls = false }
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun inventory(): ControlCenterCapabilityInventory {
        val request = HttpRequest.newBuilder(URI.create(base + "/api/v1/tools"))
            .header("Accept", "application/json")
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(10))
            .GET()
            .build()
        val response = try {
            http.send(request, HttpResponse.BodyHandlers.ofString())
        } catch (exc: Exception) {
            throw ControlCenterException(
                "Control Center capabilities failed: ${exc::class.simpleName}",
            )
        }
        if (response.statusCode() !in 200..299) {
            throw ControlCenterException(
                "Control Center capabilities failed (${response.statusCode()}): " +
                    response.body().take(500),
            )
        }
        return parse(response.body())
    }

    internal fun parse(body: String): ControlCenterCapabilityInventory {
        val root = try {
            json.parseToJsonElement(body).jsonObject
        } catch (exc: Exception) {
            fail("invalid JSON: ${exc::class.simpleName}")
        }
        val toolLayerEnabled = root.strictBoolean("enabled")
        val tools = root["tools"] as? JsonArray ?: fail("tools must be an array")
        val capabilities = tools.mapIndexed { index, element ->
            val item = element as? JsonObject ?: fail("tools[$index] must be an object")
            val name = item.strictString("name")
            val enabled = item.strictBoolean("enabled")
            val descriptorObject = item["descriptor"] as? JsonObject
                ?: fail("$name descriptor must be an object")
            parseDescriptor(name, enabled, descriptorObject)
        }
        val ids = capabilities.map { it.capabilityId }
        if (ids.size != ids.toSet().size) fail("duplicate capability ids")
        return ControlCenterCapabilityInventory(
            toolLayerEnabled = toolLayerEnabled,
            capabilities = capabilities.sortedBy { it.capabilityId },
        )
    }

    private fun parseDescriptor(
        toolName: String,
        enabled: Boolean,
        payload: JsonObject,
    ): ControlCenterCapability {
        val wire = try {
            json.decodeFromJsonElement<CapabilityDescriptorWire>(payload)
        } catch (exc: Exception) {
            fail("$toolName invalid descriptor: ${exc::class.simpleName}")
        }
        if (wire.schema != SCHEMA) fail("$toolName unsupported descriptor schema ${wire.schema}")
        if (!CAPABILITY_ID.matches(wire.capabilityId)) fail("$toolName invalid capability id")
        if (wire.capabilityId != "tool:$toolName") fail("$toolName capability id mismatch")
        if (wire.kind != "tool") fail("$toolName kind must be tool")
        if (wire.description.isBlank()) fail("$toolName description must contain visible text")
        requireEnum(toolName, "access", wire.access, ACCESS)
        requireEnum(toolName, "impact", wire.impact, IMPACT)
        requireEnum(toolName, "data_class", wire.dataClass, DATA_CLASS)
        requireEnum(toolName, "isolation.mode", wire.isolation.mode, ISOLATION)
        requireUniqueStrings(toolName, "isolation.env_allow", wire.isolation.envAllow)
        requireEnum(toolName, "confirmation.mode", wire.confirmation.mode, CONFIRMATION)
        requireEnum(toolName, "network.mode", wire.network.mode, NETWORK)
        requireUniqueStrings(toolName, "network.destinations", wire.network.destinations)
        requireEnum(toolName, "termination.mode", wire.termination.mode, TERMINATION)

        if (wire.scheduling.allowed && wire.scheduling.reason.isNotEmpty()) {
            fail("$toolName schedulable capability carries a refusal reason")
        }
        if (!wire.scheduling.allowed && wire.scheduling.reason.isBlank()) {
            fail("$toolName unschedulable capability lacks a reason")
        }
        if (wire.network.mode in setOf("none", "undeclared") && wire.network.destinations.isNotEmpty()) {
            fail("$toolName network destinations contradict ${wire.network.mode} mode")
        }
        if (wire.network.mode in setOf("loopback", "configured_service", "public") && wire.network.destinations.isEmpty()) {
            fail("$toolName networked mode lacks a destination")
        }
        val expectedConfirmation = if (wire.access != "read" || wire.network.mode == "public") {
            "required"
        } else {
            "none"
        }
        if (wire.confirmation.mode != expectedConfirmation) {
            fail("$toolName confirmation contradicts access/network")
        }
        if (wire.productionActivation) {
            fail("$toolName production activation must remain false")
        }

        return ControlCenterCapability(
            capabilityId = wire.capabilityId,
            name = toolName,
            description = wire.description.trim(),
            enabled = enabled,
            access = wire.access,
            impact = wire.impact,
            dataClass = wire.dataClass,
            isolationMode = wire.isolation.mode,
            schedulable = wire.scheduling.allowed,
            schedulingReason = wire.scheduling.reason.takeIf { it.isNotBlank() },
            confirmationMode = wire.confirmation.mode,
            networkMode = wire.network.mode,
            networkDestinations = wire.network.destinations,
            terminationMode = wire.termination.mode,
            idempotent = wire.replay.idempotent,
        )
    }

    private fun requireEnum(tool: String, field: String, value: String, allowed: Set<String>) {
        if (value !in allowed) fail("$tool unsupported $field $value")
    }

    private fun requireUniqueStrings(tool: String, field: String, values: List<String>) {
        if (values.any { it.isBlank() }) fail("$tool $field contains a blank value")
        if (values.size != values.toSet().size) fail("$tool $field contains duplicates")
    }

    private fun JsonObject.strictString(key: String): String {
        val primitive = this[key] as? JsonPrimitive ?: fail("$key must be a string")
        if (!primitive.isString) fail("$key must be a string")
        val value = primitive.content.trim()
        if (value.isBlank()) fail("blank $key")
        return value
    }

    private fun JsonObject.strictBoolean(key: String): Boolean {
        val primitive = this[key] as? JsonPrimitive ?: fail("$key must be boolean")
        if (primitive.isString) fail("$key must be boolean")
        return primitive.booleanOrNull ?: fail("$key must be boolean")
    }

    private fun fail(message: String): Nothing =
        throw ControlCenterException("Invalid Control Center capabilities: $message")
}

data class ControlCenterCapabilityInventory(
    val toolLayerEnabled: Boolean,
    val capabilities: List<ControlCenterCapability>,
)

data class ControlCenterCapability(
    val capabilityId: String,
    val name: String,
    val description: String,
    val enabled: Boolean,
    val access: String,
    val impact: String,
    val dataClass: String,
    val isolationMode: String,
    val schedulable: Boolean,
    val schedulingReason: String?,
    val confirmationMode: String,
    val networkMode: String,
    val networkDestinations: List<String>,
    val terminationMode: String,
    val idempotent: Boolean,
)
