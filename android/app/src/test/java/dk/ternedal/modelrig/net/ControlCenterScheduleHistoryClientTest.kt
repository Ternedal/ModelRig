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

class ControlCenterScheduleHistoryClientTest {
    @Test
    fun historyUsesAuthenticatedReadOnlyControlCenterRoute() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(validPayload().toString()))
        server.start()
        try {
            val history = ControlCenterScheduleHistoryClient(
                server.url("/").toString(),
                "paired-token",
            ).history()

            assertEquals(ControlCenterScheduleHistoryClient.SCHEMA, history.schema)
            assertFalse(history.productionActivation)
            assertEquals("ready", history.occurrenceSource.state)
            assertEquals("ready", history.jobsSource.state)
            assertEquals(2, history.items.size)
            assertTrue(history.items.first().inFlight == true)
            assertEquals("executed", history.items.last().terminalOutcome)
            assertEquals("completed", history.items.last().job?.status)

            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertEquals("/api/v1/control-center/schedules", request.path)
            assertEquals("Bearer paired-token", request.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun occurrenceStateMustMatchInflightAndTerminalOutcome() {
        val client = client()

        assertInvalid(
            client,
            validPayload().also { firstItem(it).put("in_flight", false) },
            "pending occurrence state contradiction",
        )
        assertInvalid(
            client,
            validPayload().also { secondItem(it).put("terminal_outcome", "not_run") },
            "executed occurrence state contradiction",
        )
        assertInvalid(
            client,
            validPayload().also {
                secondItem(it)
                    .put("occurrence_status", "unknown_schema_value")
                    .put("in_flight", false)
                    .put("terminal_outcome", "unknown")
            },
            "future occurrence state must remain unknown",
        )
    }

    @Test
    fun futureOccurrenceStateCanOnlyRemainStructurallyUnknown() {
        val client = client()
        val payload = validPayload()
        val item = secondItem(payload)
            .put("occurrence_status", "unknown_schema_value")
            .put("in_flight", JSONObject.NULL)
            .put("terminal_outcome", "unknown")

        val parsed = client.parse(payload).items.last()
        assertEquals("unknown_schema_value", parsed.occurrenceStatus)
        assertNull(parsed.inFlight)
        assertEquals("unknown", parsed.terminalOutcome)
        assertEquals("completed", item.getJSONObject("job").getString("status"))
        assertEquals("completed", parsed.job?.status)
    }

    @Test
    fun jobObservationNeverOverridesOccurrenceOutcome() {
        val client = client()
        val payload = validPayload()
        secondItem(payload)
            .put("occurrence_status", "released")
            .put("in_flight", false)
            .put("terminal_outcome", "not_run")
            .getJSONObject("job")
            .put("status", "completed")

        val parsed = client.parse(payload).items.last()
        assertEquals("not_run", parsed.terminalOutcome)
        assertEquals("completed", parsed.job?.status)
    }

    @Test
    fun sourceStateAndProductionActivationFailClosed() {
        val client = client()

        assertInvalid(
            client,
            validPayload().put("production_activation", true),
            "production_activation must remain false",
        )
        assertInvalid(
            client,
            validPayload().also {
                it.getJSONObject("sources").getJSONObject("occurrence_ledger")
                    .put("state", "unavailable")
                    .put("reason", "database_missing")
            },
            "unavailable occurrence source cannot expose items",
        )
        assertInvalid(
            client,
            validPayload().also {
                it.getJSONObject("sources").getJSONObject("jobs")
                    .put("state", "not_required")
                    .put("reason", JSONObject.NULL)
            },
            "non-ready jobs source cannot expose job observations",
        )
        assertInvalid(
            client,
            validPayload().also {
                it.getJSONObject("sources").getJSONObject("jobs")
                    .put("state", "ready")
                    .put("reason", "should-not-be-here")
            },
            "ready source must not carry a reason",
        )
    }

    @Test
    fun malformedWireTypesAndProgressAreRejected() {
        val client = client()

        assertInvalid(
            client,
            validPayload().put("production_activation", "false"),
            "production_activation must be boolean",
        )
        assertInvalid(
            client,
            validPayload().also { firstItem(it).put("in_flight", "true") },
            "in_flight must be boolean or null",
        )
        assertInvalid(
            client,
            validPayload().also {
                secondItem(it).getJSONObject("job").put("progress_completed", 1.5)
            },
            "progress_completed must be an integer",
        )
        assertInvalid(
            client,
            validPayload().also {
                secondItem(it).getJSONObject("job")
                    .put("progress_completed", 3)
                    .put("progress_total", 2)
            },
            "job progress exceeds total",
        )
    }

    @Test
    fun duplicateOccurrencesAndJobWithoutIdentityAreRejected() {
        val client = client()

        val duplicate = validPayload()
        secondItem(duplicate).put("occurrence_id", firstItem(duplicate).getString("occurrence_id"))
        assertInvalid(client, duplicate, "duplicate occurrence ids")

        val missingJobId = validPayload()
        secondItem(missingJobId).put("job_id", JSONObject.NULL)
        assertInvalid(client, missingJobId, "job observation lacks job_id")
    }

    @Test
    fun unavailableSourcesCanBeShownWithoutInventingEmptySuccess() {
        val client = client()
        val payload = JSONObject()
            .put("schema", ControlCenterScheduleHistoryClient.SCHEMA)
            .put("generated_at", 1_900_000_000.0)
            .put(
                "sources",
                JSONObject()
                    .put(
                        "occurrence_ledger",
                        JSONObject().put("state", "unavailable").put("reason", "database_missing"),
                    )
                    .put(
                        "jobs",
                        JSONObject().put("state", "not_required").put("reason", JSONObject.NULL),
                    ),
            )
            .put("items", JSONArray())
            .put("production_activation", false)

        val parsed = client.parse(payload)
        assertEquals("unavailable", parsed.occurrenceSource.state)
        assertEquals("database_missing", parsed.occurrenceSource.reason)
        assertEquals("not_required", parsed.jobsSource.state)
        assertTrue(parsed.items.isEmpty())
    }

    @Test
    fun httpFailureDoesNotBecomeEmptyHistory() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(502)
                .addHeader("Content-Type", "application/json")
                .setBody("""{"error":"control center schedule history unavailable"}"""),
        )
        server.start()
        try {
            val error = runCatching {
                ControlCenterScheduleHistoryClient(server.url("/").toString(), "token").history()
            }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertTrue(error?.message.orEmpty().contains("(502)"))
            assertTrue(error?.message.orEmpty().contains("schedule history unavailable"))
        } finally {
            server.shutdown()
        }
    }

    private fun client() = ControlCenterScheduleHistoryClient("http://127.0.0.1:1", "token")

    private fun assertInvalid(
        client: ControlCenterScheduleHistoryClient,
        payload: JSONObject,
        text: String,
    ) {
        val error = runCatching { client.parse(payload) }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertTrue("${error?.message} should contain $text", error?.message.orEmpty().contains(text))
    }

    private fun validPayload() = JSONObject()
        .put("schema", ControlCenterScheduleHistoryClient.SCHEMA)
        .put("generated_at", 1_900_000_000.0)
        .put(
            "sources",
            JSONObject()
                .put(
                    "occurrence_ledger",
                    JSONObject().put("state", "ready").put("reason", JSONObject.NULL),
                )
                .put(
                    "jobs",
                    JSONObject().put("state", "ready").put("reason", JSONObject.NULL),
                ),
        )
        .put(
            "items",
            JSONArray()
                .put(
                    JSONObject()
                        .put("occurrence_id", "claim-pending")
                        .put("schedule_id", "0a1b2c3d4e5f")
                        .put("tool", "note_append")
                        .put("due_at", 1_900_000_010.0)
                        .put("occurrence_status", "reserved")
                        .put("in_flight", true)
                        .put("terminal_outcome", JSONObject.NULL)
                        .put("created_at", 1_900_000_000.0)
                        .put("resolved_at", JSONObject.NULL)
                        .put("job_id", JSONObject.NULL)
                        .put("job", JSONObject.NULL),
                )
                .put(
                    JSONObject()
                        .put("occurrence_id", "claim-executed")
                        .put("schedule_id", "1a2b3c4d5e6f")
                        .put("tool", "note_append")
                        .put("due_at", 1_899_000_010.0)
                        .put("occurrence_status", "executed")
                        .put("in_flight", false)
                        .put("terminal_outcome", "executed")
                        .put("created_at", 1_899_000_000.0)
                        .put("resolved_at", 1_899_000_020.0)
                        .put("job_id", "job-1")
                        .put(
                            "job",
                            JSONObject()
                                .put("status", "completed")
                                .put("kind", "schedule_tool_call")
                                .put("progress_completed", 1)
                                .put("progress_total", 1)
                                .put("created_at", 1_899_000_001.0)
                                .put("updated_at", 1_899_000_020.0),
                        ),
                ),
        )
        .put("production_activation", false)

    private fun firstItem(payload: JSONObject) = payload.getJSONArray("items").getJSONObject(0)
    private fun secondItem(payload: JSONObject) = payload.getJSONArray("items").getJSONObject(1)

    private fun jsonResponse(body: String) = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/json")
        .setBody(body)
}
