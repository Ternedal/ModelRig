package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ControlCenterGitHubConnectorClientTest {
    @Test
    fun snapshotUsesAuthenticatedBackendRoutes() {
        val requests = CopyOnWriteArrayList<Triple<String, String?, String>>()
        val server = server { exchange ->
            val target = buildString {
                append(exchange.requestURI.path)
                exchange.requestURI.rawQuery?.let { append('?').append(it) }
            }
            requests += Triple(target, exchange.requestHeaders.getFirst("Authorization"), exchange.requestMethod)
            val response = if (exchange.requestURI.path.endsWith("/grants")) grantsPayload() else auditPayload()
            writeJson(exchange, 200, response)
        }
        try {
            val snapshot = ControlCenterGitHubConnectorClient(
                "http://127.0.0.1:${server.address.port}",
                "paired-token",
            ).snapshot()

            assertEquals(1, snapshot.activeGrants.size)
            assertEquals("ternedal/modelrig", snapshot.audit.single().repository)
            assertEquals("issue", snapshot.audit.single().operation)
            assertEquals(
                listOf(
                    Triple("/api/v1/github-connector/grants?include_revoked=true", "Bearer paired-token", "GET"),
                    Triple("/api/v1/github-connector/audit?limit=100", "Bearer paired-token", "GET"),
                ),
                requests.toList(),
            )
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun revokeUsesExactScopeDigestAndExplicitConfirmation() {
        var receivedBody = ""
        var receivedPath = ""
        var receivedAuth: String? = null
        val server = server { exchange ->
            receivedPath = exchange.requestURI.path
            receivedAuth = exchange.requestHeaders.getFirst("Authorization")
            receivedBody = exchange.requestBody.bufferedReader().use { it.readText() }
            writeJson(exchange, 200, revokePayload())
        }
        try {
            val client = ControlCenterGitHubConnectorClient(
                "http://127.0.0.1:${server.address.port}",
                "paired-token",
            )
            val active = client.parseGrants(grantsPayload()).single()
            val revoked = client.revoke(active)

            assertFalse(revoked.active)
            assertEquals(active.grantId, revoked.grantId)
            assertEquals(active.scopeSha256, revoked.scopeSha256)
            assertEquals("/api/v1/github-connector/grants/${active.grantId}/revoke", receivedPath)
            assertEquals("Bearer paired-token", receivedAuth)
            assertEquals(
                "{\"expected_scope_sha256\":\"${active.scopeSha256}\",\"confirm_revoke\":true}",
                receivedBody,
            )
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun schemaConnectorAndActivationContractsFailClosed() {
        val client = client()

        val futureGrant = grantsPayload().replace(
            "kaliv-github-connector-grant/v1",
            "kaliv-github-connector-grant/v2",
        )
        val first = runCatching { client.parseGrants(futureGrant) }.exceptionOrNull()
        assertTrue(first is ControlCenterException)
        assertTrue(first.message.orEmpty().contains("schema is unsupported"))

        val futureScope = grantsPayload().replace(
            "kaliv-github-connector-scope/v1",
            "kaliv-github-connector-scope/v2",
        )
        val second = runCatching { client.parseGrants(futureScope) }.exceptionOrNull()
        assertTrue(second is ControlCenterException)
        assertTrue(second.message.orEmpty().contains("scope.schema is unsupported"))

        val stringActivation = grantsPayload().replace(
            "\"production_activation\":false",
            "\"production_activation\":\"false\"",
        )
        val third = runCatching { client.parseGrants(stringActivation) }.exceptionOrNull()
        assertTrue(third is ControlCenterException)
        assertTrue(third.message.orEmpty().contains("production_activation must be false"))

        val wrongConnector = auditPayload().replace("\"connector\":\"github\"", "\"connector\":\"gitlab\"")
        val fourth = runCatching { client.parseAudit(wrongConnector) }.exceptionOrNull()
        assertTrue(fourth is ControlCenterException)
        assertTrue(fourth.message.orEmpty().contains("connector must be github"))
    }

    @Test
    fun fractionalDurationAndUnknownOperationsFailClosed() {
        val client = client()
        val fractional = auditPayload().replace("\"duration_ms\":12", "\"duration_ms\":12.5")
        val first = runCatching { client.parseAudit(fractional) }.exceptionOrNull()
        assertTrue(first is ControlCenterException)
        assertTrue(first.message.orEmpty().contains("duration_ms must be an integer"))

        val unknownOperation = auditPayload().replace("\"operation\":\"issue\"", "\"operation\":\"write_issue\"")
        val second = runCatching { client.parseAudit(unknownOperation) }.exceptionOrNull()
        assertTrue(second is ControlCenterException)
        assertTrue(second.message.orEmpty().contains("operation is unsupported"))
    }

    @Test
    fun auditFilteringUsesRecordedFieldsOnly() {
        val snapshot = DesktopGitHubConnectorSnapshot(
            grants = client().parseGrants(grantsPayload()),
            audit = client().parseAudit(auditPayload()),
        )
        assertEquals(1, snapshot.filteredAudit(repository = "modelrig").size)
        assertEquals(1, snapshot.filteredAudit(operation = "issue").size)
        assertEquals(1, snapshot.filteredAudit(outcome = "executed").size)
        assertTrue(snapshot.filteredAudit(operation = "pull_request").isEmpty())
        assertTrue(snapshot.filteredAudit(outcome = "blocked").isEmpty())
    }

    private fun client() = ControlCenterGitHubConnectorClient("http://127.0.0.1:1", "token")

    private fun server(handler: (com.sun.net.httpserver.HttpExchange) -> Unit): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange -> handler(exchange) }
        server.start()
        return server
    }

    private fun writeJson(exchange: com.sun.net.httpserver.HttpExchange, status: Int, body: String) {
        val bytes = body.toByteArray()
        exchange.responseHeaders.add("Content-Type", "application/json")
        exchange.sendResponseHeaders(status, bytes.size.toLong())
        exchange.responseBody.use { it.write(bytes) }
    }

    private fun grantsPayload() = """
        {
          "connector":"github",
          "grants":[${grantPayload("active")}],
          "production_activation":false
        }
    """.trimIndent()

    private fun grantPayload(status: String): String {
        val revokedAt = if (status == "revoked") "\"2026-08-12T10:00:00Z\"" else "null"
        val revokedBy = if (status == "revoked") "\"loopback-operator\"" else "null"
        return """
            {
              "schema":"kaliv-github-connector-grant/v1",
              "grant_id":"ghg_0123456789abcdef0123456789abcdef",
              "scope":{
                "schema":"kaliv-github-connector-scope/v1",
                "account":"ternedal",
                "repositories":["ternedal/modelrig"],
                "operations":["issue","pull_request"],
                "production_activation":false
              },
              "scope_sha256":"${"a".repeat(64)}",
              "created_at":"2026-08-12T09:00:00Z",
              "created_by":"loopback-operator",
              "status":"$status",
              "revoked_at":$revokedAt,
              "revoked_by":$revokedBy,
              "production_activation":false
            }
        """.trimIndent()
    }

    private fun revokePayload() = """
        {
          "connector":"github",
          "grant":${grantPayload("revoked")},
          "revoked_now":true,
          "production_activation":false
        }
    """.trimIndent()

    private fun auditPayload() = """
        {
          "connector":"github",
          "entries":[
            {
              "ts":"2026-08-12T09:15:00",
              "connector":"github",
              "account":"ternedal",
              "repository":"ternedal/modelrig",
              "operation":"issue",
              "object_id":"88",
              "outcome":"executed",
              "grant_id":"ghg_0123456789abcdef0123456789abcdef",
              "scope_sha256":"${"a".repeat(64)}",
              "revision":"abc123",
              "duration_ms":12,
              "detail":"fresh_remote_read"
            }
          ],
          "production_activation":false
        }
    """.trimIndent()
}
