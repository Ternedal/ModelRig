package dk.ternedal.modelrig.net

import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

/**
 * Authenticated Android Control Center projection of the T-036 GitHub connector
 * authority. The client never talks to the loopback worker directly and never
 * accepts model-visible grant mutation. It consumes only the paired-device
 * backend routes introduced by the qualified T-036/T-044 proxy slice.
 */
class ControlCenterGitHubConnectorClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val jsonType = "application/json".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    fun snapshot(includeRevoked: Boolean = true, auditLimit: Int = 100): ControlCenterGitHubConnectorSnapshot {
        require(auditLimit in 1..500) { "auditLimit must be in 1..500" }
        val grants = parseGrants(
            get("/api/v1/github-connector/grants?include_revoked=$includeRevoked"),
        )
        val audit = parseAudit(
            get("/api/v1/github-connector/audit?limit=$auditLimit"),
        )
        return ControlCenterGitHubConnectorSnapshot(grants = grants, audit = audit)
    }

    fun revoke(grant: ControlCenterGitHubGrant): ControlCenterGitHubGrant {
        if (!grant.active) {
            throw ModelRigException("GitHub-tilladelsen er allerede tilbagekaldt")
        }
        val body = JSONObject()
            .put("expected_scope_sha256", grant.scopeSha256)
            .put("confirm_revoke", true)
        val root = post(
            "/api/v1/github-connector/grants/${seg(grant.grantId)}/revoke",
            body,
        )
        requireConnectorRoot(root, "revoke")
        val revoked = root.optJSONObject("grant")
            ?: fail("revoke.grant must be an object")
        val parsed = parseGrant(revoked, "revoke.grant")
        if (parsed.grantId != grant.grantId) fail("revoke returned a different grant id")
        if (parsed.scopeSha256 != grant.scopeSha256) fail("revoke returned a different scope digest")
        if (parsed.active) fail("revoke returned an active grant")
        return parsed
    }

    internal fun parseGrants(root: JSONObject): List<ControlCenterGitHubGrant> {
        requireConnectorRoot(root, "grants")
        val array = root.optJSONArray("grants") ?: fail("grants must be an array")
        return buildList {
            for (index in 0 until array.length()) {
                val item = array.optJSONObject(index) ?: fail("grants[$index] must be an object")
                add(parseGrant(item, "grants[$index]"))
            }
        }
    }

    internal fun parseAudit(root: JSONObject): List<ControlCenterGitHubAuditEntry> {
        requireConnectorRoot(root, "audit")
        val array = root.optJSONArray("entries") ?: fail("entries must be an array")
        return buildList {
            for (index in 0 until array.length()) {
                val item = array.optJSONObject(index) ?: fail("entries[$index] must be an object")
                add(parseAuditEntry(item, index))
            }
        }
    }

    private fun parseGrant(item: JSONObject, path: String): ControlCenterGitHubGrant {
        requireFalse(item, "production_activation", path)
        if (item.requireString("schema", path) != GRANT_SCHEMA) {
            fail("$path.schema is unsupported")
        }
        val grantId = item.requireString("grant_id", path)
        if (!Regex("^ghg_[0-9a-f]{32}$").matches(grantId)) fail("$path.grant_id has invalid format")
        val digest = item.requireString("scope_sha256", path)
        if (!Regex("^[0-9a-f]{64}$").matches(digest)) fail("$path.scope_sha256 must be lowercase SHA-256")
        val status = item.requireString("status", path)
        if (status !in setOf("active", "revoked")) fail("$path.status is unsupported")
        val scope = item.optJSONObject("scope") ?: fail("$path.scope must be an object")
        requireFalse(scope, "production_activation", "$path.scope")
        if (scope.requireString("schema", "$path.scope") != SCOPE_SCHEMA) {
            fail("$path.scope.schema is unsupported")
        }
        val repositories = scope.requireStringArray("repositories", "$path.scope", 1..25)
        val operations = scope.requireStringArray("operations", "$path.scope", 1..4)
        if (repositories.size != repositories.toSet().size) fail("$path.scope.repositories contains duplicates")
        if (operations.size != operations.toSet().size) fail("$path.scope.operations contains duplicates")
        if (operations.any { it !in GITHUB_READ_OPERATIONS }) fail("$path.scope.operations contains unsupported operation")
        val revokedAt = item.optionalString("revoked_at", path)
        val revokedBy = item.optionalString("revoked_by", path)
        if (status == "active" && (revokedAt != null || revokedBy != null)) {
            fail("$path active grant contains revocation evidence")
        }
        if (status == "revoked" && (revokedAt == null || revokedBy == null)) {
            fail("$path revoked grant lacks revocation evidence")
        }
        return ControlCenterGitHubGrant(
            grantId = grantId,
            account = scope.requireString("account", "$path.scope"),
            repositories = repositories,
            operations = operations,
            scopeSha256 = digest,
            createdAt = item.requireString("created_at", path),
            createdBy = item.requireString("created_by", path),
            status = status,
            revokedAt = revokedAt,
            revokedBy = revokedBy,
        )
    }

    private fun parseAuditEntry(item: JSONObject, index: Int): ControlCenterGitHubAuditEntry {
        val path = "entries[$index]"
        val connector = item.requireString("connector", path)
        if (connector != "github") fail("$path.connector must be github")
        val operation = item.requireString("operation", path)
        if (operation !in GITHUB_READ_OPERATIONS) fail("$path.operation is unsupported")
        val outcome = item.requireString("outcome", path)
        if (outcome !in setOf("executed", "blocked", "error")) fail("$path.outcome is unsupported")
        val duration = item.requireNonNegativeLong("duration_ms", path)
        val scope = item.optionalString("scope_sha256", path)
        if (scope != null && !Regex("^[0-9a-f]{64}$").matches(scope)) {
            fail("$path.scope_sha256 must be lowercase SHA-256 or null")
        }
        val grantId = item.optionalString("grant_id", path)
        if (grantId != null && !Regex("^ghg_[0-9a-f]{32}$").matches(grantId)) {
            fail("$path.grant_id has invalid format")
        }
        val detail = item.requireString("detail", path)
        if (detail.length > 120) fail("$path.detail exceeds 120 characters")
        return ControlCenterGitHubAuditEntry(
            timestamp = item.requireString("ts", path),
            account = item.optionalString("account", path),
            repository = item.requireString("repository", path),
            operation = operation,
            objectId = item.optionalString("object_id", path),
            outcome = outcome,
            grantId = grantId,
            scopeSha256 = scope,
            revision = item.optionalString("revision", path),
            durationMs = duration,
            detail = detail,
        )
    }

    private fun requireConnectorRoot(root: JSONObject, label: String) {
        val connector = root.requireString("connector", label)
        if (connector != "github") fail("$label.connector must be github")
        requireFalse(root, "production_activation", label)
    }

    private fun get(path: String): JSONObject = execute(
        Request.Builder().url(base + path).get(),
        "GitHub connector GET $path",
    )

    private fun post(path: String, payload: JSONObject): JSONObject = execute(
        Request.Builder()
            .url(base + path)
            .post(payload.toString().toRequestBody(jsonType)),
        "GitHub connector POST $path",
    )

    private fun execute(builder: Request.Builder, label: String): JSONObject {
        builder.header("Authorization", "Bearer $token")
        http.newCall(builder.build()).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val upstream = runCatching {
                    val json = JSONObject(body)
                    json.optString("detail").ifBlank { json.optString("error") }
                }.getOrDefault("").ifBlank { body }.take(500)
                val detail = if (
                    response.code == 404 && label.startsWith("GitHub connector GET ")
                ) {
                    "GitHub connector-piloten er ikke eksponeret på denne rig."
                } else {
                    upstream
                }
                throw ModelRigException("$label failed (${response.code}): $detail")
            }
            if (body.isBlank()) throw ModelRigException("$label returned an empty body")
            return runCatching { JSONObject(body) }.getOrElse {
                throw ModelRigException("$label returned invalid JSON")
            }
        }
    }

    private fun JSONObject.requireString(key: String, path: String): String {
        if (!has(key) || isNull(key) || get(key) !is String) fail("$path.$key must be a string")
        return getString(key).trim().takeIf { it.isNotEmpty() }
            ?: fail("$path.$key must not be blank")
    }

    private fun JSONObject.optionalString(key: String, path: String): String? {
        if (!has(key) || isNull(key)) return null
        if (get(key) !is String) fail("$path.$key must be string or null")
        return getString(key).trim().takeIf { it.isNotEmpty() }
    }

    private fun JSONObject.requireStringArray(key: String, path: String, size: IntRange): List<String> {
        if (!has(key) || isNull(key) || get(key) !is JSONArray) fail("$path.$key must be an array")
        val array = getJSONArray(key)
        if (array.length() !in size) fail("$path.$key has invalid size")
        return buildList {
            for (index in 0 until array.length()) {
                val raw = array.get(index)
                if (raw !is String || raw.trim().isEmpty()) fail("$path.$key[$index] must be a non-blank string")
                add(raw.trim())
            }
        }
    }

    private fun JSONObject.requireNonNegativeLong(key: String, path: String): Long {
        if (!has(key) || isNull(key)) fail("$path.$key must be an integer")
        val value = when (val raw = get(key)) {
            is Int -> raw.toLong()
            is Long -> raw
            else -> fail("$path.$key must be an integer")
        }
        if (value < 0) fail("$path.$key must be non-negative")
        return value
    }

    private fun requireFalse(root: JSONObject, key: String, path: String) {
        if (!root.has(key) || root.isNull(key) || root.get(key) !is Boolean || root.getBoolean(key)) {
            fail("$path.$key must be false")
        }
    }

    private fun seg(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8.toString()).replace("+", "%20")

    private fun fail(message: String): Nothing =
        throw ModelRigException("invalid GitHub connector Control Center payload: $message")

    private companion object {
        const val GRANT_SCHEMA = "kaliv-github-connector-grant/v1"
        const val SCOPE_SCHEMA = "kaliv-github-connector-scope/v1"
        val GITHUB_READ_OPERATIONS = setOf("repository", "issue", "pull_request", "workflow_run")
    }
}

data class ControlCenterGitHubConnectorSnapshot(
    val grants: List<ControlCenterGitHubGrant>,
    val audit: List<ControlCenterGitHubAuditEntry>,
) {
    val activeGrants: List<ControlCenterGitHubGrant> get() = grants.filter { it.active }

    fun filteredAudit(
        repository: String? = null,
        operation: String? = null,
        outcome: String? = null,
    ): List<ControlCenterGitHubAuditEntry> {
        val repoNeedle = repository?.trim()?.takeIf { it.isNotEmpty() }
        val operationNeedle = operation?.trim()?.takeIf { it.isNotEmpty() }
        val outcomeNeedle = outcome?.trim()?.takeIf { it.isNotEmpty() }
        return audit.filter { entry ->
            (repoNeedle == null || entry.repository.contains(repoNeedle, ignoreCase = true)) &&
                (operationNeedle == null || entry.operation == operationNeedle) &&
                (outcomeNeedle == null || entry.outcome == outcomeNeedle)
        }
    }
}

data class ControlCenterGitHubGrant(
    val grantId: String,
    val account: String,
    val repositories: List<String>,
    val operations: List<String>,
    val scopeSha256: String,
    val createdAt: String,
    val createdBy: String,
    val status: String,
    val revokedAt: String?,
    val revokedBy: String?,
) {
    val active: Boolean get() = status == "active"
}

data class ControlCenterGitHubAuditEntry(
    val timestamp: String,
    val account: String?,
    val repository: String,
    val operation: String,
    val objectId: String?,
    val outcome: String,
    val grantId: String?,
    val scopeSha256: String?,
    val revision: String?,
    val durationMs: Long,
    val detail: String,
)
