package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Read-only, privacy-minimised view of the existing ToolGate audit route.
 *
 * `/api/v1/tools/audit` predates T-044 and includes `args_json` and a result
 * summary. Control Center deliberately models neither field: task/capability/
 * approval/outcome evidence is enough for operator audit, and copying payload
 * content into another UI would widen exposure of potentially private data.
 *
 * The current durable audit schema has no connector identifier. Connector is
 * therefore explicit missing evidence, never inferred from `origin`.
 */
class ControlCenterAuditClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    fun snapshot(): ControlCenterAuditSnapshot {
        val request = Request.Builder()
            .url(base + "/api/v1/tools/audit?limit=100")
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
                throw ModelRigException("control center audit failed (${response.code}): $detail")
            }
            if (body.isBlank()) {
                throw ModelRigException("control center audit returned an empty body")
            }
            return parse(JSONObject(body))
        }
    }

    internal fun parse(root: JSONObject): ControlCenterAuditSnapshot {
        val array = root.optJSONArray("entries") ?: fail("entries must be an array")
        val entries = buildList {
            for (index in 0 until array.length()) {
                val item = array.optJSONObject(index) ?: fail("entries[$index] must be an object")
                add(parseEntry(item, index))
            }
        }
        return ControlCenterAuditSnapshot(
            entries = entries,
            connectorEvidence = ControlCenterAuditEvidence(
                state = "unavailable",
                reason = "tool_audit_does_not_record_connector_id",
            ),
        )
    }

    private fun parseEntry(item: JSONObject, index: Int): ControlCenterAuditEntry {
        val timestamp = item.requireString("ts", index)
        val tool = item.requireString("tool", index)
        val outcome = item.requireString("outcome", index)
        val origin = item.requireString("origin", index)
        val durationMs = item.optionalNonNegativeLong("duration_ms", index)

        return ControlCenterAuditEntry(
            timestamp = timestamp,
            taskRef = item.optionalNullableString("conversation_id", index),
            capabilityId = "tool:$tool",
            tool = tool,
            connectorId = null,
            approvalId = item.optionalNullableString("confirmation_id", index),
            risk = item.optionalNullableString("risk", index),
            outcome = outcome,
            origin = origin,
            durationMs = durationMs,
        )
    }

    private fun JSONObject.requireString(key: String, index: Int): String {
        if (!has(key) || isNull(key) || get(key) !is String) {
            fail("entries[$index].$key must be a string")
        }
        return getString(key).trim().takeIf { it.isNotEmpty() }
            ?: fail("entries[$index].$key must not be blank")
    }

    private fun JSONObject.optionalNullableString(key: String, index: Int): String? {
        if (!has(key) || isNull(key)) return null
        if (get(key) !is String) fail("entries[$index].$key must be string or null")
        return getString(key).trim().takeIf { it.isNotEmpty() }
    }

    private fun JSONObject.optionalNonNegativeLong(key: String, index: Int): Long? {
        if (!has(key) || isNull(key)) return null
        val value = when (val raw = get(key)) {
            is Int -> raw.toLong()
            is Long -> raw
            else -> fail("entries[$index].$key must be an integer or null")
        }
        if (value < 0) fail("entries[$index].$key must be non-negative")
        return value
    }

    private fun fail(message: String): Nothing =
        throw ModelRigException("invalid control center audit: $message")
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
