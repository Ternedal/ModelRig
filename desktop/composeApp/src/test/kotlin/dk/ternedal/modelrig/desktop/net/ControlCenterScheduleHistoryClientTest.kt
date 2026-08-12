package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ControlCenterScheduleHistoryClientTest {
    @Test
    fun authenticatedReadUsesControlCenterHistoryRoute() {
        val authorization = AtomicReference<String>()
        val path = AtomicReference<String>()
        val server = server { exchange ->
            authorization.set(exchange.requestHeaders.getFirst("Authorization"))
            path.set(exchange.requestURI.path)
            val body = validPayload().toByteArray()
            exchange.responseHeaders.add("Content-Type", "application/json")
            exchange.sendResponseHeaders(200, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val history = ControlCenterScheduleHistoryClient(
                "http://127.0.0.1:${server.address.port}",
                "desktop-token",
            ).history()

            assertEquals(ControlCenterScheduleHistoryClient.SCHEMA, history.schema)
            assertFalse(history.productionActivation)
            assertEquals("ready", history.occurrenceSource.state)
            assertEquals("ready", history.jobsSource.state)
            assertEquals(2, history.items.size)
            assertTrue(history.items.first().inFlight == true)
            assertEquals("executed", history.items.last().terminalOutcome)
            assertEquals("completed", history.items.last().job?.status)
            assertEquals("Bearer desktop-token", authorization.get())
            assertEquals("/api/v1/control-center/schedules", path.get())
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun jobObservationNeverRewritesOccurrenceOutcome() {
        val body = validPayload()
            .replace("\"occurrence_status\":\"executed\"", "\"occurrence_status\":\"released\"")
            .replace("\"terminal_outcome\":\"executed\"", "\"terminal_outcome\":\"not_run\"")
        val parsed = client().parse(body).items.last()

        assertEquals("released", parsed.occurrenceStatus)
        assertEquals("not_run", parsed.terminalOutcome)
        assertEquals("completed", parsed.job?.status)
    }

    @Test
    fun occurrenceCrossFieldContradictionsFailClosed() {
        assertInvalid(
            validPayload().replaceFirst("\"in_flight\":true", "\"in_flight\":false"),
            "pending occurrence state contradiction",
        )
        assertInvalid(
            validPayload().replace("\"terminal_outcome\":\"executed\"", "\"terminal_outcome\":\"not_run\""),
            "executed occurrence state contradiction",
        )
        val future = validPayload()
            .replace("\"occurrence_status\":\"executed\"", "\"occurrence_status\":\"unknown_schema_value\"")
            .replaceFirstAfterExecuted("\"in_flight\":false", "\"in_flight\":null")
            .replace("\"terminal_outcome\":\"executed\"", "\"terminal_outcome\":\"unknown\"")
        val parsed = client().parse(future).items.last()
        assertEquals("unknown_schema_value", parsed.occurrenceStatus)
        assertNull(parsed.inFlight)
        assertEquals("unknown", parsed.terminalOutcome)
        assertEquals("completed", parsed.job?.status)
    }

    @Test
    fun strictWireTypesRejectStringBooleanAndFractionalProgress() {
        assertRejected(
            validPayload().replace("\"production_activation\":false", "\"production_activation\":\"false\""),
        )
        assertRejected(
            validPayload().replaceFirst("\"in_flight\":true", "\"in_flight\":\"true\""),
        )
        assertRejected(
            validPayload().replace("\"progress_completed\":1", "\"progress_completed\":1.5"),
        )
    }

    @Test
    fun sourceStatesAndProductionActivationFailClosed() {
        assertInvalid(
            validPayload().replace("\"production_activation\":false", "\"production_activation\":true"),
            "production_activation must remain false",
        )
        assertInvalid(
            validPayload().replace(
                "\"occurrence_ledger\":{\"state\":\"ready\",\"reason\":null}",
                "\"occurrence_ledger\":{\"state\":\"unavailable\",\"reason\":\"database_missing\"}",
            ),
            "unavailable occurrence source cannot expose items",
        )
        assertInvalid(
            validPayload().replace(
                "\"jobs\":{\"state\":\"ready\",\"reason\":null}",
                "\"jobs\":{\"state\":\"not_required\",\"reason\":null}",
            ),
            "non-ready jobs source cannot expose job observations",
        )
        assertInvalid(
            validPayload().replace(
                "\"jobs\":{\"state\":\"ready\",\"reason\":null}",
                "\"jobs\":{\"state\":\"ready\",\"reason\":\"bad\"}",
            ),
            "ready source must not carry a reason",
        )
    }

    @Test
    fun duplicatesAndInvalidProgressFailClosed() {
        val duplicate = validPayload().replace("claim-executed", "claim-pending")
        assertInvalid(duplicate, "duplicate occurrence ids")
        val beyondTotal = validPayload()
            .replace("\"progress_completed\":1", "\"progress_completed\":3")
            .replace("\"progress_total\":1", "\"progress_total\":2")
        assertInvalid(beyondTotal, "job progress exceeds total")
        assertInvalid(
            validPayload().replace("\"progress_completed\":1", "\"progress_completed\":-1"),
            "job progress must be non-negative",
        )
        assertInvalid(
            validPayload().replace("\"job_id\":\"job-1\"", "\"job_id\":null"),
            "job observation lacks job_id",
        )
    }

    @Test
    fun unavailableSourcesRemainUnavailableInsteadOfEmptySuccess() {
        val body = """
            {
              "schema":"${ControlCenterScheduleHistoryClient.SCHEMA}",
              "generated_at":1900000000.0,
              "sources":{
                "occurrence_ledger":{"state":"unavailable","reason":"database_missing"},
                "jobs":{"state":"not_required","reason":null}
              },
              "items":[],
              "production_activation":false
            }
        """.trimIndent()
        val parsed = client().parse(body)
        assertEquals("unavailable", parsed.occurrenceSource.state)
        assertEquals("database_missing", parsed.occurrenceSource.reason)
        assertEquals("not_required", parsed.jobsSource.state)
        assertTrue(parsed.items.isEmpty())
    }

    @Test
    fun backendFailureRemainsErrorInsteadOfSyntheticHistory() {
        val server = server { exchange ->
            val body = "{\"error\":\"control center schedule history unavailable\"}".toByteArray()
            exchange.sendResponseHeaders(502, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        try {
            val error = runCatching {
                ControlCenterScheduleHistoryClient(
                    "http://127.0.0.1:${server.address.port}",
                    "desktop-token",
                ).history()
            }.exceptionOrNull()
            assertTrue(error is ControlCenterException)
            assertTrue(error.message.orEmpty().contains("(502)"))
            assertTrue(error.message.orEmpty().contains("schedule history unavailable"))
        } finally {
            server.stop(0)
        }
    }

    private fun client() = ControlCenterScheduleHistoryClient("http://127.0.0.1:1", "token")

    private fun assertRejected(body: String) {
        val error = runCatching { client().parse(body) }.exceptionOrNull()
        assertTrue(error is ControlCenterException, "wire type must fail closed; error=$error")
    }

    private fun assertInvalid(body: String, text: String) {
        val error = runCatching { client().parse(body) }.exceptionOrNull()
        assertTrue(error is ControlCenterException, "unexpected error: $error")
        assertTrue(error.message.orEmpty().contains(text), "${error.message} should contain $text")
    }

    private fun server(handler: (com.sun.net.httpserver.HttpExchange) -> Unit): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange -> handler(exchange) }
        server.start()
        return server
    }

    private fun String.replaceFirstAfterExecuted(old: String, new: String): String {
        val marker = "\"occurrence_status\":\"unknown_schema_value\""
        val markerIndex = indexOf(marker)
        check(markerIndex >= 0)
        val before = substring(0, markerIndex + marker.length)
        val after = substring(markerIndex + marker.length).replaceFirst(old, new)
        return before + after
    }

    private fun validPayload(): String = """
        {
          "schema":"kaliv-control-center-schedule-history/v1",
          "generated_at":1900000000.0,
          "sources":{
            "occurrence_ledger":{"state":"ready","reason":null},
            "jobs":{"state":"ready","reason":null}
          },
          "items":[
            {
              "occurrence_id":"claim-pending",
              "schedule_id":"0a1b2c3d4e5f",
              "tool":"note_append",
              "due_at":1900000010.0,
              "occurrence_status":"reserved",
              "in_flight":true,
              "terminal_outcome":null,
              "created_at":1900000000.0,
              "resolved_at":null,
              "job_id":null,
              "job":null
            },
            {
              "occurrence_id":"claim-executed",
              "schedule_id":"1a2b3c4d5e6f",
              "tool":"note_append",
              "due_at":1899000010.0,
              "occurrence_status":"executed",
              "in_flight":false,
              "terminal_outcome":"executed",
              "created_at":1899000000.0,
              "resolved_at":1899000020.0,
              "job_id":"job-1",
              "job":{
                "status":"completed",
                "kind":"schedule_tool_call",
                "progress_completed":1,
                "progress_total":1,
                "created_at":1899000001.0,
                "updated_at":1899000020.0
              }
            }
          ],
          "production_activation":false
        }
    """.trimIndent()
}
