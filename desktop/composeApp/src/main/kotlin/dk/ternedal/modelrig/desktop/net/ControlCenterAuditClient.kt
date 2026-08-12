package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
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
 * Read-only, privacy-minimised desktop projection of the existing ToolGate audit route.
 *
 * The raw endpoint also carries tool arguments and a result summary. Those fields are
 * deliberately never copied into the Control Center domain model.
 */
class ControlCenterAuditClient(baseUrl: String, private val bearer: String) {
    companion object {
        private val INTEGER_TEXT = Regex("^-?(0|[1-9][0-9]*)$")
    }

    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = false; explicitNulls = true }
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun snapshot(): ControlCenterAuditSnapshot {
        val request = HttpRequest.newBuilder(URI.create(base + "/api/v1/tools/audit?limit=100"))
            .header("Accept", "application/json")
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(10))
            .GET()
            .build()
        val response = try {
            http.send(request, HttpResponse.BodyHandlers.ofString())
        } catch (exc: Exception) {
            throw ControlCenterException(
                "Control Center audit failed: ${exc::class.simpleName}",
            )
        }
        if (response.statusCode() !in 200..299) {
            throw ControlCenterException(
                "Control Center audit failed (${response.statusCode()}): " +
                    response.body().take(500),
            )
        }
        if (response.body().isBlank()) {
            throw ControlCenterException("Control Center audit returned an empty body")
        }
        return parse(response.body())
    }

    internal fun parse(body: String): ControlCenterAuditSnapshot {
        val root = try {
            json.parseToJsonElement(body) as? JsonObject
                ?: fail("root must be an object")
        } catch (exc: ControlCenterException) {
            throw exc
        } catch (exc: Exception) {
            fail("invalid payload: ${exc::class.simpleName}")
        }
        val entriesElement = root["entries"] ?: fail("entries must be an array")
        val array = entriesElement as? JsonArray ?: fail("entries must be an array")
        val entries = array.mapIndexed { index, element ->
            val item = element as? JsonObject ?: fail("entries[$index] must be an object")
            parseEntry(item, index)
        }
        return ControlCenterAuditSnapshot(
            entries = entries,
            connectorEvidence = ControlCenterAuditEvidence(
                state = "unavailable",
                reason = "tool_audit_does_not_record_connector_id",
            ),
        )
    }

    private fun parseEntry(item: JsonObject, index: Int): ControlCenterAuditEntry {
        val timestamp = item.requireString("ts", index)
        val tool = item.requireString("tool", index)
        return ControlCenterAuditEntry(
            timestamp = timestamp,
            taskRef = item.optionalNullableString("conversation_id", index),
            capabilityId = "tool:$tool",
            tool = tool,
            connectorId = null,
            approvalId = item.optionalNullableString("confirmation_id", index),
            risk = item.optionalNullableString("risk", index),
            outcome = item.requireString("outcome", index),
            origin = item.requireString("origin", index),
            durationMs = item.optionalNonNegativeLong("duration_ms", index),
        )
    }

    private fun JsonObject.requireString(key: String, index: Int): String {
        val value = this[key] ?: fail("entries[$index].$key must be a string")
        val primitive = value as? JsonPrimitive
            ?: fail("entries[$index].$key must be a string")
        if (!primitive.isString) fail("entries[$index].$key must be a string")
        return primitive.content.trim().takeIf { it.isNotEmpty() }
            ?: fail("entries[$index].$key must not be blank")
    }

    private fun JsonObject.optionalNullableString(key: String, index: Int): String? {
        val value: JsonElement = this[key] ?: return null
        if (value === JsonNull) return null
        val primitive = value as? JsonPrimitive
            ?: fail("entries[$index].$key must be string or null")
        if (!primitive.isString) fail("entries[$index].$key must be string or null")
        return primitive.content.trim().takeIf { it.isNotEmpty() }
    }

    private fun JsonObject.optionalNonNegativeLong(key: String, index: Int): Long? {
        val value: JsonElement = this[key] ?: return null
        if (value === JsonNull) return null
        val primitive = value as? JsonPrimitive
            ?: fail("entries[$index].$key must be an integer or null")
        if (primitive.isString || !INTEGER_TEXT.matches(primitive.content)) {
            fail("entries[$index].$key must be an integer or null")
        }
        val parsed = primitive.content.toLongOrNull()
            ?: fail("entries[$index].$key must be an integer or null")
        if (parsed < 0) fail("entries[$index].$key must be non-negative")
        return parsed
    }

    private fun fail(message: String): Nothing =
        throw ControlCenterException("Invalid Control Center audit: $message")
}

data class ControlCenterAuditSnapshot(
    val entries: List<ControlCenterAuditEntry>,
    val connectorEvidence: ControlCenterAuditEvidence,
) {
    fun filtered(filter: ControlCenterAuditFilter): List<ControlCenterAuditEntry> {
        if (!filter.connector.isNullOrBlank()) return emptyList()
        val task = filter.task?.trim()?.takeIf { it.isNotEmpty() }
        val capability = filter.capability?.trim()?.takeIf { it.isNotEmpty() }
        val approval = filter.approval?.trim()?.takeIf { it.isNotEmpty() }
        return entries.filter { entry ->
            (task == null || entry.taskRef?.contains(task, ignoreCase = true) == true) &&
                (capability == null || entry.capabilityId.contains(capability, ignoreCase = true)) &&
                (approval == null || entry.approvalId?.contains(approval, ignoreCase = true) == true)
        }
    }
}

data class ControlCenterAuditFilter(
    val task: String? = null,
    val capability: String? = null,
    val connector: String? = null,
    val approval: String? = null,
)

data class ControlCenterAuditEvidence(
    val state: String,
    val reason: String?,
)

data class ControlCenterAuditEntry(
    val timestamp: String,
    val taskRef: String?,
    val capabilityId: String,
    val tool: String,
    val connectorId: String?,
    val approvalId: String?,
    val risk: String?,
    val outcome: String,
    val origin: String,
    val durationMs: Long?,
)
