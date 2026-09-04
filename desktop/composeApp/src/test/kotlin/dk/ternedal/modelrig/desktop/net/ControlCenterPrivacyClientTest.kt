package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ControlCenterPrivacyClientTest {
    @Test
    fun authenticatedReadUsesExistingStatusRouteAndPreservesPrivacyEvidence() {
        val authorization = AtomicReference<String>()
        val path = AtomicReference<String>()
        val server = server { exchange ->
            authorization.set(exchange.requestHeaders.getFirst("Authorization"))
            path.set(exchange.requestURI.path)
            val body = validStatus().toByteArray()
            exchange.responseHeaders.add("Content-Type", "application/json")
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val privacy = ControlCenterPrivacyClient(
                "http://127.0.0.1:${server.address.port}",
                "desktop-token",
            ).privacy()

            assertEquals("ready", privacy.evidenceState)
            assertFalse(privacy.toolResultEgress!!.privateGateEnabled)
            assertEquals("allowed_legacy_mode", privacy.toolResultEgress!!.privateRule)
            assertEquals("dormant", privacy.commonDataSharing.state)
            assertFalse(privacy.scopedPermissions.revocationSupported)
            assertFalse(privacy.productionActivation)
            assertEquals("Bearer desktop-token", authorization.get())
            assertEquals("/api/v1/control-center/status", path.get())
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun olderStatusWithoutPrivacyFailsClosedToUnknown() {
        val privacy = client().parse(
            """{"schema":"kaliv-control-center-status/v1"}""",
        )

        assertEquals("unknown", privacy.evidenceState)
        assertEquals("privacy_not_reported", privacy.reason)
        assertEquals(null, privacy.toolResultEgress)
        assertFalse(privacy.scopedPermissions.revocationSupported)
        assertFalse(privacy.productionActivation)
    }

    @Test
    fun malformedPrivacyWireTypesAndContradictionsFailClosed() {
        val client = client()

        assertInvalid(
            client,
            validStatus().replace("\"production_activation\":false", "\"production_activation\":true"),
            "production activation must be false",
        )
        assertInvalid(
            client,
            validStatus().replace("\"private_gate_enabled\":false", "\"private_gate_enabled\":\"false\""),
            "private_gate_enabled must be boolean",
        )
        assertInvalid(
            client,
            validStatus().replace("\"private_gate_enabled\":false", "\"private_gate_enabled\":true"),
            "private gate/rule contradiction",
        )
        assertInvalid(
            client,
            validStatus().replace("\"revocation_supported\":false", "\"revocation_supported\":true"),
            "no active authority",
        )
        assertInvalid(
            client,
            validStatus().replace("\"runtime_integrated\":false", "\"runtime_integrated\":true"),
            "dormant data-sharing cannot be runtime integrated",
        )
        assertInvalid(
            client,
            validStatus().replace("\"secret\":\"forbidden\"", "\"secret\":\"allowed\""),
            "secret egress rule must be forbidden",
        )
    }

    @Test
    fun unknownPrivacyEvidenceRemainsUnknownAndCannotGrantRevocation() {
        val body = """
            {
              "schema":"kaliv-control-center-status/v1",
              "privacy":{
                "schema":"kaliv-control-center-privacy/v1",
                "evidence_state":"unknown",
                "reason":"provider_error:RuntimeError",
                "tool_result_egress":null,
                "common_data_sharing":{
                  "state":"unknown","runtime_integrated":false,
                  "reason":"privacy_provider_unavailable"
                },
                "scoped_permissions":{
                  "state":"unknown","count":null,"revocation_supported":false,
                  "reason":"privacy_provider_unavailable"
                },
                "production_activation":false
              }
            }
        """.trimIndent()

        val privacy = client().parse(body)
        assertEquals("unknown", privacy.evidenceState)
        assertEquals("provider_error:RuntimeError", privacy.reason)
        assertEquals(null, privacy.toolResultEgress)
        assertFalse(privacy.scopedPermissions.revocationSupported)
    }

    @Test
    fun malformedPrivacyObjectIsNotSilentlyTreatedAsMissing() {
        assertInvalid(
            client(),
            """{"schema":"kaliv-control-center-status/v1","privacy":"safe"}""",
            "privacy must be an object or null",
        )
    }

    @Test
    fun statusApiFailureDoesNotBecomeUnknownHealthyPrivacy() {
        val server = server { exchange ->
            val body = "{\"error\":\"control center status unavailable\"}".toByteArray()
            exchange.sendResponseHeaders(502, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val error = runCatching {
                ControlCenterPrivacyClient(
                    "http://127.0.0.1:${server.address.port}",
                    "token",
                ).privacy()
            }.exceptionOrNull()
            assertTrue(error is ControlCenterException)
            assertTrue(error.message.orEmpty().contains("(502)"))
        } finally {
            server.stop(0)
        }
    }

    private fun assertInvalid(client: ControlCenterPrivacyClient, body: String, text: String) {
        val error = runCatching { client.parse(body) }.exceptionOrNull()
        assertTrue(error is ControlCenterException)
        assertTrue(
            error.message.orEmpty().contains(text),
            "${error.message} should contain $text",
        )
    }

    private fun client() = ControlCenterPrivacyClient("http://127.0.0.1:1", "token")

    private fun server(handler: (com.sun.net.httpserver.HttpExchange) -> Unit): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange -> handler(exchange) }
        server.start()
        return server
    }

    private fun validStatus() = """
        {
          "schema":"kaliv-control-center-status/v1",
          "privacy":{
            "schema":"kaliv-control-center-privacy/v1",
            "evidence_state":"ready",
            "tool_result_egress":{
              "source":"toolgate",
              "private_gate_enabled":false,
              "rules":{
                "public":"allowed",
                "operational":"allowed",
                "private":"allowed_legacy_mode",
                "secret":"forbidden"
              }
            },
            "common_data_sharing":{
              "schema":"kaliv-data-sharing-policy/v1",
              "state":"dormant",
              "runtime_integrated":false,
              "reason":"common_data_sharing_not_runtime_integrated"
            },
            "scoped_permissions":{
              "state":"unavailable",
              "count":null,
              "revocation_supported":false,
              "reason":"no_active_scoped_permission_authority"
            },
            "production_activation":false
          }
        }
    """.trimIndent()
}
