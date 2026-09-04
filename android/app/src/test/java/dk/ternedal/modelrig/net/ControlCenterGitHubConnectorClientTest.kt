package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControlCenterGitHubConnectorClientTest {
    @Test
    fun snapshotUsesAuthenticatedBackendRoutesAndPreservesConnectorEvidence() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(grantsPayload()))
        server.enqueue(jsonResponse(auditPayload()))
        server.start()
        try {
            val snapshot = ControlCenterGitHubConnectorClient(
                server.url("/").toString(),
                "paired-token",
            ).snapshot()

            assertEquals(1, snapshot.activeGrants.size)
            assertEquals("issue", snapshot.audit.single().operation)
            assertEquals("ternedal/modelrig", snapshot.audit.single().repository)
            assertEquals(
                "ghg_0123456789abcdef0123456789abcdef",
                snapshot.audit.single().grantId,
            )
            assertEquals("abc123", snapshot.audit.single().revision)

            val grantsRequest = server.takeRequest()
            assertEquals("GET", grantsRequest.method)
            assertEquals("/api/v1/github-connector/grants?include_revoked=true", grantsRequest.path)
            assertEquals("Bearer paired-token", grantsRequest.getHeader("Authorization"))

            val auditRequest = server.takeRequest()
            assertEquals("GET", auditRequest.method)
            assertEquals("/api/v1/github-connector/audit?limit=100", auditRequest.path)
            assertEquals("Bearer paired-token", auditRequest.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun revokeBindsExactScopeDigestAndRequiresExplicitServerConfirmationBody() {
        val server = MockWebServer()
        val revokedGrant = grantPayload(status = "revoked")
        server.enqueue(
            jsonResponse(
                JSONObject()
                    .put("connector", "github")
                    .put("grant", revokedGrant)
                    .put("revoked_now", true)
                    .put("production_activation", false),
            ),
        )
        server.start()
        try {
            val client = ControlCenterGitHubConnectorClient(server.url("/").toString(), "paired-token")
            val active = client.parseGrants(grantsPayload()).single()
            val revoked = client.revoke(active)

            assertFalse(revoked.active)
            assertEquals(active.grantId, revoked.grantId)
            assertEquals(active.scopeSha256, revoked.scopeSha256)

            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertEquals("/api/v1/github-connector/grants/${active.grantId}/revoke", request.path)
            assertEquals("Bearer paired-token", request.getHeader("Authorization"))
            val body = JSONObject(request.body.readUtf8())
            assertEquals(active.scopeSha256, body.getString("expected_scope_sha256"))
            assertTrue(body.getBoolean("confirm_revoke"))
            assertEquals(2, body.length())
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun malformedBooleanAndNumericTypesFailClosed() {
        val client = ControlCenterGitHubConnectorClient("http://127.0.0.1:1", "token")

        val stringActivation = grantsPayload().put("production_activation", "false")
        val first = runCatching { client.parseGrants(stringActivation) }.exceptionOrNull()
        assertTrue(first is ModelRigException)
        assertTrue(first?.message.orEmpty().contains("production_activation must be false"))

        val fractionalDuration = auditPayload()
        fractionalDuration.getJSONArray("entries").getJSONObject(0).put("duration_ms", 4.5)
        val second = runCatching { client.parseAudit(fractionalDuration) }.exceptionOrNull()
        assertTrue(second is ModelRigException)
        assertTrue(second?.message.orEmpty().contains("duration_ms must be an integer"))
    }

    @Test
    fun futureGrantOrScopeSchemaFailsClosed() {
        val client = ControlCenterGitHubConnectorClient("http://127.0.0.1:1", "token")

        val futureGrant = grantsPayload()
        futureGrant.getJSONArray("grants").getJSONObject(0)
            .put("schema", "kaliv-github-connector-grant/v2")
        val first = runCatching { client.parseGrants(futureGrant) }.exceptionOrNull()
        assertTrue(first is ModelRigException)
        assertTrue(first?.message.orEmpty().contains("schema is unsupported"))

        val futureScope = grantsPayload()
        futureScope.getJSONArray("grants").getJSONObject(0).getJSONObject("scope")
            .put("schema", "kaliv-github-connector-scope/v2")
        val second = runCatching { client.parseGrants(futureScope) }.exceptionOrNull()
        assertTrue(second is ModelRigException)
        assertTrue(second?.message.orEmpty().contains("scope.schema is unsupported"))
    }

    @Test
    fun connectorIdentityIsRequiredAndNeverInferred() {
        val client = ControlCenterGitHubConnectorClient("http://127.0.0.1:1", "token")
        val wrongConnector = auditPayload()
        wrongConnector.getJSONArray("entries").getJSONObject(0).put("connector", "gitlab")

        val error = runCatching { client.parseAudit(wrongConnector) }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertTrue(error?.message.orEmpty().contains("connector must be github"))
    }

    @Test
    fun localAuditFilteringUsesRecordedRepositoryOperationAndOutcome() {
        val client = ControlCenterGitHubConnectorClient("http://127.0.0.1:1", "token")
        val snapshot = ControlCenterGitHubConnectorSnapshot(
            grants = client.parseGrants(grantsPayload()),
            audit = client.parseAudit(auditPayload()),
        )

        assertEquals(1, snapshot.filteredAudit(repository = "modelrig").size)
        assertEquals(1, snapshot.filteredAudit(operation = "issue").size)
        assertEquals(1, snapshot.filteredAudit(outcome = "executed").size)
        assertTrue(snapshot.filteredAudit(operation = "pull_request").isEmpty())
        assertTrue(snapshot.filteredAudit(outcome = "blocked").isEmpty())
    }

    private fun jsonResponse(body: JSONObject) = MockResponse()
        .setResponseCode(200)
        .setHeader("Content-Type", "application/json")
        .setBody(body.toString())

    private fun grantsPayload(): JSONObject = JSONObject()
        .put("connector", "github")
        .put("grants", JSONArray().put(grantPayload(status = "active")))
        .put("production_activation", false)

    private fun grantPayload(status: String): JSONObject {
        val revoked = status == "revoked"
        return JSONObject()
            .put("schema", "kaliv-github-connector-grant/v1")
            .put("grant_id", "ghg_0123456789abcdef0123456789abcdef")
            .put(
                "scope",
                JSONObject()
                    .put("schema", "kaliv-github-connector-scope/v1")
                    .put("account", "ternedal")
                    .put("repositories", JSONArray().put("ternedal/modelrig"))
                    .put("operations", JSONArray().put("issue").put("pull_request"))
                    .put("production_activation", false),
            )
            .put("scope_sha256", "a".repeat(64))
            .put("created_at", "2026-08-12T09:00:00Z")
            .put("created_by", "loopback-operator")
            .put("status", status)
            .put("revoked_at", if (revoked) "2026-08-12T10:00:00Z" else JSONObject.NULL)
            .put("revoked_by", if (revoked) "loopback-operator" else JSONObject.NULL)
            .put("production_activation", false)
    }

    private fun auditPayload(): JSONObject = JSONObject()
        .put("connector", "github")
        .put(
            "entries",
            JSONArray().put(
                JSONObject()
                    .put("ts", "2026-08-12T09:15:00")
                    .put("connector", "github")
                    .put("account", "ternedal")
                    .put("repository", "ternedal/modelrig")
                    .put("operation", "issue")
                    .put("object_id", "88")
                    .put("outcome", "executed")
                    .put("grant_id", "ghg_0123456789abcdef0123456789abcdef")
                    .put("scope_sha256", "a".repeat(64))
                    .put("revision", "abc123")
                    .put("duration_ms", 12)
                    .put("detail", "fresh_remote_read"),
            ),
        )
        .put("production_activation", false)
}
