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
    fun historyUsesAuthenticatedGetOnlyOutcomeEndpoint() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(historyPayload().toString()))
        server.start()
        try {
            val history = ControlCenterScheduleHistoryClient(
                server.url("/").toString(),
                "paired-history-token",
            ).history()

            assertEquals("ready", history.occurrenceSource.state)
            assertEquals("ready", history.jobsSource.state)
            assertEquals(1, history.items.size)
            val item = history.items.single()
            assertEquals("released", item.occurrenceStatus)
            assertFalse(item.inFlight ?: true)
            assertEquals("not_run", item.terminalOutcome)
            assertEquals("completed", item.job?.status)

            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertEquals("/api/v1/control-center/schedules", request.path)
            assertEquals("Bearer paired-history-token", request.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun topLevelAndSourcesFailClosedOnSchemaActivationAndContradictions() {
        val client = client()

        assertInvalid(client, historyPayload().put("schema", "future/v9"), "wrong schema")
        assertInvalid(
            client,
            historyPayload().put("production_activation", true),
            "production activation must remain false",
        )
        assertInvalid(
            client,
            historyPayload().put("production_activation", "false"),
            "production_activation must be boolean",
        )
        assertInvalid(
            client,
            historyPayload().put("unexpected", "field"),
            "history fields do not match the v1 contract",
        )

        val unknownSource = historyPayload()
        unknownSource.getJSONObject("sources").getJSONObject("occurrence_ledger")
            .put("state", "future_ready")
        assertInvalid(client, unknownSource, "unknown occurrence_ledger source state")

        val unavailableWithoutReason = historyPayload()
        unavailableWithoutReason.getJSONObject("sources").getJSONObject("occurrence_ledger")
            .put("state", "unavailable")
            .put("reason", JSONObject.NULL)
        unavailableWithoutReason.put("items", JSONArray())
        assertInvalid(client, unavailableWithoutReason, "lacks a reason")

        val readyWithReason = historyPayload()
        readyWithReason.getJSONObject("sources").getJSONObject("jobs")
            .put("reason", "should not be here")
        assertInvalid(client, readyWithReason, "jobs source reason contradicts state")
    }

    @Test
    fun occurrenceStatusRelationshipsAreStrictAndUnknownStaysUnknown() {
        val client = client()

        val reservedWrong = noJobHistory(
            occurrence("reserved", inFlight = false, terminalOutcome = null, withJob = false),
        )
        assertInvalid(client, reservedWrong, "in_flight contradicts occurrence status")

        val executedWrong = noJobHistory(
            occurrence("executed", inFlight = false, terminalOutcome = "not_run", withJob = false),
        )
        assertInvalid(client, executedWrong, "terminal outcome contradicts occurrence status")

        val unknownWrong = noJobHistory(
            occurrence(
                "unknown_schema_value",
                inFlight = false,
                terminalOutcome = "unknown",
                withJob = false,
            ),
        )
        assertInvalid(client, unknownWrong, "in_flight contradicts occurrence status")

        val unknown = client.parseHistory(
            noJobHistory(
                occurrence(
                    "unknown_schema_value",
                    inFlight = null,
                    terminalOutcome = "unknown",
                    withJob = false,
                ),
            ),
        ).items.single()
        assertNull(unknown.inFlight)
        assertEquals("unknown", unknown.terminalOutcome)
    }

    @Test
    fun observedJobNeverOverridesOccurrenceLedgerOutcome() {
        val client = client()
        val releasedWithCompletedJob = client.parseHistory(historyPayload()).items.single()
        assertEquals("released", releasedWithCompletedJob.occurrenceStatus)
        assertEquals("not_run", releasedWithCompletedJob.terminalOutcome)
        assertEquals("completed", releasedWithCompletedJob.job?.status)

        val executedWithFailedJobPayload = historyPayload()
        val row = executedWithFailedJobPayload.getJSONArray("items").getJSONObject(0)
        row.put("occurrence_status", "executed")
            .put("terminal_outcome", "executed")
        row.getJSONObject("job").put("status", "failed")
        val executedWithFailedJob = client.parseHistory(executedWithFailedJobPayload).items.single()
        assertEquals("executed", executedWithFailedJob.terminalOutcome)
        assertEquals("failed", executedWithFailedJob.job?.status)
    }

    @Test
    fun scalarTypesJobEnumsAndExactFieldsAreRejected() {
        val client = client()

        val stringInFlight = historyPayload()
        stringInFlight.getJSONArray("items").getJSONObject(0).put("in_flight", "false")
        assertInvalid(client, stringInFlight, "in_flight must be boolean or null")

        val floatProgress = historyPayload()
        floatProgress.getJSONArray("items").getJSONObject(0).getJSONObject("job")
            .put("progress_completed", 1.0)
        assertInvalid(client, floatProgress, "progress_completed must be an integer")

        val stringTimestamp = historyPayload()
        stringTimestamp.getJSONArray("items").getJSONObject(0).put("created_at", "1999999900")
        assertInvalid(client, stringTimestamp, "created_at must be numeric")

        val unknownJob = historyPayload()
        unknownJob.getJSONArray("items").getJSONObject(0).getJSONObject("job")
            .put("status", "future_success")
        assertInvalid(client, unknownJob, "unknown job status")

        val extraJobField = historyPayload()
        extraJobField.getJSONArray("items").getJSONObject(0).getJSONObject("job")
            .put("detail", "private payload")
        assertInvalid(client, extraJobField, "job fields do not match the v1 contract")
    }

    @Test
    fun sourceBindingAndDuplicateOccurrencesCannotBecomeAmbiguous() {
        val client = client()

        val noIdWithJob = historyPayload()
        noIdWithJob.getJSONArray("items").getJSONObject(0).put("job_id", JSONObject.NULL)
        assertInvalid(client, noIdWithJob, "job observation lacks job_id")

        val unavailableJobsWithObservation = historyPayload()
        unavailableJobsWithObservation.getJSONObject("sources").getJSONObject("jobs")
            .put("state", "unavailable")
            .put("reason", "database_missing")
        assertInvalid(client, unavailableJobsWithObservation, "cannot provide job observations")

        val notRequiredWithReference = historyPayload()
        notRequiredWithReference.getJSONObject("sources").getJSONObject("jobs")
            .put("state", "not_required")
        assertInvalid(client, notRequiredWithReference, "despite referenced jobs")

        val duplicate = historyPayload()
        val first = duplicate.getJSONArray("items").getJSONObject(0)
        duplicate.getJSONArray("items").put(JSONObject(first.toString()))
        assertInvalid(client, duplicate, "duplicate occurrence ids")

        val unavailableLedger = historyPayload()
        unavailableLedger.getJSONObject("sources").getJSONObject("occurrence_ledger")
            .put("state", "unavailable")
            .put("reason", "database_missing")
        assertInvalid(client, unavailableLedger, "cannot provide items")
    }

    @Test
    fun backendFailureDoesNotBecomeEmptyHistory() {
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
            assertEquals(1, server.requestCount)
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
        val error = runCatching { client.parseHistory(payload) }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertTrue("${error?.message} should contain $text", error?.message.orEmpty().contains(text))
    }

    private fun historyPayload(): JSONObject = JSONObject()
        .put("schema", "kaliv-control-center-schedule-history/v1")
        .put("generated_at", 2_000_000_000.0)
        .put(
            "sources",
            JSONObject()
                .put("occurrence_ledger", source("ready"))
                .put("jobs", source("ready")),
        )
        .put(
            "items",
            JSONArray().put(
                occurrence(
                    status = "released",
                    inFlight = false,
                    terminalOutcome = "not_run",
                    withJob = true,
                ),
            ),
        )
        .put("production_activation", false)

    private fun noJobHistory(item: JSONObject): JSONObject = JSONObject()
        .put("schema", "kaliv-control-center-schedule-history/v1")
        .put("generated_at", 2_000_000_000.0)
        .put(
            "sources",
            JSONObject()
                .put("occurrence_ledger", source("ready"))
                .put("jobs", source("not_required")),
        )
        .put("items", JSONArray().put(item))
        .put("production_activation", false)

    private fun source(state: String): JSONObject = JSONObject()
        .put("state", state)
        .put("reason", JSONObject.NULL)

    private fun occurrence(
        status: String,
        inFlight: Boolean?,
        terminalOutcome: String?,
        withJob: Boolean,
    ): JSONObject = JSONObject()
        .put("occurrence_id", "0123456789abcdef0123456789abcdef")
        .put("schedule_id", "0a1b2c3d4e5f")
        .put("tool", "note_append")
        .put("due_at", 1_999_999_940.0)
        .put("occurrence_status", status)
        .put("in_flight", inFlight ?: JSONObject.NULL)
        .put("terminal_outcome", terminalOutcome ?: JSONObject.NULL)
        .put("created_at", 1_999_999_945.0)
        .put("resolved_at", if (inFlight == true) JSONObject.NULL else 1_999_999_950.0)
        .put("job_id", if (withJob) "job000000001" else JSONObject.NULL)
        .put(
            "job",
            if (withJob) {
                JSONObject()
                    .put("status", "completed")
                    .put("kind", "schedule")
                    .put("progress_completed", 1)
                    .put("progress_total", 1)
                    .put("created_at", 1_999_999_946.0)
                    .put("updated_at", 1_999_999_950.0)
            } else {
                JSONObject.NULL
            },
        )

    private fun jsonResponse(body: String) = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/json")
        .setBody(body)
}
