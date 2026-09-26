package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ControlCenterVisionClientTest {
    @Test
    fun authenticatedSnapshotParsesBoundedVisionProjection() {
        val authorization = AtomicReference<String>()
        val path = AtomicReference<String>()
        val server = server { exchange ->
            authorization.set(exchange.requestHeaders.getFirst("Authorization"))
            path.set(exchange.requestURI.path)
            val body = validSnapshot().toByteArray()
            exchange.responseHeaders.add("Content-Type", "application/json")
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val snapshot = ControlCenterVisionClient(
                "http://127.0.0.1:${server.address.port}",
                "desktop-token",
            ).snapshot()

            assertTrue(snapshot.available)
            assertEquals(1, snapshot.sensors.size)
            val sensor = snapshot.sensors.single()
            assertEquals("Stue Kinect", sensor.title)
            assertEquals("online", sensor.presence)
            assertEquals(listOf("depth", "infrared", "rgb"), sensor.capabilities)
            assertTrue(sensor.desiredEnabled)
            assertEquals(true, sensor.effectiveCaptureActive)
            assertEquals("converged", sensor.convergence)
            assertEquals("Bearer desktop-token", authorization.get())
            assertEquals("/api/v1/control-center/vision", path.get())
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun enabledMutationUsesAuthenticatedNarrowPatch() {
        val authorization = AtomicReference<String>()
        val method = AtomicReference<String>()
        val path = AtomicReference<String>()
        val requestBody = AtomicReference<String>()
        val server = server { exchange ->
            authorization.set(exchange.requestHeaders.getFirst("Authorization"))
            method.set(exchange.requestMethod)
            path.set(exchange.requestURI.rawPath)
            requestBody.set(exchange.requestBody.bufferedReader().readText())
            val body = """
                {"schema":"kaliv-control-center-vision-enabled/v1","source_id":"cam a","enabled":false}
            """.trimIndent().toByteArray()
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val receipt = ControlCenterVisionClient(
                "http://127.0.0.1:${server.address.port}",
                "desktop-token",
            ).setEnabled("cam a", false)

            assertEquals("cam a", receipt.sourceId)
            assertFalse(receipt.enabled)
            assertEquals("PATCH", method.get())
            assertEquals("/api/v1/control-center/vision/sensors/cam%20a/enabled", path.get())
            assertEquals("{\"enabled\":false}", requestBody.get())
            assertEquals("Bearer desktop-token", authorization.get())
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun parserRejectsControlContradictions() {
        val client = ControlCenterVisionClient("http://127.0.0.1:1", "token")

        assertInvalid(
            client,
            validSnapshot().replace(
                "\"convergence\":\"converged\"",
                "\"convergence\":\"pending\"",
            ),
            "pending state is contradictory",
        )
        assertInvalid(
            client,
            validSnapshot().replace(
                "\"effective_capture_active\":true",
                "\"effective_capture_active\":false",
            ),
            "convergence contradicts",
        )
        assertInvalid(
            client,
            validSnapshot().replace(
                "\"production_activation\":false",
                "\"production_activation\":true",
            ),
            "production_activation",
        )
    }

    private fun assertInvalid(
        client: ControlCenterVisionClient,
        body: String,
        expected: String,
    ) {
        val error = runCatching { client.parseSnapshot(body) }.exceptionOrNull()
        assertTrue(error is ControlCenterException)
        assertTrue(error?.message.orEmpty().contains(expected), error?.message)
    }

    private fun server(handler: (com.sun.net.httpserver.HttpExchange) -> Unit): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange -> handler(exchange) }
        server.start()
        return server
    }

    private fun validSnapshot(): String = """
        {
          "schema":"kaliv-control-center-vision/v1",
          "available":true,
          "reason":null,
          "production_activation":false,
          "sensors":[{
            "source_id":"kinect-living-room",
            "display_name":"Stue Kinect",
            "location":"Stue",
            "role":"tracking",
            "source_type":"camera",
            "device":"kinect-v2",
            "capabilities":["rgb","depth","infrared"],
            "presence":"online",
            "desired_enabled":true,
            "effective_capture_active":true,
            "convergence":"converged",
            "first_seen_utc":"2026-09-26T04:30:00+00:00",
            "last_seen_utc":"2026-09-26T04:35:00+00:00",
            "runtime_last_seen_utc":"2026-09-26T04:35:01+00:00",
            "observation_count":12
          }]
        }
    """.trimIndent()
}
