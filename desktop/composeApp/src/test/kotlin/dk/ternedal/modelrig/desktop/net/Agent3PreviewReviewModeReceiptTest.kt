package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicReference
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class Agent3PreviewReviewModeReceiptTest {
    @Test
    fun reviewedPreviewAcceptsMatchingTrueAndFalseReceiptsAndSendsExplicitMode() {
        listOf(true, false).forEach { expected ->
            val fixture = server("{\"review_reads\":$expected}")
            try {
                val preview = Agent3Client(fixture.baseUrl(), "token")
                    .previewPlan(message = "review this", reviewReads = expected)
                assertEquals(expected, preview.reviewReads)

                val request = Json.parseToJsonElement(fixture.requestBody.get()).jsonObject
                assertTrue("review_reads" in request)
                assertEquals(expected, request.getValue("review_reads").jsonPrimitive.boolean)
            } finally {
                fixture.server.stop(0)
            }
        }
    }

    @Test
    fun reviewedPreviewRejectsBothReviewModeMismatchDirections() {
        listOf(
            true to false,
            false to true,
        ).forEach { (requested, returned) ->
            val fixture = server("{\"review_reads\":$returned}")
            try {
                assertReceiptFailure(fixture, requested)
            } finally {
                fixture.server.stop(0)
            }
        }
    }

    @Test
    fun reviewedPreviewRejectsMissingNullStringAndNumberReceipts() {
        listOf(
            "{}",
            "{\"review_reads\":null}",
            "{\"review_reads\":\"false\"}",
            "{\"review_reads\":0}",
        ).forEach { response ->
            val fixture = server(response)
            try {
                assertReceiptFailure(fixture, expected = false)
            } finally {
                fixture.server.stop(0)
            }
        }
    }

    @Test
    fun genericPreviewKeepsMissingReceiptAndOmittedRequestCompatibility() {
        val fixture = server("{}")
        try {
            val preview = Agent3Client(fixture.baseUrl(), "token")
                .previewPlan(message = "generic preview")
            assertFalse(preview.reviewReads)

            val request = Json.parseToJsonElement(fixture.requestBody.get()).jsonObject
            assertFalse("review_reads" in request)
        } finally {
            fixture.server.stop(0)
        }
    }

    private fun assertReceiptFailure(fixture: Fixture, expected: Boolean) {
        val error = assertFailsWith<Agent3Exception> {
            Agent3Client(fixture.baseUrl(), "token")
                .previewPlan(message = "review this", reviewReads = expected)
        }
        assertEquals(
            "Invalid Agent 3.0 Preview envelope: server review_reads does not match reviewed intent",
            error.message,
        )
    }

    private data class Fixture(
        val server: HttpServer,
        val requestBody: AtomicReference<String>,
    ) {
        fun baseUrl(): String = "http://127.0.0.1:${server.address.port}"
    }

    private fun server(responseBody: String): Fixture {
        val requestBody = AtomicReference("")
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/v1/experimental/agent3") { exchange ->
            requestBody.set(exchange.requestBody.use { it.readBytes().toString(Charsets.UTF_8) })
            exchange.respond(200, responseBody)
        }
        server.start()
        return Fixture(server, requestBody)
    }

    private fun HttpExchange.respond(status: Int, body: String) {
        val bytes = body.toByteArray(Charsets.UTF_8)
        responseHeaders.add("Content-Type", "application/json")
        sendResponseHeaders(status, bytes.size.toLong())
        responseBody.use { it.write(bytes) }
    }
}
