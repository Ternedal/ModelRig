package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ControlCenterClientTest {
    @Test
    fun authenticatedReadPreservesServerStates() {
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
            val status = ControlCenterClient(
                "http://127.0.0.1:${server.address.port}",
                "desktop-token",
            ).status()

            assertEquals(ControlCenterClient.SCHEMA, status.schema)
            assertEquals("attention", status.overall)
            assertFalse(status.green)
            assertEquals("healthy", status.components.getValue("backend").state)
            assertEquals("stale", status.components.getValue("models").state)
            assertEquals("disabled", status.components.getValue("agent3").state)
            assertEquals("fallback", status.routing.state)
            assertEquals("readiness report expired", status.routing.fallbackReason)
            assertEquals(listOf("models"), status.requiredFailures)
            assertEquals("Bearer desktop-token", authorization.get())
            assertEquals("/api/v1/control-center/status", path.get())
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun parserRejectsContradictionsAndUnknownStates() {
        val client = ControlCenterClient("http://127.0.0.1:1", "token")

        assertInvalid(
            client,
            validStatus().replace(ControlCenterClient.SCHEMA, "kaliv-control-center-status/v9"),
            "unsupported schema",
        )
        assertInvalid(
            client,
            validStatus().replace(
                "\"overall\":\"attention\",\"green\":false",
                "\"overall\":\"healthy\",\"green\":false",
            ),
            "overall/green contradiction",
        )
        assertInvalid(
            client,
            validStatus().replaceFirst("\"state\":\"healthy\"", "\"state\":\"synthetic-green\""),
            "unsupported component state",
        )
        assertInvalid(
            client,
            validStatus().replace("\"required_failures\":[\"models\"]", "\"required_failures\":[]"),
            "required_failures contradiction",
        )
        assertInvalid(
            client,
            validStatus().replace(
                "\"fallback_reason\":\"readiness report expired\"",
                "\"fallback_reason\":null",
            ),
            "lacks server reason",
        )
    }

    @Test
    fun parserRequiresFreshnessForHealthyFacts() {
        val client = ControlCenterClient("http://127.0.0.1:1", "token")
        assertInvalid(
            client,
            validStatus().replaceFirst(
                "\"observed_at\":2000000000.0,\"age_s\":1.0",
                "\"observed_at\":null,\"age_s\":null",
            ),
            "lacks freshness evidence",
        )
        assertInvalid(
            client,
            validStatus().replaceFirst("\"age_s\":1.0", "\"age_s\":-1.0"),
            "negative age",
        )
    }

    @Test
    fun backendErrorsRemainErrorsInsteadOfSyntheticStatus() {
        val server = server { exchange ->
            val body = "{\"error\":\"control center status unavailable\"}".toByteArray()
            exchange.sendResponseHeaders(502, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val error = runCatching {
                ControlCenterClient(
                    "http://127.0.0.1:${server.address.port}",
                    "token",
                ).status()
            }.exceptionOrNull()
            assertTrue(error is ControlCenterException)
            assertTrue(error?.message.orEmpty().contains("(502)"))
            assertTrue(error?.message.orEmpty().contains("status unavailable"))
        } finally {
            server.stop(0)
        }
    }

    private fun assertInvalid(client: ControlCenterClient, body: String, text: String) {
        val error = runCatching { client.parse(body) }.exceptionOrNull()
        assertTrue(error is ControlCenterException)
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

    private fun validStatus(): String = """
        {
          "schema":"kaliv-control-center-status/v1",
          "generated_at":2000000001.0,
          "freshness_s":30.0,
          "overall":"attention","green":false,
          "components":{
            "backend":{"name":"backend","required":true,"state":"healthy","green":true,"observed_at":2000000000.0,"age_s":1.0,"detail":"backend detail","reason":null},
            "worker":{"name":"worker","required":true,"state":"healthy","green":true,"observed_at":2000000000.0,"age_s":1.0,"detail":"worker detail","reason":null},
            "models":{"name":"models","required":true,"state":"stale","green":false,"observed_at":1999999970.0,"age_s":31.0,"detail":"models detail","reason":"observation_too_old"},
            "agent3":{"name":"agent3","required":false,"state":"disabled","green":false,"observed_at":2000000000.0,"age_s":1.0,"detail":"disabled","reason":"disabled_by_configuration"}
          },
          "routing":{"state":"fallback","green":false,"configured_surface":"agent3_developer","active_surface":"agent_v2","fallback_reason":"readiness report expired","observed_at":2000000000.0,"age_s":1.0,"reason":"server_selected_fallback"},
          "summary":{"states":{"healthy":2,"stale":1,"disabled":1,"fallback":1},"required_failures":["models"]}
        }
    """.trimIndent()
}
