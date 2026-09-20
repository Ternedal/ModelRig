package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DevControlPilotStatusClientTest {
    @Test
    fun authenticatedReadUsesExactStatusRoute() {
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
            val status = DevControlPilotStatusClient(
                "http://127.0.0.1:${server.address.port}",
                "desktop-token",
            ).status()

            assertTrue(status != null)
            assertEquals(DevControlPilotStatusClient.FEATURE_FLAG, status.featureFlag)
            assertTrue(status.manualRefreshOnly)
            assertEquals(DevControlPilotStatusClient.AUTHORITY, status.authority)
            assertEquals("Bearer desktop-token", authorization.get())
            assertEquals(DevControlPilotStatusClient.ROUTE, path.get())
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun defaultOff404IsAbsenceNotAnError() {
        val server = server { exchange ->
            exchange.sendResponseHeaders(404, -1)
            exchange.close()
        }
        try {
            assertNull(
                DevControlPilotStatusClient(
                    "http://127.0.0.1:${server.address.port}",
                    "desktop-token",
                ).status(),
            )
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun parserRejectsAnyBroadenedAuthority() {
        val client = client()
        for (field in listOf(
            "automatic_polling",
            "unattended_cadence",
            "task_registry_ready",
            "runtime_preflight_satisfied",
            "pilot_start_authorized",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_transport_available",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )) {
            val error = runCatching {
                client.parse(validStatus().replace("\"$field\":false", "\"$field\":true"))
            }.exceptionOrNull()
            assertTrue(error is ControlCenterException, "$field should fail closed")
            assertTrue(error?.message.orEmpty().contains("must remain false"), error?.message)
        }
    }

    @Test
    fun parserRejectsContractIdentityDrift() {
        val client = client()
        assertInvalid(
            client,
            validStatus().replace(DevControlPilotStatusClient.SCHEMA, "kaliv-devcontrol-pilot-status/v2"),
            "unsupported schema",
        )
        assertInvalid(
            client,
            validStatus().replace(DevControlPilotStatusClient.FEATURE_FLAG, "KALIV_DEVCONTROL_PILOT_ALIAS"),
            "unexpected feature flag",
        )
        assertInvalid(
            client,
            validStatus().replace("\"manual_refresh_only\":true", "\"manual_refresh_only\":false"),
            "manual refresh invariant missing",
        )
        assertInvalid(
            client,
            validStatus().replace(DevControlPilotStatusClient.AUTHORITY, "dc-l16-executor"),
            "unexpected authority",
        )
    }

    @Test
    fun non404BackendErrorsRemainErrors() {
        val server = server { exchange ->
            val body = "{\"error\":\"invalid token\"}".toByteArray()
            exchange.sendResponseHeaders(401, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val error = runCatching {
                DevControlPilotStatusClient(
                    "http://127.0.0.1:${server.address.port}",
                    "bad-token",
                ).status()
            }.exceptionOrNull()
            assertTrue(error is ControlCenterException)
            assertTrue(error?.message.orEmpty().contains("(401)"))
        } finally {
            server.stop(0)
        }
    }

    private fun client() = DevControlPilotStatusClient("http://127.0.0.1:1", "token")

    private fun assertInvalid(client: DevControlPilotStatusClient, body: String, text: String) {
        val error = runCatching { client.parse(body) }.exceptionOrNull()
        assertTrue(error is ControlCenterException, "unexpected error: $error")
        assertTrue(error?.message.orEmpty().contains(text), "${error?.message} should contain $text")
    }

    private fun server(handler: (com.sun.net.httpserver.HttpExchange) -> Unit): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange -> handler(exchange) }
        server.start()
        return server
    }

    private fun validStatus(): String = """
        {
          "schema":"kaliv-devcontrol-pilot-status/v1",
          "feature_flag":"KALIV_DEVCONTROL_PILOT",
          "enabled":true,
          "operator_surface":"desktop.control-center",
          "route_scope":"read-only-status-only",
          "manual_refresh_only":true,
          "automatic_polling":false,
          "unattended_cadence":false,
          "task_registry_ready":false,
          "runtime_preflight_satisfied":false,
          "pilot_start_authorized":false,
          "product_pilot_started":false,
          "local_commit_authorized":false,
          "remote_transport_available":false,
          "remote_write_authorized":false,
          "push_authorized":false,
          "pr_mutation_authorized":false,
          "merge_authorized":false,
          "release_authorized":false,
          "deploy_authorized":false,
          "production_activation_authorized":false,
          "authority":"dc-l16-product-status-observation-only"
        }
    """.trimIndent()
}
