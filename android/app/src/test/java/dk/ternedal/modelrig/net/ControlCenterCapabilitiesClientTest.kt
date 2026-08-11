package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControlCenterCapabilitiesClientTest {
    @Test
    fun authenticatedReadKeepsRuntimeEnablementOutsideCanonicalDescriptor() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(inventoryPayload().toString()))
        server.start()
        try {
            val inventory = ControlCenterCapabilitiesClient(
                server.url("/").toString(),
                "paired-device-token",
            ).inventory()

            assertTrue(inventory.toolLayerEnabled)
            assertEquals(2, inventory.capabilities.size)
            val models = inventory.capabilities.first { it.name == "list_models" }
            assertFalse(models.enabled)
            assertEquals("tool:list_models", models.capabilityId)
            assertEquals("read", models.access)
            assertEquals("operational", models.dataClass)
            assertEquals("configured_service", models.networkMode)
            assertEquals(listOf("ollama"), models.networkDestinations)
            assertFalse(models.schedulable)
            assertEquals("pilot only", models.schedulingReason)
            assertEquals("cooperative", models.terminationMode)
            assertTrue(models.idempotent)

            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertEquals("/api/v1/tools", request.path)
            assertEquals("Bearer paired-device-token", request.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun parserRejectsDescriptorRuntimeStateAndProductionActivation() {
        val client = client()

        val runtimeInsideDescriptor = inventoryPayload()
        runtimeInsideDescriptor.getJSONArray("tools")
            .getJSONObject(0)
            .getJSONObject("descriptor")
            .put("enabled", true)
        assertInvalid(client, runtimeInsideDescriptor, "unknown=[enabled]")

        val activated = inventoryPayload()
        activated.getJSONArray("tools")
            .getJSONObject(0)
            .getJSONObject("descriptor")
            .put("production_activation", true)
        assertInvalid(client, activated, "production activation must remain false")
    }

    @Test
    fun parserRejectsIdentitySchemaAndUnknownAxisValues() {
        val client = client()

        val wrongId = inventoryPayload()
        wrongId.getJSONArray("tools")
            .getJSONObject(0)
            .getJSONObject("descriptor")
            .put("capability_id", "tool:someone_else")
        assertInvalid(client, wrongId, "capability id mismatch")

        val wrongSchema = inventoryPayload()
        wrongSchema.getJSONArray("tools")
            .getJSONObject(0)
            .getJSONObject("descriptor")
            .put("schema", "kaliv-capability/v9")
        assertInvalid(client, wrongSchema, "unsupported descriptor schema")

        val unknownNetwork = inventoryPayload()
        unknownNetwork.getJSONArray("tools")
            .getJSONObject(0)
            .getJSONObject("descriptor")
            .getJSONObject("network")
            .put("mode", "vpn_magic")
        assertInvalid(client, unknownNetwork, "unsupported mode vpn_magic")
    }

    @Test
    fun parserRejectsSchedulingNetworkAndConfirmationContradictions() {
        val client = client()

        val schedulableWithReason = inventoryPayload()
        schedulableWithReason.getJSONArray("tools")
            .getJSONObject(0)
            .getJSONObject("descriptor")
            .getJSONObject("scheduling")
            .put("reason", "should not be here")
        assertInvalid(client, schedulableWithReason, "carries a refusal reason")

        val networkWithoutDestination = inventoryPayload()
        networkWithoutDestination.getJSONArray("tools")
            .getJSONObject(1)
            .getJSONObject("descriptor")
            .getJSONObject("network")
            .put("destinations", JSONArray())
        assertInvalid(client, networkWithoutDestination, "networked mode lacks a destination")

        val duplicateDestination = inventoryPayload()
        duplicateDestination.getJSONArray("tools")
            .getJSONObject(1)
            .getJSONObject("descriptor")
            .getJSONObject("network")
            .put("destinations", JSONArray().put("ollama").put("ollama"))
        assertInvalid(client, duplicateDestination, "contains duplicates")

        val publicReadWithoutConfirmation = inventoryPayload()
        val descriptor = publicReadWithoutConfirmation.getJSONArray("tools")
            .getJSONObject(0)
            .getJSONObject("descriptor")
        descriptor.getJSONObject("network")
            .put("mode", "public")
            .put("destinations", JSONArray().put("approved-public"))
        descriptor.getJSONObject("confirmation").put("mode", "none")
        assertInvalid(client, publicReadWithoutConfirmation, "confirmation contradicts access/network")
    }

    @Test
    fun parserRejectsWrongBooleanTypesAndDuplicateCapabilityIds() {
        val client = client()

        val wrongEnabledType = inventoryPayload().put("enabled", "true")
        assertInvalid(client, wrongEnabledType, "enabled must be boolean")

        val duplicateIds = inventoryPayload()
        val tools = duplicateIds.getJSONArray("tools")
        val duplicate = JSONObject(tools.getJSONObject(0).toString())
        tools.put(duplicate)
        assertInvalid(client, duplicateIds, "duplicate capability ids")
    }

    @Test
    fun httpFailureDoesNotBecomeSyntheticInventory() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(401)
                .addHeader("Content-Type", "application/json")
                .setBody("""{"error":"invalid token"}"""),
        )
        server.start()
        try {
            val error = runCatching {
                ControlCenterCapabilitiesClient(server.url("/").toString(), "bad-token").inventory()
            }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertTrue(error?.message.orEmpty().contains("(401)"))
            assertTrue(error?.message.orEmpty().contains("invalid token"))
        } finally {
            server.shutdown()
        }
    }

    private fun client() = ControlCenterCapabilitiesClient("http://127.0.0.1:1", "token")

    private fun assertInvalid(
        client: ControlCenterCapabilitiesClient,
        payload: JSONObject,
        text: String,
    ) {
        val error = runCatching { client.parse(payload) }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertTrue(
            "${error?.message} should contain $text",
            error?.message.orEmpty().contains(text),
        )
    }

    private fun inventoryPayload(): JSONObject = JSONObject()
        .put("enabled", true)
        .put("tools_dir", "/not-used-by-control-center")
        .put(
            "tools",
            JSONArray()
                .put(tool("current_datetime", enabled = true, descriptor = publicReadDescriptor()))
                .put(tool("list_models", enabled = false, descriptor = modelReadDescriptor())),
        )

    private fun tool(name: String, enabled: Boolean, descriptor: JSONObject) = JSONObject()
        .put("name", name)
        .put("risk", descriptor.getString("access"))
        .put("description", descriptor.getString("description"))
        .put("params", JSONObject())
        .put("enabled", enabled)
        .put("impact", descriptor.getString("impact"))
        .put("schedulable", descriptor.getJSONObject("scheduling").getBoolean("allowed"))
        .put("unschedulable_reason", descriptor.getJSONObject("scheduling").getString("reason"))
        .put("cancellation", descriptor.getJSONObject("termination").getString("mode"))
        .put("network", descriptor.getJSONObject("network").getString("mode"))
        .put("network_destinations", descriptor.getJSONObject("network").getJSONArray("destinations"))
        .put("idempotent", descriptor.getJSONObject("replay").getBoolean("idempotent"))
        .put("descriptor", descriptor)

    private fun publicReadDescriptor() = descriptor(
        name = "current_datetime",
        description = "Læs serverens aktuelle tid.",
        access = "read",
        impact = "read",
        dataClass = "public",
        isolationMode = "in_process",
        schedulable = true,
        schedulingReason = "",
        confirmation = "none",
        networkMode = "none",
        destinations = emptyList(),
        termination = "none",
        idempotent = true,
    )

    private fun modelReadDescriptor() = descriptor(
        name = "list_models",
        description = "Læs lokal modeloversigt.",
        access = "read",
        impact = "read",
        dataClass = "operational",
        isolationMode = "process",
        schedulable = false,
        schedulingReason = "pilot only",
        confirmation = "none",
        networkMode = "configured_service",
        destinations = listOf("ollama"),
        termination = "cooperative",
        idempotent = true,
    )

    private fun descriptor(
        name: String,
        description: String,
        access: String,
        impact: String,
        dataClass: String,
        isolationMode: String,
        schedulable: Boolean,
        schedulingReason: String,
        confirmation: String,
        networkMode: String,
        destinations: List<String>,
        termination: String,
        idempotent: Boolean,
    ) = JSONObject()
        .put("schema", ControlCenterCapabilitiesClient.SCHEMA)
        .put("capability_id", "tool:$name")
        .put("kind", "tool")
        .put("description", description)
        .put("access", access)
        .put("impact", impact)
        .put("data_class", dataClass)
        .put("parameters", JSONObject().put("type", "object").put("properties", JSONObject()))
        .put(
            "isolation",
            JSONObject()
                .put("mode", isolationMode)
                .put("env_allow", JSONArray()),
        )
        .put(
            "scheduling",
            JSONObject()
                .put("allowed", schedulable)
                .put("reason", schedulingReason),
        )
        .put("confirmation", JSONObject().put("mode", confirmation))
        .put(
            "network",
            JSONObject()
                .put("mode", networkMode)
                .put("destinations", JSONArray(destinations)),
        )
        .put("termination", JSONObject().put("mode", termination))
        .put("replay", JSONObject().put("idempotent", idempotent))
        .put("production_activation", false)

    private fun jsonResponse(body: String) = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/json")
        .setBody(body)
}
