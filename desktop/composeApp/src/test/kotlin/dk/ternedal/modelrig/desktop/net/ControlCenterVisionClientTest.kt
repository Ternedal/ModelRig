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
            assertTrue(snapshot.controlAvailable)
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
            assertEquals(31, snapshot.visionRigSchemaVersions?.bootstrap)
            assertEquals(15, snapshot.visionRigSchemaVersions?.catalog)
            assertEquals(28, snapshot.visionRigSchemaVersions?.fleet)
            assertEquals(1, snapshot.producerReadiness.runtimeSources)
            assertEquals(1, snapshot.producerReadiness.heartbeatV6Sources)
            assertEquals(0, snapshot.producerReadiness.heartbeatUpgradeRequired)
            assertEquals(1.0, snapshot.producerReadiness.heartbeatV6Ratio)
            assertEquals(1, snapshot.producerReadiness.packetMeasurementCompleteSources)
            assertEquals(0, snapshot.producerReadiness.packetMeasurementGapSources)
            assertEquals(1.0, snapshot.producerReadiness.packetMeasurementCompleteRatio)
            assertEquals(1, snapshot.producerReadinessTransition.heartbeatV6SourcesDelta)
            assertEquals(0.1, snapshot.producerReadinessTransition.heartbeatV6RatioDelta)
            assertEquals("Bearer desktop-token", authorization.get())
            assertEquals("/api/v1/control-center/status", path.get())
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
            assertEquals(
                "/api/v1/control-center/vision/sensors/cam%20a/enabled",
                path.get(),
            )
            assertEquals("""{"enabled":false}""", requestBody.get())
            assertEquals("Bearer desktop-token", authorization.get())
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun enabledMutationRejectsMismatchedReceipt() {
        val server = server { exchange ->
            val body = """
                {"schema":"kaliv-control-center-vision-enabled/v1","source_id":"other","enabled":true}
            """.trimIndent().toByteArray()
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val error = runCatching {
                ControlCenterVisionClient(
                    "http://127.0.0.1:${server.address.port}",
                    "desktop-token",
                ).setEnabled("cam-a", true)
            }.exceptionOrNull()
            assertTrue(error is ControlCenterException)
            assertTrue(error?.message.orEmpty().contains("does not match"))
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
          "control_available":true,
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
          "visionrig_schema_versions":{"bootstrap":31,"catalog":15,"fleet":28},
          "producer_readiness":{
            "runtime_sources":1,
            "heartbeat_v6_sources":1,
            "heartbeat_upgrade_required":0,
            "heartbeat_v6_ratio":1.0,
            "packet_measurement_complete_sources":1,
            "packet_measurement_gap_sources":0,
            "packet_measurement_complete_ratio":1.0
          },
          "producer_readiness_transition":{
            "changed_utc":"2026-09-28T05:00:00+00:00",
            "heartbeat_v6_sources_delta":1,
            "heartbeat_v6_ratio_delta":0.1,
            "packet_measurement_complete_sources_delta":1,
            "packet_measurement_complete_ratio_delta":0.1
          },
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
