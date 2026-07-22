package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Read-only authenticated client for the server-authoritative Control Center.
 *
 * The client deliberately does not derive health from raw subsystem values. It
 * accepts only the versioned backend contract and rejects contradictory or
 * unknown states, so stale/unknown data can never be painted green locally.
 */
class ControlCenterClient(baseUrl: String, private val token: String) {
    companion object {
        const val SCHEMA = "kaliv-control-center-status/v1"
        private val OVERALL_STATES = setOf("healthy", "attention", "unavailable", "unknown")
        private val COMPONENT_STATES = setOf("healthy", "unavailable", "unknown", "stale", "disabled")
        private val ROUTING_STATES = setOf("healthy", "fallback", "unknown", "stale", "disabled")
        private val REQUIRED_COMPONENTS = setOf("backend", "worker", "models", "agent3")
    }

    private val base = baseUrl.trimEnd('/')
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    fun status(): ControlCenterStatus {
        val request = Request.Builder()
            .url(base + "/api/v1/control-center/status")
            .header("Authorization", "Bearer $token")
            .get()
            .build()
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val json = JSONObject(body)
                    json.optString("detail").ifBlank { json.optString("error") }
                }.getOrDefault("").ifBlank { body }.take(500)
                throw ModelRigException(
                    "control center status failed (${response.code}): $detail",
                )
            }
            if (body.isBlank()) {
                throw ModelRigException("control center status returned an empty body")
            }
            return parse(JSONObject(body))
        }
    }

    internal fun parse(root: JSONObject): ControlCenterStatus {
        val schema = root.requireString("schema")
        if (schema != SCHEMA) fail("unsupported schema $schema")

        val generatedAt = root.requireFiniteDouble("generated_at")
        val freshnessSeconds = root.requireFiniteDouble("freshness_s")
        if (freshnessSeconds <= 0.0) fail("freshness_s must be positive")

        val overall = root.requireEnum("overall", OVERALL_STATES)
        val green = root.requireBoolean("green")
        if (green != (overall == "healthy")) {
            fail("overall/green contradiction")
        }

        val componentJson = root.requireObject("components")
        val components = linkedMapOf<String, ControlCenterComponent>()
        val keys = componentJson.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            components[key] = parseComponent(key, componentJson.requireObject(key))
        }
        val missing = REQUIRED_COMPONENTS - components.keys
        if (missing.isNotEmpty()) fail("missing components: ${missing.sorted().joinToString()}")

        val routing = parseRouting(root.requireObject("routing"))
        val summaryJson = root.requireObject("summary")
        val requiredFailuresJson = summaryJson.optJSONArray("required_failures")
            ?: fail("summary.required_failures must be an array")
        val requiredFailures = (0 until requiredFailuresJson.length()).map { index ->
            val value = requiredFailuresJson.optString(index, "")
            if (value.isBlank()) fail("blank required failure")
            value
        }

        return ControlCenterStatus(
            schema = schema,
            generatedAt = generatedAt,
            freshnessSeconds = freshnessSeconds,
            overall = overall,
            green = green,
            components = components.toMap(),
            routing = routing,
            requiredFailures = requiredFailures,
        )
    }

    private fun parseComponent(key: String, value: JSONObject): ControlCenterComponent {
        val name = value.requireString("name")
        if (name != key) fail("component name/key mismatch for $key")
        val state = value.requireEnum("state", COMPONENT_STATES)
        val green = value.requireBoolean("green")
        if (green != (state == "healthy")) fail("component $key state/green contradiction")
        val observedAt = value.optionalFiniteDouble("observed_at")
        val ageSeconds = value.optionalFiniteDouble("age_s")
        if (ageSeconds != null && ageSeconds < 0.0) fail("component $key has negative age")
        if (state == "healthy" && (observedAt == null || ageSeconds == null)) {
            fail("healthy component $key lacks freshness evidence")
        }
        return ControlCenterComponent(
            name = name,
            required = value.requireBoolean("required"),
            state = state,
            green = green,
            observedAt = observedAt,
            ageSeconds = ageSeconds,
            detail = value.optionalString("detail"),
            reason = value.optionalString("reason"),
        )
    }

    private fun parseRouting(value: JSONObject): ControlCenterRouting {
        val state = value.requireEnum("state", ROUTING_STATES)
        val green = value.requireBoolean("green")
        if (green != (state == "healthy")) fail("routing state/green contradiction")
        val fallbackReason = value.optionalString("fallback_reason")
        if (state == "fallback" && fallbackReason == null) {
            fail("fallback routing lacks server reason")
        }
        val ageSeconds = value.optionalFiniteDouble("age_s")
        if (ageSeconds != null && ageSeconds < 0.0) fail("routing has negative age")
        return ControlCenterRouting(
            state = state,
            green = green,
            configuredSurface = value.optionalString("configured_surface"),
            activeSurface = value.optionalString("active_surface"),
            fallbackReason = fallbackReason,
            observedAt = value.optionalFiniteDouble("observed_at"),
            ageSeconds = ageSeconds,
            reason = value.optionalString("reason"),
        )
    }

    private fun JSONObject.requireObject(key: String): JSONObject =
        optJSONObject(key) ?: fail("$key must be an object")

    private fun JSONObject.requireString(key: String): String {
        if (!has(key) || isNull(key)) fail("missing $key")
        val value = optString(key, "").trim()
        if (value.isBlank()) fail("blank $key")
        return value
    }

    private fun JSONObject.optionalString(key: String): String? {
        if (!has(key) || isNull(key)) return null
        return optString(key, "").trim().takeUnless { it.isBlank() }
    }

    private fun JSONObject.requireBoolean(key: String): Boolean {
        if (!has(key) || isNull(key) || get(key) !is Boolean) fail("$key must be boolean")
        return getBoolean(key)
    }

    private fun JSONObject.requireFiniteDouble(key: String): Double {
        if (!has(key) || isNull(key)) fail("missing $key")
        val value = runCatching { getDouble(key) }.getOrElse { fail("$key must be numeric") }
        if (!value.isFinite()) fail("$key must be finite")
        return value
    }

    private fun JSONObject.optionalFiniteDouble(key: String): Double? {
        if (!has(key) || isNull(key)) return null
        val value = runCatching { getDouble(key) }.getOrElse { fail("$key must be numeric") }
        if (!value.isFinite()) fail("$key must be finite")
        return value
    }

    private fun JSONObject.requireEnum(key: String, allowed: Set<String>): String {
        val value = requireString(key)
        if (value !in allowed) fail("unsupported $key $value")
        return value
    }

    private fun fail(message: String): Nothing =
        throw ModelRigException("invalid control center status: $message")
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
