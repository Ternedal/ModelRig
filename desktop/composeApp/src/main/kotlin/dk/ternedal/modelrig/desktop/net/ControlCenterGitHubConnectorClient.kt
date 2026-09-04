package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.charset.StandardCharsets
import java.time.Duration

/**
 * Authenticated desktop Control Center projection of the T-036 GitHub connector
 * authority. All calls stay behind the paired-device Go backend; the desktop app
 * never calls the loopback worker or a GitHub credential path directly.
 */
class ControlCenterGitHubConnectorClient(baseUrl: String, private val bearer: String) {
    companion object {
        private const val GRANT_SCHEMA = "kaliv-github-connector-grant/v1"
        private const val SCOPE_SCHEMA = "kaliv-github-connector-scope/v1"
        private val GRANT_ID = Regex("^ghg_[0-9a-f]{32}$")
        private val SHA256 = Regex("^[0-9a-f]{64}$")
        private val INTEGER_TEXT = Regex("^(0|[1-9][0-9]*)$")
        private val READ_OPERATIONS = setOf("repository", "issue", "pull_request", "workflow_run")
        private val OUTCOMES = setOf("executed", "blocked", "error")
    }

    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = true }
    private val http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun snapshot(includeRevoked: Boolean = true, auditLimit: Int = 100): DesktopGitHubConnectorSnapshot {
        require(auditLimit in 1..500) { "auditLimit must be in 1..500" }
        val grants = parseGrants(
            get("/api/v1/github-connector/grants?include_revoked=$includeRevoked", "grants"),
        )
        val audit = parseAudit(
            get("/api/v1/github-connector/audit?limit=$auditLimit", "audit"),
        )
        return DesktopGitHubConnectorSnapshot(grants = grants, audit = audit)
    }

    fun revoke(grant: DesktopGitHubGrant): DesktopGitHubGrant {
        if (!grant.active) throw ControlCenterException("GitHub-tilladelsen er allerede tilbagekaldt")
        val payload = "{\"expected_scope_sha256\":\"${grant.scopeSha256}\",\"confirm_revoke\":true}"
        val root = parseObject(
            post(
                "/api/v1/github-connector/grants/${seg(grant.grantId)}/revoke",
                payload,
                "revoke",
            ),
            "revoke",
        )
        requireConnectorRoot(root, "revoke")
        val item = root["grant"] as? JsonObject ?: fail("revoke.grant must be an object")
        val parsed = parseGrant(item, "revoke.grant")
        if (parsed.grantId != grant.grantId) fail("revoke returned a different grant id")
        if (parsed.scopeSha256 != grant.scopeSha256) fail("revoke returned a different scope digest")
        if (parsed.active) fail("revoke returned an active grant")
        return parsed
    }

    internal fun parseGrants(body: String): List<DesktopGitHubGrant> {
        val root = parseObject(body, "grants")
        requireConnectorRoot(root, "grants")
        val array = root["grants"] as? JsonArray ?: fail("grants must be an array")
        val parsed = array.mapIndexed { index, element ->
            val item = element as? JsonObject ?: fail("grants[$index] must be an object")
            parseGrant(item, "grants[$index]")
        }
        val ids = parsed.map { it.grantId }
        if (ids.size != ids.toSet().size) fail("duplicate grant ids")
        return parsed
    }

    internal fun parseAudit(body: String): List<DesktopGitHubAuditEntry> {
        val root = parseObject(body, "audit")
        requireConnectorRoot(root, "audit")
        val array = root["entries"] as? JsonArray ?: fail("entries must be an array")
        return array.mapIndexed { index, element ->
            val item = element as? JsonObject ?: fail("entries[$index] must be an object")
            parseAuditEntry(item, index)
        }
    }

    private fun parseGrant(item: JsonObject, path: String): DesktopGitHubGrant {
        requireFalse(item, "production_activation", path)
        if (item.strictString("schema", path) != GRANT_SCHEMA) fail("$path.schema is unsupported")
        val grantId = item.strictString("grant_id", path)
        if (!GRANT_ID.matches(grantId)) fail("$path.grant_id has invalid format")
        val digest = item.strictString("scope_sha256", path)
        if (!SHA256.matches(digest)) fail("$path.scope_sha256 must be lowercase SHA-256")
        val status = item.strictString("status", path)
        if (status !in setOf("active", "revoked")) fail("$path.status is unsupported")
        val scope = item["scope"] as? JsonObject ?: fail("$path.scope must be an object")
        requireFalse(scope, "production_activation", "$path.scope")
        if (scope.strictString("schema", "$path.scope") != SCOPE_SCHEMA) {
            fail("$path.scope.schema is unsupported")
        }
        val repositories = scope.strictStringArray("repositories", "$path.scope", 1..25)
        val operations = scope.strictStringArray("operations", "$path.scope", 1..4)
        if (repositories.size != repositories.toSet().size) fail("$path.scope.repositories contains duplicates")
        if (operations.size != operations.toSet().size) fail("$path.scope.operations contains duplicates")
        if (operations.any { it !in READ_OPERATIONS }) fail("$path.scope.operations contains unsupported operation")
        val revokedAt = item.optionalString("revoked_at", path)
        val revokedBy = item.optionalString("revoked_by", path)
        if (status == "active" && (revokedAt != null || revokedBy != null)) {
            fail("$path active grant contains revocation evidence")
        }
        if (status == "revoked" && (revokedAt == null || revokedBy == null)) {
            fail("$path revoked grant lacks revocation evidence")
        }
        return DesktopGitHubGrant(
            grantId = grantId,
            account = scope.strictString("account", "$path.scope"),
            repositories = repositories,
            operations = operations,
            scopeSha256 = digest,
            createdAt = item.strictString("created_at", path),
            createdBy = item.strictString("created_by", path),
            status = status,
            revokedAt = revokedAt,
            revokedBy = revokedBy,
        )
    }

    private fun parseAuditEntry(item: JsonObject, index: Int): DesktopGitHubAuditEntry {
        val path = "entries[$index]"
        if (item.strictString("connector", path) != "github") fail("$path.connector must be github")
        val operation = item.strictString("operation", path)
        if (operation !in READ_OPERATIONS) fail("$path.operation is unsupported")
        val outcome = item.strictString("outcome", path)
        if (outcome !in OUTCOMES) fail("$path.outcome is unsupported")
        val durationMs = item.strictNonNegativeLong("duration_ms", path)
        val grantId = item.optionalString("grant_id", path)
        if (grantId != null && !GRANT_ID.matches(grantId)) fail("$path.grant_id has invalid format")
        val digest = item.optionalString("scope_sha256", path)
        if (digest != null && !SHA256.matches(digest)) fail("$path.scope_sha256 must be lowercase SHA-256 or null")
        val detail = item.strictString("detail", path)
        if (detail.length > 120) fail("$path.detail exceeds 120 characters")
        return DesktopGitHubAuditEntry(
            timestamp = item.strictString("ts", path),
            account = item.optionalString("account", path),
            repository = item.strictString("repository", path),
            operation = operation,
            objectId = item.optionalString("object_id", path),
            outcome = outcome,
            grantId = grantId,
            scopeSha256 = digest,
            revision = item.optionalString("revision", path),
            durationMs = durationMs,
            detail = detail,
        )
    }

    private fun get(path: String, label: String): String {
        val request = HttpRequest.newBuilder(URI.create(base + path))
            .header("Accept", "application/json")
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(10))
            .GET()
            .build()
        return execute(request, "GitHub connector GET $label")
    }

    private fun post(path: String, body: String, label: String): String {
        val request = HttpRequest.newBuilder(URI.create(base + path))
            .header("Accept", "application/json")
            .header("Content-Type", "application/json")
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(10))
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build()
        return execute(request, "GitHub connector POST $label")
    }

    private fun execute(request: HttpRequest, label: String): String {
        val response = try {
            http.send(request, HttpResponse.BodyHandlers.ofString())
        } catch (exc: Exception) {
            throw ControlCenterException("$label failed: ${exc::class.simpleName}")
        }
        if (response.statusCode() !in 200..299) {
            throw ControlCenterException("$label failed (${response.statusCode()}): ${response.body().take(500)}")
        }
        if (response.body().isBlank()) throw ControlCenterException("$label returned an empty body")
        return response.body()
    }

    private fun parseObject(body: String, label: String): JsonObject = try {
        json.parseToJsonElement(body).jsonObject
    } catch (exc: ControlCenterException) {
        throw exc
    } catch (exc: Exception) {
        fail("$label invalid JSON: ${exc::class.simpleName}")
    }

    private fun requireConnectorRoot(root: JsonObject, label: String) {
        if (root.strictString("connector", label) != "github") fail("$label.connector must be github")
        requireFalse(root, "production_activation", label)
    }

    private fun requireFalse(root: JsonObject, key: String, path: String) {
        val primitive = root[key] as? JsonPrimitive ?: fail("$path.$key must be false")
        if (primitive.isString || primitive.booleanOrNull != false) fail("$path.$key must be false")
    }

    private fun JsonObject.strictString(key: String, path: String): String {
        val primitive = this[key] as? JsonPrimitive ?: fail("$path.$key must be a string")
        if (!primitive.isString) fail("$path.$key must be a string")
        return primitive.content.trim().takeIf { it.isNotEmpty() } ?: fail("$path.$key must not be blank")
    }

    private fun JsonObject.optionalString(key: String, path: String): String? {
        val value: JsonElement = this[key] ?: return null
        if (value is JsonNull) return null
        val primitive = value as? JsonPrimitive ?: fail("$path.$key must be string or null")
        if (!primitive.isString) fail("$path.$key must be string or null")
        return primitive.content.trim().takeIf { it.isNotEmpty() }
    }

    private fun JsonObject.strictStringArray(key: String, path: String, size: IntRange): List<String> {
        val array = this[key] as? JsonArray ?: fail("$path.$key must be an array")
        if (array.size !in size) fail("$path.$key has invalid size")
        return array.mapIndexed { index, element ->
            val primitive = element as? JsonPrimitive ?: fail("$path.$key[$index] must be a non-blank string")
            if (!primitive.isString) fail("$path.$key[$index] must be a non-blank string")
            primitive.content.trim().takeIf { it.isNotEmpty() }
                ?: fail("$path.$key[$index] must be a non-blank string")
        }
    }

    private fun JsonObject.strictNonNegativeLong(key: String, path: String): Long {
        val primitive = this[key] as? JsonPrimitive ?: fail("$path.$key must be an integer")
        if (primitive.isString || !INTEGER_TEXT.matches(primitive.content)) fail("$path.$key must be an integer")
        val value = primitive.content.toLongOrNull() ?: fail("$path.$key must be an integer")
        if (value < 0) fail("$path.$key must be non-negative")
        return value
    }

    private fun seg(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8.toString()).replace("+", "%20")

    private fun fail(message: String): Nothing =
        throw ControlCenterException("Invalid GitHub connector Control Center payload: $message")
}

data class DesktopGitHubConnectorSnapshot(
    val grants: List<DesktopGitHubGrant>,
    val audit: List<DesktopGitHubAuditEntry>,
) {
    val activeGrants: List<DesktopGitHubGrant> get() = grants.filter { it.active }

    fun filteredAudit(
        repository: String? = null,
        operation: String? = null,
        outcome: String? = null,
    ): List<DesktopGitHubAuditEntry> {
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

data class DesktopGitHubGrant(
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

data class DesktopGitHubAuditEntry(
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
