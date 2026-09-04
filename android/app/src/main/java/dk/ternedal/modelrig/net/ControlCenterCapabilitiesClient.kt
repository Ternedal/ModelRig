package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Read-only Control Center view of the canonical T-030 capability descriptors.
 *
 * Runtime enablement belongs to ToolGate and is deliberately kept outside the
 * immutable `kaliv-capability/v2` descriptor. The client validates the same
 * safety axes as the worker schema before any metadata can be rendered.
 */
class ControlCenterCapabilitiesClient(baseUrl: String, private val token: String) {
    companion object {
        const val SCHEMA = "kaliv-capability/v2"

        private val DESCRIPTOR_KEYS = setOf(
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
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    fun inventory(): ControlCenterCapabilityInventory {
        val request = Request.Builder()
            .url(base + "/api/v1/tools")
            .header("Authorization", "Bearer $token")
            .get()
            .build()
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val root = JSONObject(body)
                    root.optString("error").ifBlank { root.optString("detail") }
                }.getOrDefault("").ifBlank { body }.take(500)
                throw ModelRigException(
                    "control center capabilities failed (${response.code}): $detail",
                )
            }
            if (body.isBlank()) {
                throw ModelRigException("control center capabilities returned an empty body")
            }
            return parse(JSONObject(body))
        }
    }

    internal fun parse(root: JSONObject): ControlCenterCapabilityInventory {
        val toolLayerEnabled = root.requireBoolean("enabled")
        val tools = root.optJSONArray("tools")
            ?: fail("tools must be an array")

        val parsed = buildList {
            for (index in 0 until tools.length()) {
                val item = tools.optJSONObject(index)
                    ?: fail("tools[$index] must be an object")
                val name = item.requireString("name")
                val enabled = item.requireBoolean("enabled")
                val descriptor = item.optJSONObject("descriptor")
                    ?: fail("$name descriptor must be an object")
                add(parseDescriptor(name, enabled, descriptor))
            }
        }

        val ids = parsed.map { it.capabilityId }
        if (ids.size != ids.toSet().size) fail("duplicate capability ids")

        return ControlCenterCapabilityInventory(
            toolLayerEnabled = toolLayerEnabled,
            capabilities = parsed.sortedBy { it.capabilityId },
        )
    }

    private fun parseDescriptor(
        toolName: String,
        enabled: Boolean,
        value: JSONObject,
    ): ControlCenterCapability {
        requireExactKeys(value, DESCRIPTOR_KEYS, "$toolName descriptor")

        val schema = value.requireString("schema")
        if (schema != SCHEMA) fail("$toolName unsupported descriptor schema $schema")

        val capabilityId = value.requireString("capability_id")
        if (!CAPABILITY_ID.matches(capabilityId)) fail("$toolName invalid capability id")
        if (capabilityId != "tool:$toolName") fail("$toolName capability id mismatch")

        if (value.requireString("kind") != "tool") fail("$toolName kind must be tool")
        val description = value.requireString("description")
        val access = value.requireEnum("access", ACCESS)
        val impact = value.requireEnum("impact", IMPACT)
        val dataClass = value.requireEnum("data_class", DATA_CLASS)
        value.requireObject("parameters")

        val isolation = value.requireObject("isolation")
        requireExactKeys(isolation, setOf("mode", "env_allow"), "$toolName isolation")
        val isolationMode = isolation.requireEnum("mode", ISOLATION)
        parseUniqueStrings(isolation, "env_allow", allowEmpty = true, context = "$toolName isolation")

        val scheduling = value.requireObject("scheduling")
        requireExactKeys(scheduling, setOf("allowed", "reason"), "$toolName scheduling")
        val schedulable = scheduling.requireBoolean("allowed")
        val schedulingReason = scheduling.requireRawString("reason")
        if (schedulable && schedulingReason.isNotEmpty()) {
            fail("$toolName schedulable capability carries a refusal reason")
        }
        if (!schedulable && schedulingReason.isBlank()) {
            fail("$toolName unschedulable capability lacks a reason")
        }

        val confirmation = value.requireObject("confirmation")
        requireExactKeys(confirmation, setOf("mode"), "$toolName confirmation")
        val confirmationMode = confirmation.requireEnum("mode", CONFIRMATION)

        val network = value.requireObject("network")
        requireExactKeys(network, setOf("mode", "destinations"), "$toolName network")
        val networkMode = network.requireEnum("mode", NETWORK)
        val networkDestinations = parseUniqueStrings(
            network,
            "destinations",
            allowEmpty = true,
            context = "$toolName network",
        )
        if (networkMode in setOf("none", "undeclared") && networkDestinations.isNotEmpty()) {
            fail("$toolName network destinations contradict $networkMode mode")
        }
        if (networkMode in setOf("loopback", "configured_service", "public") && networkDestinations.isEmpty()) {
            fail("$toolName networked mode lacks a destination")
        }

        val expectedConfirmation = if (access != "read" || networkMode == "public") {
            "required"
        } else {
            "none"
        }
        if (confirmationMode != expectedConfirmation) {
            fail("$toolName confirmation contradicts access/network")
        }

        val termination = value.requireObject("termination")
        requireExactKeys(termination, setOf("mode"), "$toolName termination")
        val terminationMode = termination.requireEnum("mode", TERMINATION)

        val replay = value.requireObject("replay")
        requireExactKeys(replay, setOf("idempotent"), "$toolName replay")
        val idempotent = replay.requireBoolean("idempotent")

        val productionActivation = value.requireBoolean("production_activation")
        if (productionActivation) fail("$toolName production activation must remain false")

        return ControlCenterCapability(
            capabilityId = capabilityId,
            name = toolName,
            description = description,
            enabled = enabled,
            access = access,
            impact = impact,
            dataClass = dataClass,
            isolationMode = isolationMode,
            schedulable = schedulable,
            schedulingReason = schedulingReason.takeIf { it.isNotBlank() },
            confirmationMode = confirmationMode,
            networkMode = networkMode,
            networkDestinations = networkDestinations,
            terminationMode = terminationMode,
            idempotent = idempotent,
        )
    }

    private fun requireExactKeys(value: JSONObject, expected: Set<String>, context: String) {
        val actual = value.keys().asSequence().toSet()
        if (actual != expected) {
            val missing = expected - actual
            val unknown = actual - expected
            fail(
                "$context fields differ" +
                    (if (missing.isNotEmpty()) "; missing=${missing.sorted()}" else "") +
                    (if (unknown.isNotEmpty()) "; unknown=${unknown.sorted()}" else ""),
            )
        }
    }

    private fun parseUniqueStrings(
        value: JSONObject,
        key: String,
        allowEmpty: Boolean,
        context: String,
    ): List<String> {
        val array = value.optJSONArray(key) ?: fail("$context.$key must be an array")
        val result = buildList {
            for (index in 0 until array.length()) {
                val raw = array.get(index)
                if (raw !is String) fail("$context.$key[$index] must be a string")
                if (raw.isBlank()) fail("$context.$key contains a blank value")
                add(raw)
            }
        }
        if (!allowEmpty && result.isEmpty()) fail("$context.$key must not be empty")
        if (result.size != result.toSet().size) fail("$context.$key contains duplicates")
        return result
    }

    private fun JSONObject.requireObject(key: String): JSONObject =
        optJSONObject(key) ?: fail("$key must be an object")

    private fun JSONObject.requireString(key: String): String {
        val value = requireRawString(key).trim()
        if (value.isBlank()) fail("blank $key")
        return value
    }

    private fun JSONObject.requireRawString(key: String): String {
        if (!has(key) || isNull(key) || get(key) !is String) fail("$key must be a string")
        return getString(key)
    }

    private fun JSONObject.requireBoolean(key: String): Boolean {
        if (!has(key) || isNull(key) || get(key) !is Boolean) fail("$key must be boolean")
        return getBoolean(key)
    }

    private fun JSONObject.requireEnum(key: String, allowed: Set<String>): String {
        val value = requireString(key)
        if (value !in allowed) fail("unsupported $key $value")
        return value
    }

    private fun fail(message: String): Nothing =
        throw ModelRigException("invalid control center capabilities: $message")
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
