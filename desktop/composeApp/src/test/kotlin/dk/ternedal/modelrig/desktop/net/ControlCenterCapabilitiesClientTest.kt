package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ControlCenterCapabilitiesClientTest {
    @Test
    fun authenticatedReadKeepsRuntimeEnablementOutsideDescriptor() {
        val authorization = AtomicReference<String>()
        val path = AtomicReference<String>()
        val server = server { exchange ->
            authorization.set(exchange.requestHeaders.getFirst("Authorization"))
            path.set(exchange.requestURI.path)
            val body = validInventory().toByteArray()
            exchange.responseHeaders.add("Content-Type", "application/json")
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val inventory = ControlCenterCapabilitiesClient(
                "http://127.0.0.1:${server.address.port}",
                "desktop-token",
            ).inventory()

            assertTrue(inventory.toolLayerEnabled)
            assertEquals(2, inventory.capabilities.size)
            val models = inventory.capabilities.first { it.name == "list_models" }
            assertFalse(models.enabled)
            assertEquals("tool:list_models", models.capabilityId)
            assertEquals("operational", models.dataClass)
            assertEquals("configured_service", models.networkMode)
            assertEquals(listOf("ollama"), models.networkDestinations)
            assertFalse(models.schedulable)
            assertEquals("pilot only", models.schedulingReason)
            assertEquals("cooperative", models.terminationMode)
            assertTrue(models.idempotent)
            assertEquals("Bearer desktop-token", authorization.get())
            assertEquals("/api/v1/tools", path.get())
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun descriptorRejectsRuntimeStateActivationAndIdentityDrift() {
        val client = client()
        assertInvalid(
            client,
            validInventory().replace(
                "\"production_activation\":false",
                "\"enabled\":true,\"production_activation\":false",
            ),
            "invalid descriptor",
        )
        assertInvalid(
            client,
            validInventory().replaceFirst(
                "\"production_activation\":false",
                "\"production_activation\":true",
            ),
            "production activation must remain false",
        )
        assertInvalid(
            client,
            validInventory().replaceFirst("tool:current_datetime", "tool:someone_else"),
            "capability id mismatch",
        )
        assertInvalid(
            client,
            validInventory().replaceFirst(
                ControlCenterCapabilitiesClient.SCHEMA,
                "kaliv-capability/v9",
            ),
            "unsupported descriptor schema",
        )
    }

    @Test
    fun descriptorRejectsSchedulingNetworkAndConfirmationContradictions() {
        val client = client()
        assertInvalid(
            client,
            validInventory().replaceFirst(
                "\"allowed\":true,\"reason\":\"\"",
                "\"allowed\":true,\"reason\":\"not allowed\"",
            ),
            "carries a refusal reason",
        )
        assertInvalid(
            client,
            validInventory().replace(
                "\"mode\":\"configured_service\",\"destinations\":[\"ollama\"]",
                "\"mode\":\"configured_service\",\"destinations\":[]",
            ),
            "networked mode lacks a destination",
        )
        assertInvalid(
            client,
            validInventory().replace(
                "\"mode\":\"configured_service\",\"destinations\":[\"ollama\"]",
                "\"mode\":\"configured_service\",\"destinations\":[\"ollama\",\"ollama\"]",
            ),
            "contains duplicates",
        )
        val publicWithoutCard = validInventory()
            .replaceFirst(
                "\"mode\":\"none\",\"destinations\":[]",
                "\"mode\":\"public\",\"destinations\":[\"approved-public\"]",
            )
        assertInvalid(client, publicWithoutCard, "confirmation contradicts access/network")
    }

    @Test
    fun parserRejectsWrongBooleanAndDuplicateCapabilityIds() {
        val client = client()
        assertInvalid(
            client,
            validInventory().replaceFirst("\"enabled\":true", "\"enabled\":\"true\""),
            "enabled must be boolean",
        )
        val firstTool = tool(
            "current_datetime",
            true,
            currentDatetimeDescriptor(),
        )
        val duplicate = """{"enabled":true,"tools":[$firstTool,$firstTool]}"""
        assertInvalid(client, duplicate, "duplicate capability ids")
    }

    @Test
    fun backendErrorsRemainErrorsInsteadOfSyntheticInventory() {
        val server = server { exchange ->
            val body = "{\"error\":\"invalid token\"}".toByteArray()
            exchange.sendResponseHeaders(401, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val error = runCatching {
                ControlCenterCapabilitiesClient(
                    "http://127.0.0.1:${server.address.port}",
                    "bad-token",
                ).inventory()
            }.exceptionOrNull()
            assertTrue(error is ControlCenterException)
            assertTrue(error?.message.orEmpty().contains("(401)"))
            assertTrue(error?.message.orEmpty().contains("invalid token"))
        } finally {
            server.stop(0)
        }
    }

    private fun client() = ControlCenterCapabilitiesClient("http://127.0.0.1:1", "token")

    private fun assertInvalid(
        client: ControlCenterCapabilitiesClient,
        body: String,
        text: String,
    ) {
        val error = runCatching { client.parse(body) }.exceptionOrNull()
        assertTrue(error is ControlCenterException, "unexpected error: $error")
        assertTrue(
            error?.message.orEmpty().contains(text),
            "${error?.message} should contain $text",
        )
    }

    private fun server(handler: (com.sun.net.httpserver.HttpExchange) -> Unit): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange -> handler(exchange) }
        server.start()
        return server
    }

    private fun validInventory(): String = """
        {
          "enabled":true,
          "tools_dir":"/not-used-by-control-center",
          "tools":[
            ${tool("current_datetime", true, currentDatetimeDescriptor())},
            ${tool("list_models", false, listModelsDescriptor())}
          ]
        }
    """.trimIndent()

    private fun tool(name: String, enabled: Boolean, descriptor: String): String = """
        {
          "name":"$name",
          "risk":"read",
          "description":"legacy wrapper",
          "params":{},
          "enabled":$enabled,
          "impact":"read",
          "schedulable":true,
          "unschedulable_reason":"",
          "cancellation":"none",
          "network":"none",
          "network_destinations":[],
          "idempotent":true,
          "descriptor":$descriptor
        }
    """.trimIndent()

    private fun currentDatetimeDescriptor(): String = """
        {
          "schema":"kaliv-capability/v2",
          "capability_id":"tool:current_datetime",
          "kind":"tool",
          "description":"Læs serverens aktuelle tid.",
          "access":"read",
          "impact":"read",
          "data_class":"public",
          "parameters":{"type":"object","properties":{}},
          "isolation":{"mode":"in_process","env_allow":[]},
          "scheduling":{"allowed":true,"reason":""},
          "confirmation":{"mode":"none"},
          "network":{"mode":"none","destinations":[]},
          "termination":{"mode":"none"},
          "replay":{"idempotent":true},
          "production_activation":false
        }
    """.trimIndent()

    private fun listModelsDescriptor(): String = """
        {
          "schema":"kaliv-capability/v2",
          "capability_id":"tool:list_models",
          "kind":"tool",
          "description":"Læs lokal modeloversigt.",
          "access":"read",
          "impact":"read",
          "data_class":"operational",
          "parameters":{"type":"object","properties":{}},
          "isolation":{"mode":"process","env_allow":["OLLAMA_HOST"]},
          "scheduling":{"allowed":false,"reason":"pilot only"},
          "confirmation":{"mode":"none"},
          "network":{"mode":"configured_service","destinations":["ollama"]},
          "termination":{"mode":"cooperative"},
          "replay":{"idempotent":true},
          "production_activation":false
        }
    """.trimIndent()
}
