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
    fun authenticatedReadParsesCuratedVisionRigState() {
        val authorization = AtomicReference<String>()
        val path = AtomicReference<String>()
        val server = server { exchange ->
            authorization.set(exchange.requestHeaders.getFirst("Authorization"))
            path.set(exchange.requestURI.path)
            val body = """{"vision":${validSnapshot()}}""".toByteArray()
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
            assertEquals(1, snapshot.sensorsReturned)
            assertFalse(snapshot.sensorsTruncated)
            val sensor = snapshot.sensors.single()
            assertEquals("kinect-living-room", sensor.sourceId)
            assertEquals("online", sensor.presence)
            assertEquals("converged", sensor.convergence)
            assertEquals("normal", sensor.transportStatus)
            assertEquals("current", sensor.capabilityRefreshStatus)
            assertEquals(4194304, sensor.negotiatedMaxPayloadBytes)
            assertEquals("auto", sensor.negotiatedPacketCompression)
            assertEquals("Bearer desktop-token", authorization.get())
            assertEquals("/api/v1/control-center/status", path.get())
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun parserRejectsActivationAndContradictorySensorState() {
        val client = ControlCenterVisionClient("http://127.0.0.1:1", "token")
        assertInvalid(
            client,
            validSnapshot().replace("\"production_activation\":false", "\"production_activation\":true"),
            "production_activation",
        )
        assertInvalid(
            client,
            validSnapshot().replace("\"presence\":\"online\"", "\"presence\":\"synthetic\""),
            "presence",
        )
        assertInvalid(
            client,
            validSnapshot().replace("\"total\":1", "\"total\":2"),
            "total contradicts",
        )
    }

    @Test
    fun unavailableSnapshotCannotCarrySensors() {
        val client = ControlCenterVisionClient("http://127.0.0.1:1", "token")
        val invalid = validSnapshot()
            .replace("\"available\":true", "\"available\":false")
            .replace("\"reason\":null", "\"reason\":\"visionrig_unavailable:ConnectError\"")
        assertInvalid(client, invalid, "unavailable snapshot contains sensors")
    }

    @Test
    fun backendFailureRemainsFailure() {
        val server = server { exchange ->
            val body = "{\"error\":\"control center vision unavailable\"}".toByteArray()
            exchange.sendResponseHeaders(502, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val error = runCatching {
                ControlCenterVisionClient(
                    "http://127.0.0.1:${server.address.port}",
                    "token",
                ).snapshot()
            }.exceptionOrNull()
            assertTrue(error is ControlCenterException)
            assertTrue(error?.message.orEmpty().contains("(502)"))
        } finally {
            server.stop(0)
        }
    }

    private fun assertInvalid(client: ControlCenterVisionClient, body: String, text: String) {
        val error = runCatching { client.parseSnapshot(body) }.exceptionOrNull()
        assertTrue(error is ControlCenterException)
        assertTrue(error?.message.orEmpty().contains(text), "${error?.message} should contain $text")
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
          "sensor_state_revision":12,
          "consistency":"synced",
          "total":1,
          "sensors_returned":1,
          "sensors_truncated":false,
          "presence":{"online":1,"stale":0,"offline":0,"unknown":0},
          "control":{"converged":1,"pending":0,"unknown":0},
          "transport":{"normal":1,"warning":0,"critical":0,"unknown":0},
          "capability_refresh":{"current":1,"stale":0,"unknown":0},
          "attention_total":0,
          "attention_truncated":false,
          "sensors":[{
            "source_id":"kinect-living-room",
            "display_name":"Kinect stue",
            "location":"stue",
            "role":"room-camera",
            "source_type":"camera",
            "device":"kinect-v2",
            "capabilities":["rgb","depth","infrared"],
            "lifecycle":"active",
            "presence":"online",
            "desired_enabled":true,
            "effective_capture_active":true,
            "convergence":"converged",
            "desired_revision":4,
            "applied_revision":4,
            "pending_seconds":null,
            "transport_status":"normal",
            "payload_utilization":0.42,
            "capability_refresh_status":"current",
            "negotiated_max_payload_bytes":4194304,
            "negotiated_packet_compression":"auto",
            "negotiated_packet_target_utilization":0.8,
            "first_seen_utc":"2026-09-27T10:00:00+00:00",
            "last_seen_utc":"2026-09-27T10:30:00+00:00",
            "runtime_last_seen_utc":"2026-09-27T10:30:00+00:00",
            "observation_count":42
          }],
          "production_activation":false
        }
    """.trimIndent()
}
