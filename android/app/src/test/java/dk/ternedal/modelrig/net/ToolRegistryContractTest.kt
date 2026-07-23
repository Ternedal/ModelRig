package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ToolRegistryContractTest {
    @Test
    fun registryParsesSchedulerAxesAndMissingMetadataFailsClosed() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .addHeader("Content-Type", "application/json")
                .setBody(
                    """{
                      "enabled": true,
                      "tools": [
                        {
                          "name": "current_datetime",
                          "risk": "read",
                          "description": "clock",
                          "enabled": true,
                          "impact": "read",
                          "schedulable": true,
                          "unschedulable_reason": "",
                          "cancellation": "none",
                          "idempotent": true
                        },
                        {
                          "name": "delete_model",
                          "risk": "write",
                          "description": "delete",
                          "enabled": true,
                          "impact": "destructive",
                          "schedulable": false,
                          "unschedulable_reason": "destruktive handlinger kræver et menneske",
                          "cancellation": "none",
                          "idempotent": false
                        },
                        {
                          "name": "legacy_tool",
                          "risk": "read",
                          "description": "old response",
                          "enabled": true
                        },
                        {
                          "name": "disabled_read",
                          "risk": "read",
                          "description": "disabled",
                          "enabled": false,
                          "schedulable": true
                        },
                        {
                          "name": "string_flags",
                          "risk": "read",
                          "description": "malformed",
                          "enabled": "true",
                          "schedulable": "true",
                          "idempotent": "true"
                        }
                      ]
                    }""".trimIndent(),
                ),
        )
        server.start()
        try {
            val registry = ModelRigClient(server.url("/").toString(), "device-token").toolsList()
            val tools = registry.tools.associateBy { it.name }

            val current = tools.getValue("current_datetime")
            assertTrue(current.schedulable)
            assertTrue(current.canSchedule)
            assertNull(current.scheduleBlockReason)
            assertEquals("read", current.impact)
            assertEquals("none", current.cancellation)
            assertEquals(true, current.idempotent)

            val destructive = tools.getValue("delete_model")
            assertFalse(destructive.canSchedule)
            assertEquals(
                "destruktive handlinger kræver et menneske",
                destructive.scheduleBlockReason,
            )

            val legacy = tools.getValue("legacy_tool")
            assertFalse(legacy.schedulable)
            assertFalse(legacy.canSchedule)
            assertEquals(
                "Riggen har ikke markeret værktøjet som planlægbart.",
                legacy.scheduleBlockReason,
            )
            assertNull(legacy.idempotent)

            val disabled = tools.getValue("disabled_read")
            assertFalse(disabled.canSchedule)
            assertEquals("Værktøjet er slået fra på riggen.", disabled.scheduleBlockReason)

            val stringFlags = tools.getValue("string_flags")
            assertFalse(stringFlags.enabled)
            assertFalse(stringFlags.schedulable)
            assertFalse(stringFlags.canSchedule)
            assertNull(stringFlags.idempotent)
            assertEquals(
                "Riggen har ikke markeret værktøjet som planlægbart.",
                stringFlags.scheduleBlockReason,
            )

            val request = server.takeRequest()
            assertEquals("/api/v1/tools", request.path)
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }
}
