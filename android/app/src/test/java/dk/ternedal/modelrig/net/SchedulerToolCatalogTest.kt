package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SchedulerToolCatalogTest {
    @Test
    fun enabledSchedulableToolIsSelectable() {
        val catalog = parseSchedulerToolCatalog(
            registry(
                enabled = true,
                tools = JSONArray().put(tool("current_datetime", enabled = true, schedulable = true)),
            ),
        )

        assertTrue(catalog.enabled)
        assertNull(catalog.metadataError)
        assertEquals(1, catalog.tools.size)
        assertTrue(catalog.tools.single().selectable)
        assertNull(catalog.tools.single().disabledReason)
    }

    @Test
    fun unschedulableToolUsesServerReasonAndCannotBeSelected() {
        val reason = "sletning af en model er uigenkaldelig"
        val catalog = parseSchedulerToolCatalog(
            registry(
                enabled = true,
                tools = JSONArray().put(
                    tool("delete_model", enabled = true, schedulable = false)
                        .put("unschedulable_reason", reason),
                ),
            ),
        )

        val row = catalog.tools.single()
        assertFalse(row.selectable)
        assertEquals(reason, row.disabledReason)
    }

    @Test
    fun missingSchedulableMetadataFailsClosed() {
        val raw = tool("legacy_tool", enabled = true, schedulable = true)
        raw.remove("schedulable")

        val row = parseSchedulerToolCatalog(
            registry(enabled = true, tools = JSONArray().put(raw)),
        ).tools.single()

        assertFalse(row.selectable)
        assertTrue(row.disabledReason.orEmpty().contains("schedulable-metadata"))
    }

    @Test
    fun missingEnabledMetadataFailsClosed() {
        val raw = tool("legacy_tool", enabled = true, schedulable = true)
        raw.remove("enabled")

        val row = parseSchedulerToolCatalog(
            registry(enabled = true, tools = JSONArray().put(raw)),
        ).tools.single()

        assertFalse(row.selectable)
        assertTrue(row.disabledReason.orEmpty().contains("enabled-metadata"))
    }

    @Test
    fun unschedulableWithoutReasonFailsClosedWithExplanation() {
        val row = parseSchedulerToolCatalog(
            registry(
                enabled = true,
                tools = JSONArray().put(tool("cancel_job", enabled = true, schedulable = false)),
            ),
        ).tools.single()

        assertFalse(row.selectable)
        assertTrue(row.disabledReason.orEmpty().contains("mangler en forklaring"))
    }

    @Test
    fun disabledRegistryBlocksOtherwiseSchedulableTools() {
        val catalog = parseSchedulerToolCatalog(
            registry(
                enabled = false,
                tools = JSONArray().put(tool("current_datetime", enabled = true, schedulable = true)),
            ),
        )

        assertFalse(catalog.enabled)
        assertFalse(catalog.tools.single().selectable)
        assertEquals("Værktøjslaget er slået fra på riggen.", catalog.tools.single().disabledReason)
    }

    @Test
    fun missingToolArrayBlocksCatalog() {
        val catalog = parseSchedulerToolCatalog(JSONObject().put("enabled", true))

        assertFalse(catalog.enabled)
        assertTrue(catalog.tools.isEmpty())
        assertTrue(catalog.metadataError.orEmpty().contains("tool-liste"))
    }

    @Test
    fun malformedToolRowRemainsVisibleButDisabled() {
        val catalog = parseSchedulerToolCatalog(
            registry(enabled = true, tools = JSONArray().put("not-an-object")),
        )

        assertEquals(1, catalog.tools.size)
        assertFalse(catalog.tools.single().selectable)
        assertTrue(catalog.tools.single().name.startsWith("Ukendt værktøj"))
        assertTrue(catalog.tools.single().disabledReason.orEmpty().contains("ugyldig"))
    }

    @Test
    fun loaderUsesAuthenticatedExistingToolsEndpoint() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .addHeader("Content-Type", "application/json")
                .setBody(
                    registry(
                        enabled = true,
                        tools = JSONArray().put(tool("current_datetime", true, true)),
                    ).toString(),
                ),
        )
        server.start()
        try {
            val catalog = SchedulerToolCatalogLoader(server.url("/").toString(), "device-test-value").load()
            assertTrue(catalog.tools.single().selectable)

            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertEquals("/api/v1/tools", request.path)
            assertEquals("Bearer device-test-value", request.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    private fun registry(enabled: Boolean, tools: JSONArray) = JSONObject()
        .put("enabled", enabled)
        .put("tools", tools)

    private fun tool(name: String, enabled: Boolean, schedulable: Boolean) = JSONObject()
        .put("name", name)
        .put("description", "description for $name")
        .put("enabled", enabled)
        .put("schedulable", schedulable)
        .put("unschedulable_reason", if (schedulable) "" else JSONObject.NULL)
}
