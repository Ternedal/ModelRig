package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControlCenterClientTest {
    @Test
    fun authenticatedReadPreservesServerStatesWithoutLocalRecalculation() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(validStatus().toString()))
        server.start()
        try {
            val client = ControlCenterClient(server.url("/").toString(), "device-token")
            val status = client.status()

            assertEquals(ControlCenterClient.SCHEMA, status.schema)
            assertEquals("attention", status.overall)
            assertFalse(status.green)
            assertEquals("healthy", status.components.getValue("backend").state)
            assertEquals("stale", status.components.getValue("models").state)
            assertFalse(status.components.getValue("models").green)
            assertEquals("disabled", status.components.getValue("agent3").state)
            assertEquals("fallback", status.routing.state)
            assertEquals("readiness report expired", status.routing.fallbackReason)
            assertEquals(listOf("models"), status.requiredFailures)

            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertEquals("/api/v1/control-center/status", request.path)
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun parserRejectsSchemaAndGreenContradictions() {
        val client = ControlCenterClient("http://127.0.0.1:1", "token")

        val wrongSchema = validStatus().put("schema", "kaliv-control-center-status/v9")
        assertInvalid(client, wrongSchema, "unsupported schema")

        val overallContradiction = validStatus().put("overall", "healthy").put("green", false)
        assertInvalid(client, overallContradiction, "overall/green contradiction")

        val componentContradiction = validStatus()
        componentContradiction.getJSONObject("components")
            .getJSONObject("worker")
            .put("state", "stale")
            .put("green", true)
        assertInvalid(client, componentContradiction, "state/green contradiction")
    }

    @Test
    fun parserRejectsMissingEvidenceAndUnknownStates() {
        val client = ControlCenterClient("http://127.0.0.1:1", "token")

        val missingComponent = validStatus()
        missingComponent.getJSONObject("components").remove("backend")
        assertInvalid(client, missingComponent, "missing components")

        val healthyWithoutAge = validStatus()
        healthyWithoutAge.getJSONObject("components")
            .getJSONObject("worker")
            .put("age_s", JSONObject.NULL)
        assertInvalid(client, healthyWithoutAge, "lacks freshness evidence")

        val unknownState = validStatus()
        unknownState.getJSONObject("components")
            .getJSONObject("worker")
            .put("state", "super-green")
        assertInvalid(client, unknownState, "unsupported state")

        val fallbackWithoutReason = validStatus()
        fallbackWithoutReason.getJSONObject("routing")
            .put("fallback_reason", JSONObject.NULL)
        assertInvalid(client, fallbackWithoutReason, "lacks server reason")
    }

    @Test
    fun backendErrorsRemainErrorsInsteadOfSyntheticStatus() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(502)
                .addHeader("Content-Type", "application/json")
                .setBody("""{"error":"control center status unavailable"}"""),
        )
        server.start()
        try {
            val error = runCatching {
                ControlCenterClient(server.url("/").toString(), "token").status()
            }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertTrue(error?.message.orEmpty().contains("(502)"))
            assertTrue(error?.message.orEmpty().contains("status unavailable"))
        } finally {
            server.shutdown()
        }
    }

    private fun assertInvalid(client: ControlCenterClient, payload: JSONObject, text: String) {
        val error = runCatching { client.parse(payload) }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertTrue("${error?.message} should contain $text", error?.message.orEmpty().contains(text))
    }

    private fun validStatus(): JSONObject {
        val components = JSONObject()
            .put("backend", component("backend", required = true, state = "healthy", green = true))
            .put("worker", component("worker", required = true, state = "healthy", green = true))
            .put(
                "models",
                component(
                    "models",
                    required = true,
                    state = "stale",
                    green = false,
                    reason = "observation_too_old",
                ).put("age_s", 31.0),
            )
            .put(
                "agent3",
                component(
                    "agent3",
                    required = false,
                    state = "disabled",
                    green = false,
                    reason = "disabled_by_configuration",
                ),
            )

        val routing = JSONObject()
            .put("state", "fallback")
            .put("green", false)
            .put("configured_surface", "agent3_developer")
            .put("active_surface", "agent_v2")
            .put("fallback_reason", "readiness report expired")
            .put("observed_at", 2_000_000_000.0)
            .put("age_s", 1.0)
            .put("reason", "server_selected_fallback")

        return JSONObject()
            .put("schema", ControlCenterClient.SCHEMA)
            .put("generated_at", 2_000_000_001.0)
            .put("freshness_s", 30.0)
            .put("overall", "attention")
            .put("green", false)
            .put("components", components)
            .put("routing", routing)
            .put(
                "summary",
                JSONObject()
                    .put("states", JSONObject().put("healthy", 2).put("stale", 1).put("disabled", 1).put("fallback", 1))
                    .put("required_failures", JSONArray().put("models")),
            )
    }

    private fun component(
        name: String,
        required: Boolean,
        state: String,
        green: Boolean,
        reason: String? = null,
    ) = JSONObject()
        .put("name", name)
        .put("required", required)
        .put("state", state)
        .put("green", green)
        .put("observed_at", 2_000_000_000.0)
        .put("age_s", 1.0)
        .put("detail", "$name detail")
        .put("reason", reason ?: JSONObject.NULL)

    private fun jsonResponse(body: String) = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/json")
        .setBody(body)
}
