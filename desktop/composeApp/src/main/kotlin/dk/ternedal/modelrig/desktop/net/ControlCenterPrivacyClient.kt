package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

/**
 * Read-only desktop projection of the additive Control Center privacy object.
 *
 * Privacy is parsed from raw JSON primitives instead of data-class coercion so
 * quoted booleans or synthetic values cannot become trusted policy evidence.
 */
class ControlCenterPrivacyClient(baseUrl: String, private val bearer: String) {
    companion object {
        const val STATUS_SCHEMA = "kaliv-control-center-status/v1"
        const val PRIVACY_SCHEMA = "kaliv-control-center-privacy/v1"
        const val DATA_SHARING_SCHEMA = "kaliv-data-sharing-policy/v1"
        private val EVIDENCE_STATES = setOf("ready", "unknown")
        private val COMMON_STATES = setOf("dormant", "unknown")
        private val SCOPED_STATES = setOf("unavailable", "unknown")
        private val PRIVATE_RULES = setOf(
            "allowed_legacy_mode",
            "blocked_requires_explicit_consent",
        )
    }

    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = false; explicitNulls = true }
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun privacy(): ControlCenterPrivacy {
        val request = HttpRequest.newBuilder(
            URI.create(base + "/api/v1/control-center/status"),
        )
            .header("Accept", "application/json")
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(10))
            .GET()
            .build()
        val response = try {
            http.send(request, HttpResponse.BodyHandlers.ofString())
        } catch (exc: Exception) {
            throw ControlCenterException(
                "Control Center privacy failed: ${exc::class.simpleName}",
            )
        }
        if (response.statusCode() !in 200..299) {
            throw ControlCenterException(
                "Control Center privacy failed (${response.statusCode()}): " +
                    response.body().take(500),
            )
        }
        if (response.body().isBlank()) {
            throw ControlCenterException("Control Center privacy returned an empty body")
        }
        return parse(response.body())
    }

    internal fun parse(body: String): ControlCenterPrivacy {
        val root = try {
            json.parseToJsonElement(body) as? JsonObject
                ?: fail("root must be an object")
        } catch (exc: ControlCenterException) {
            throw exc
        } catch (exc: Exception) {
            fail("invalid payload: ${exc::class.simpleName}")
        }
        val statusSchema = root.requireString("schema", "status")
        if (statusSchema != STATUS_SCHEMA) fail("unsupported status schema $statusSchema")

        val privacyElement = root["privacy"] ?: return ControlCenterPrivacy.unreported()
        if (privacyElement === JsonNull) return ControlCenterPrivacy.unreported()
        val privacy = privacyElement as? JsonObject ?: fail("privacy must be an object or null")
        return parsePrivacy(privacy)
    }

    private fun parsePrivacy(value: JsonObject): ControlCenterPrivacy {
        val schema = value.requireString("schema", "privacy")
        if (schema != PRIVACY_SCHEMA) fail("unsupported privacy schema $schema")
        val evidenceState = value.requireEnum("evidence_state", EVIDENCE_STATES, "privacy")
        val productionActivation = value.requireBoolean("production_activation", "privacy")
        if (productionActivation) fail("privacy production activation must be false")

        val common = parseCommon(value.requireObject("common_data_sharing", "privacy"))
        val scoped = parseScoped(value.requireObject("scoped_permissions", "privacy"))
        val egressElement = value["tool_result_egress"]
        val egress = when {
            egressElement == null || egressElement === JsonNull -> null
            egressElement is JsonObject -> parseEgress(egressElement)
            else -> fail("privacy.tool_result_egress must be an object or null")
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
            reason = value.optionalString("reason", "privacy"),
            toolResultEgress = egress,
            commonDataSharing = common,
            scopedPermissions = scoped,
            productionActivation = productionActivation,
        )
    }

    private fun parseEgress(value: JsonObject): ControlCenterToolResultEgress {
        val source = value.requireString("source", "privacy.tool_result_egress")
        if (source != "toolgate") fail("unsupported privacy egress source $source")
        val gateEnabled = value.requireBoolean(
            "private_gate_enabled",
            "privacy.tool_result_egress",
        )
        val rules = value.requireObject("rules", "privacy.tool_result_egress")
        val publicRule = rules.requireString("public", "privacy.tool_result_egress.rules")
        val operationalRule = rules.requireString("operational", "privacy.tool_result_egress.rules")
        val privateRule = rules.requireEnum(
            "private",
            PRIVATE_RULES,
            "privacy.tool_result_egress.rules",
        )
        val secretRule = rules.requireString("secret", "privacy.tool_result_egress.rules")
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

    private fun parseCommon(value: JsonObject): ControlCenterCommonDataSharing {
        val state = value.requireEnum("state", COMMON_STATES, "privacy.common_data_sharing")
        val runtimeIntegrated = value.requireBoolean(
            "runtime_integrated",
            "privacy.common_data_sharing",
        )
        if (state == "dormant") {
            val schema = value.requireString("schema", "privacy.common_data_sharing")
            if (schema != DATA_SHARING_SCHEMA) fail("unsupported data-sharing schema $schema")
            if (runtimeIntegrated) fail("dormant data-sharing cannot be runtime integrated")
        }
        return ControlCenterCommonDataSharing(
            state = state,
            runtimeIntegrated = runtimeIntegrated,
            reason = value.optionalString("reason", "privacy.common_data_sharing"),
        )
    }

    private fun parseScoped(value: JsonObject): ControlCenterScopedPermissions {
        val state = value.requireEnum("state", SCOPED_STATES, "privacy.scoped_permissions")
        val revocationSupported = value.requireBoolean(
            "revocation_supported",
            "privacy.scoped_permissions",
        )
        if (revocationSupported) fail("scoped permission revocation has no active authority")
        val count: JsonElement? = value["count"]
        if (count != null && count !== JsonNull) {
            fail("scoped permission count must be null while authority is unavailable")
        }
        return ControlCenterScopedPermissions(
            state = state,
            revocationSupported = revocationSupported,
            reason = value.optionalString("reason", "privacy.scoped_permissions"),
        )
    }

    private fun JsonObject.requireObject(key: String, path: String): JsonObject =
        this[key] as? JsonObject ?: fail("$path.$key must be an object")

    private fun JsonObject.requireString(key: String, path: String): String {
        val value = this[key] as? JsonPrimitive ?: fail("$path.$key must be a string")
        if (!value.isString) fail("$path.$key must be a string")
        return value.content.trim().takeIf { it.isNotEmpty() }
            ?: fail("$path.$key must not be blank")
    }

    private fun JsonObject.optionalString(key: String, path: String): String? {
        val element = this[key] ?: return null
        if (element === JsonNull) return null
        val value = element as? JsonPrimitive ?: fail("$path.$key must be string or null")
        if (!value.isString) fail("$path.$key must be string or null")
        return value.content.trim().takeIf { it.isNotEmpty() }
    }

    private fun JsonObject.requireBoolean(key: String, path: String): Boolean {
        val value = this[key] as? JsonPrimitive ?: fail("$path.$key must be boolean")
        if (value.isString || value.content !in setOf("true", "false")) {
            fail("$path.$key must be boolean")
        }
        return value.content == "true"
    }

    private fun JsonObject.requireEnum(
        key: String,
        allowed: Set<String>,
        path: String,
    ): String {
        val value = requireString(key, path)
        if (value !in allowed) fail("unsupported $path.$key $value")
        return value
    }

    private fun fail(message: String): Nothing =
        throw ControlCenterException("Invalid Control Center privacy: $message")
}

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
