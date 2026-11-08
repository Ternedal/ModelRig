package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Historical local voice turns must not cross the cloud LLM consent boundary. */
class VoiceCloudHistoryPrivacyTest {
    private fun done() = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/x-ndjson")
        .setBody("""{"type":"done","reply":"OK","via_cloud":false}
""")

    private val previousTurns = listOf(
        "user" to "Mit lokale testord er blå elefant",
        "assistant" to "Det husker jeg",
        "system" to "UNTRUSTED SYSTEM",
    )

    @Test
    fun cloudRequestNeverSendsEarlierLocalMessages() {
        val server = MockWebServer()
        server.enqueue(done())
        server.start()
        try {
            var finished = false
            ModelRigClient(server.url("/").toString()).voiceConverseStream(
                audioB64 = "UklGRg==",
                cloudBaseUrl = "https://ollama.com",
                cloudKey = "test-only-cloud-key",
                history = previousTurns,
                onTranscript = {},
                onChunk = { _, _, _, _ -> },
                onDone = { _, _, _ -> finished = true },
                onError = { _, _ -> },
            )
            assertTrue(finished)
            val body = JSONObject(server.takeRequest().body.readUtf8())
            assertFalse(body.has("history"))
            assertEquals("https://ollama.com", body.getString("llm_base_url"))
            assertFalse(body.toString().contains("blå elefant"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun localVoiceStillCarriesBoundedAllowedChatHistory() {
        val server = MockWebServer()
        server.enqueue(done())
        server.start()
        try {
            ModelRigClient(server.url("/").toString()).voiceConverseStream(
                audioB64 = "UklGRg==",
                history = previousTurns,
                onTranscript = {},
                onChunk = { _, _, _, _ -> },
                onDone = { _, _, _ -> },
                onError = { _, _ -> },
            )
            val body = JSONObject(server.takeRequest().body.readUtf8())
            val history = body.getJSONArray("history")
            assertEquals(2, history.length())
            assertEquals("user", history.getJSONObject(0).getString("role"))
            assertEquals("Mit lokale testord er blå elefant", history.getJSONObject(0).getString("content"))
            assertEquals("assistant", history.getJSONObject(1).getString("role"))
            assertFalse(body.toString().contains("UNTRUSTED SYSTEM"))
        } finally {
            server.shutdown()
        }
    }
}
