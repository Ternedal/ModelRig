package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3PreviewReviewModeReceiptTest {
    @Test
    fun reviewedPreviewAcceptsMatchingTrueAndFalseReceipts() {
        listOf(true, false).forEach { expected ->
            val server = server("{\"review_reads\":$expected}")
            try {
                val preview = Agent3Client(server.url("/").toString(), "token")
                    .previewPlan(message = "review this", reviewReads = expected)
                assertEquals(expected, preview.reviewReads)

                val request = server.takeRequest()
                assertEquals("/api/v1/experimental/agent3/plan", request.path)
                assertEquals(
                    expected,
                    JSONObject(request.body.readUtf8()).getBoolean("review_reads"),
                )
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun reviewedPreviewRejectsBothReviewModeMismatchDirections() {
        listOf(
            true to false,
            false to true,
        ).forEach { (requested, returned) ->
            val server = server("{\"review_reads\":$returned}")
            try {
                assertReviewReceiptFailure(server, requested)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun reviewedPreviewRejectsMissingNullAndNonBooleanReceipts() {
        val bodies = listOf(
            "{}",
            "{\"review_reads\":null}",
            "{\"review_reads\":\"false\"}",
            "{\"review_reads\":0}",
        )
        bodies.forEach { body ->
            val server = server(body)
            try {
                assertReviewReceiptFailure(server, expected = false)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun genericPreviewKeepsPermissiveMissingReceiptCompatibility() {
        val server = server("{}")
        try {
            val preview = Agent3Client(server.url("/").toString(), "token")
                .previewPlan(message = "generic preview")
            assertEquals(false, preview.reviewReads)

            val request = JSONObject(server.takeRequest().body.readUtf8())
            assertEquals(false, request.getBoolean("review_reads"))
        } finally {
            server.shutdown()
        }
    }

    private fun assertReviewReceiptFailure(server: MockWebServer, expected: Boolean) {
        val error = runCatching {
            Agent3Client(server.url("/").toString(), "token")
                .previewPlan(message = "review this", reviewReads = expected)
        }.exceptionOrNull()
        assertTrue("Expected ModelRigException, got $error", error is ModelRigException)
        assertEquals(
            "Ugyldigt Agent 3.0 Preview-svar: serverens Read review matcher ikke den reviewede intent",
            error?.message,
        )
    }

    private fun server(body: String): MockWebServer = MockWebServer().also { server ->
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody(body),
        )
        server.start()
    }
}
