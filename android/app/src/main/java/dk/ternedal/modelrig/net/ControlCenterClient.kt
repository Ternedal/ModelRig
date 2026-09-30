package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
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
        const val PRIVACY_SCHEMA = "kaliv-control-center-privacy/v1"
        const val DATA_SHARING_SCHEMA = "kaliv-data-sharing-policy/v1"
        const val VISION_SCHEMA = "kaliv-control-center-vision/v1"
        const val VISION_CONTROL_SCHEMA = "kaliv-control-center-vision-control/v1"
        private val OVERALL_STATES = setOf("healthy", "attention", "unavailable", "unknown")
        private val COMPONENT_STATES = setOf("healthy", "unavailable", "unknown", "stale", "disabled")
        private val ROUTING_STATES = setOf("healthy", "fallback", "unknown", "stale", "disabled")
        private val REQUIRED_COMPONENTS = setOf("backend", "worker", "models", "agent3")
        private val PRIVACY_EVIDENCE_STATES = setOf("ready", "unknown")
        private val COMMON_DATA_SHARING_STATES = setOf("dormant", "unknown")
        private val SCOPED_PERMISSION_STATES = setOf("unavailable", "unknown")
        private val PRIVATE_EGRESS_RULES = setOf(
            "allowed_legacy_mode",
            "blocked_requires_explicit_consent",
        )
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

    fun setVisionEnabled(
        sourceId: String,
        enabled: Boolean,
        expectedStateRevision: Int,
    ): ControlCenterVisionControlReceipt {
        val normalizedSourceId = sourceId.trim()
        if (normalizedSourceId.isBlank() || normalizedSourceId.length > 128) {
            throw ModelRigException("invalid VisionRig source id")
        }
        if (expectedStateRevision < 0) {
            throw ModelRigException("invalid VisionRig state revision")
        }
        val url = okhttp3.HttpUrl.get(base).newBuilder()
            .addPathSegments("api/v1/control-center/vision")
            .addPathSegment(normalizedSourceId)
            .addPathSegment("enabled")
            .build()
        val payload = JSONObject()
            .put("enabled", enabled)
            .put("expected_state_revision", expectedStateRevision)
            .toString()
            .toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer " + token)
            .post(payload)
            .build()
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val json = JSONObject(body)
                    json.optString("detail").ifBlank { json.optString("error") }
                }.getOrDefault("").ifBlank { body }.take(500)
                throw ModelRigException(
                    "VisionRig sensor control failed (" + response.code + "): " + detail,
                )
            }
            if (body.isBlank()) {
                throw ModelRigException("VisionRig sensor control returned an empty body")
            }
            return parseVisionControl(JSONObject(body), normalizedSourceId, enabled)
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
        val privacy = root.optJSONObject("privacy")?.let(::parsePrivacy)
            ?: ControlCenterPrivacy.unreported()
        val vision = root.optJSONObject("vision")?.let(::parseVision)
            ?: ControlCenterVision.unreported()

        return ControlCenterStatus(
            schema = schema,
            generatedAt = generatedAt,
            freshnessSeconds = freshnessSeconds,
            overall = overall,
            green = green,
            components = components.toMap(),
            routing = routing,
            requiredFailures = requiredFailures,
            privacy = privacy,
            vision = vision,
        )
    }

    private fun parseVision(value: JSONObject): ControlCenterVision {
        val schema = value.requireStrictString("schema")
        if (schema != VISION_SCHEMA) fail("unsupported Vision schema " + schema)
        val available = value.requireBoolean("available")
        val productionActivation = value.requireBoolean("production_activation")
        if (productionActivation) fail("Vision production activation must be false")

        val revision = if (value.has("sensor_state_revision") && !value.isNull("sensor_state_revision")) {
            val parsed = runCatching { value.getInt("sensor_state_revision") }
                .getOrElse { fail("Vision sensor_state_revision must be integer") }
            if (parsed < 0) fail("Vision sensor_state_revision must be non-negative")
            parsed
        } else {
            null
        }
        if (available && revision == null) fail("available Vision projection lacks state revision")

        val consistency = value.optionalStrictString("consistency") ?: "unknown"
        if (consistency !in setOf("synced", "registry_ahead", "journal_ahead", "unknown")) {
            fail("unsupported Vision consistency " + consistency)
        }

        val sensorsJson = value.optJSONArray("sensors")
            ?: fail("Vision sensors must be an array")
        if (sensorsJson.length() > 128) fail("Vision sensors exceed bound")
        val sensors = (0 until sensorsJson.length()).map { index ->
            parseVisionSensor(
                sensorsJson.optJSONObject(index)
                    ?: fail("Vision sensor must be an object"),
            )
        }
        val returned = value.requireNonNegativeInt("sensors_returned")
        if (returned != sensors.size) fail("Vision sensors_returned mismatch")

        return ControlCenterVision(
            schema = schema,
            available = available,
            reason = value.optionalStrictString("reason"),
            sensorStateRevision = revision,
            consistency = consistency,
            total = value.requireNonNegativeInt("total"),
            sensorsTruncated = value.requireBoolean("sensors_truncated"),
            attentionTotal = value.requireNonNegativeInt("attention_total"),
            sensors = sensors,
            productionActivation = productionActivation,
        )
    }

    private fun parseVisionSensor(value: JSONObject): ControlCenterVisionSensor {
        val sourceId = value.requireStrictString("source_id")
        if (sourceId.length > 128) fail("Vision source id exceeds bound")
        val lifecycle = value.requireStrictString("lifecycle")
        if (lifecycle !in setOf("active", "retired")) fail("unsupported Vision lifecycle " + lifecycle)
        val presence = value.requireStrictString("presence")
        if (presence !in setOf("online", "stale", "offline", "unknown")) {
            fail("unsupported Vision presence " + presence)
        }
        val convergence = value.requireStrictString("convergence")
        if (convergence !in setOf("converged", "pending", "unknown")) {
            fail("unsupported Vision convergence " + convergence)
        }
        return ControlCenterVisionSensor(
            sourceId = sourceId,
            displayName = value.optionalStrictString("display_name"),
            sourceType = value.requireStrictString("source_type"),
            device = value.optionalStrictString("device"),
            lifecycle = lifecycle,
            presence = presence,
            desiredEnabled = value.requireBoolean("desired_enabled"),
            effectiveCaptureActive = value.optionalBoolean("effective_capture_active"),
            convergence = convergence,
            desiredRevision = value.requireNonNegativeInt("desired_revision"),
            appliedRevision = value.optionalNonNegativeInt("applied_revision"),
            pendingSeconds = value.optionalFiniteDouble("pending_seconds"),
            transportStatus = value.requireStrictString("transport_status"),
            capabilityRefreshStatus = value.requireStrictString("capability_refresh_status"),
            lastSeenUtc = value.optionalStrictString("last_seen_utc"),
        )
    }

    private fun parseVisionControl(
        value: JSONObject,
        expectedSourceId: String,
        expectedEnabled: Boolean,
    ): ControlCenterVisionControlReceipt {
        val schema = value.requireStrictString("schema")
        if (schema != VISION_CONTROL_SCHEMA) {
            throw ModelRigException("invalid VisionRig control receipt: unsupported schema " + schema)
        }
        val sourceId = value.requireStrictString("source_id")
        if (sourceId != expectedSourceId) {
            throw ModelRigException("invalid VisionRig control receipt: source mismatch")
        }
        val enabled = value.requireBoolean("enabled")
        if (enabled != expectedEnabled) {
            throw ModelRigException("invalid VisionRig control receipt: enabled mismatch")
        }
        val productionActivation = value.requireBoolean("production_activation")
        if (productionActivation) {
            throw ModelRigException("invalid VisionRig control receipt: production activation")
        }
        return ControlCenterVisionControlReceipt(
            schema = schema,
            sourceId = sourceId,
            enabled = enabled,
            sensorStateRevision = value.requireNonNegativeInt("sensor_state_revision"),
            desiredRevision = value.requireNonNegativeInt("desired_revision"),
            productionActivation = productionActivation,
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

    private fun parsePrivacy(value: JSONObject): ControlCenterPrivacy {
        val schema = value.requireStrictString("schema")
        if (schema != PRIVACY_SCHEMA) fail("unsupported privacy schema $schema")
        val evidenceState = value.requireStrictEnum("evidence_state", PRIVACY_EVIDENCE_STATES)
        val productionActivation = value.requireBoolean("production_activation")
        if (productionActivation) fail("privacy production activation must be false")

        val common = parseCommonDataSharing(value.requireObject("common_data_sharing"))
        val scoped = parseScopedPermissions(value.requireObject("scoped_permissions"))
        val egress = if (value.has("tool_result_egress") && !value.isNull("tool_result_egress")) {
            parseToolResultEgress(value.requireObject("tool_result_egress"))
        } else {
            null
        }

        if (evidenceState == "ready" && egress == null) {
            fail("ready privacy lacks ToolGate egress evidence")
        }
        if (evidenceState == "unknown" && scoped.revocationSupported) {
            fail("unknown privacy cannot grant revoke authority")
        }

        return ControlCenterPrivacy(
            schema = schema,
            evidenceState = evidenceState,
            reason = value.optionalStrictString("reason"),
            toolResultEgress = egress,
            commonDataSharing = common,
            scopedPermissions = scoped,
            productionActivation = productionActivation,
        )
    }

    private fun parseToolResultEgress(value: JSONObject): ControlCenterToolResultEgress {
        val source = value.requireStrictString("source")
        if (source != "toolgate") fail("unsupported privacy egress source $source")
        val gateEnabled = value.requireBoolean("private_gate_enabled")
        val rules = value.requireObject("rules")
        val publicRule = rules.requireStrictString("public")
        val operationalRule = rules.requireStrictString("operational")
        val privateRule = rules.requireStrictEnum("private", PRIVATE_EGRESS_RULES)
        val secretRule = rules.requireStrictString("secret")
        if (publicRule != "allowed") fail("public egress rule must be allowed")
        if (operationalRule != "allowed") fail("operational egress rule must be allowed")
        if (secretRule != "forbidden") fail("secret egress rule must be forbidden")
        val expectedPrivate = if (gateEnabled) {
            "blocked_requires_explicit_consent"
        } else {
            "allowed_legacy_mode"
        }
        if (privateRule != expectedPrivate) fail("private gate/rule contradiction")
        return ControlCenterToolResultEgress(
            privateGateEnabled = gateEnabled,
            publicRule = publicRule,
            operationalRule = operationalRule,
            privateRule = privateRule,
            secretRule = secretRule,
        )
    }

    private fun parseCommonDataSharing(value: JSONObject): ControlCenterCommonDataSharing {
        val state = value.requireStrictEnum("state", COMMON_DATA_SHARING_STATES)
        val runtimeIntegrated = value.requireBoolean("runtime_integrated")
        if (state == "dormant") {
            val schema = value.requireStrictString("schema")
            if (schema != DATA_SHARING_SCHEMA) fail("unsupported data-sharing schema $schema")
            if (runtimeIntegrated) fail("dormant data-sharing cannot be runtime integrated")
        }
        return ControlCenterCommonDataSharing(
            state = state,
            runtimeIntegrated = runtimeIntegrated,
            reason = value.optionalStrictString("reason"),
        )
    }

    private fun parseScopedPermissions(value: JSONObject): ControlCenterScopedPermissions {
        val state = value.requireStrictEnum("state", SCOPED_PERMISSION_STATES)
        val revocationSupported = value.requireBoolean("revocation_supported")
        if (revocationSupported) fail("scoped permission revocation has no active authority")
        if (value.has("count") && !value.isNull("count")) {
            fail("scoped permission count must be null while authority is unavailable")
        }
        return ControlCenterScopedPermissions(
            state = state,
            revocationSupported = revocationSupported,
            reason = value.optionalStrictString("reason"),
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

    private fun JSONObject.requireStrictString(key: String): String {
        if (!has(key) || isNull(key) || get(key) !is String) fail("$key must be a string")
        return getString(key).trim().takeIf { it.isNotEmpty() } ?: fail("blank $key")
    }

    private fun JSONObject.optionalString(key: String): String? {
        if (!has(key) || isNull(key)) return null
        return optString(key, "").trim().takeUnless { it.isBlank() }
    }

    private fun JSONObject.optionalStrictString(key: String): String? {
        if (!has(key) || isNull(key)) return null
        if (get(key) !is String) fail("$key must be a string or null")
        return getString(key).trim().takeUnless { it.isBlank() }
    }

    private fun JSONObject.requireBoolean(key: String): Boolean {
        if (!has(key) || isNull(key) || get(key) !is Boolean) fail("$key must be boolean")
        return getBoolean(key)
    }

    private fun JSONObject.optionalBoolean(key: String): Boolean? {
        if (!has(key) || isNull(key)) return null
        if (get(key) !is Boolean) fail(key + " must be boolean or null")
        return getBoolean(key)
    }

    private fun JSONObject.requireNonNegativeInt(key: String): Int {
        if (!has(key) || isNull(key)) fail("missing " + key)
        val value = runCatching { getInt(key) }.getOrElse { fail(key + " must be integer") }
        if (value < 0) fail(key + " must be non-negative")
        return value
    }

    private fun JSONObject.optionalNonNegativeInt(key: String): Int? {
        if (!has(key) || isNull(key)) return null
        val value = runCatching { getInt(key) }.getOrElse { fail(key + " must be integer or null") }
        if (value < 0) fail(key + " must be non-negative")
        return value
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

    private fun JSONObject.requireStrictEnum(key: String, allowed: Set<String>): String {
        val value = requireStrictString(key)
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
    val privacy: ControlCenterPrivacy,
    val vision: ControlCenterVision,
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

data class ControlCenterVision(
    val schema: String?,
    val available: Boolean,
    val reason: String?,
    val sensorStateRevision: Int?,
    val consistency: String,
    val total: Int,
    val sensorsTruncated: Boolean,
    val attentionTotal: Int,
    val sensors: List<ControlCenterVisionSensor>,
    val productionActivation: Boolean,
) {
    companion object {
        fun unreported() = ControlCenterVision(
            schema = null,
            available = false,
            reason = "vision_not_reported",
            sensorStateRevision = null,
            consistency = "unknown",
            total = 0,
            sensorsTruncated = false,
            attentionTotal = 0,
            sensors = emptyList(),
            productionActivation = false,
        )
    }
}

data class ControlCenterVisionSensor(
    val sourceId: String,
    val displayName: String?,
    val sourceType: String,
    val device: String?,
    val lifecycle: String,
    val presence: String,
    val desiredEnabled: Boolean,
    val effectiveCaptureActive: Boolean?,
    val convergence: String,
    val desiredRevision: Int,
    val appliedRevision: Int?,
    val pendingSeconds: Double?,
    val transportStatus: String,
    val capabilityRefreshStatus: String,
    val lastSeenUtc: String?,
)

data class ControlCenterVisionControlReceipt(
    val schema: String,
    val sourceId: String,
    val enabled: Boolean,
    val sensorStateRevision: Int,
    val desiredRevision: Int,
    val productionActivation: Boolean,
)

data class ControlCenterPrivacy(
    val schema: String?,
    val evidenceState: String,
    val reason: String?,
    val toolResultEgress: ControlCenterToolResultEgress?,
    val commonDataSharing: ControlCenterCommonDataSharing,
    val scopedPermissions: ControlCenterScopedPermissions,
    val productionActivation: Boolean,
) {
    companion object {
        fun unreported() = ControlCenterPrivacy(
            schema = null,
            evidenceState = "unknown",
            reason = "privacy_not_reported",
            toolResultEgress = null,
            commonDataSharing = ControlCenterCommonDataSharing(
                state = "unknown",
                runtimeIntegrated = false,
                reason = "privacy_not_reported",
            ),
            scopedPermissions = ControlCenterScopedPermissions(
                state = "unknown",
                revocationSupported = false,
                reason = "privacy_not_reported",
            ),
            productionActivation = false,
        )
    }
}

data class ControlCenterToolResultEgress(
    val privateGateEnabled: Boolean,
    val publicRule: String,
    val operationalRule: String,
    val privateRule: String,
    val secretRule: String,
)

data class ControlCenterCommonDataSharing(
    val state: String,
    val runtimeIntegrated: Boolean,
    val reason: String?,
)

data class ControlCenterScopedPermissions(
    val state: String,
    val revocationSupported: Boolean,
    val reason: String?,
)
