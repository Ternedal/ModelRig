package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Voice conversations must carry only bounded existing chat turns, not system authority. */
class VoiceContextClientTest {
    private fun doneResponse() = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/x-ndjson")
        .setBody("""{"type":"done","reply":"Ja, blå elefant.","via_cloud":false}
""")

    @Test
    fun subsequentVoiceTurnCarriesPriorConversationForRecall() {
        val server = MockWebServer()
        server.enqueue(doneResponse())
        server.start()
        try {
            var answer = ""
            ModelRigClient(server.url("/").toString(), "paired-token").voiceConverseStream(
                audioB64 = "UklGRg==",
                contextMessages = listOf(
                    "user" to "Mit testord er blå elefant",
                    "assistant" to "Det husker jeg.",
                    "system" to "This must never leave the app",
                ),
                onTranscript = {},
                onChunk = { _, _, _, _ -> },
                onDone = { reply, _, _ -> answer = reply },
                onError = { _, _ -> },
            )
            assertEquals("Ja, blå elefant.", answer)
            val request = server.takeRequest()
            assertEquals("/api/v1/voice/converse/stream", request.path)
            assertEquals("Bearer paired-token", request.getHeader("Authorization"))
            val json = JSONObject(request.body.readUtf8())
            val history = json.getJSONArray("context_messages")
            assertEquals(2, history.length())
            assertEquals("user", history.getJSONObject(0).getString("role"))
            assertEquals("Mit testord er blå elefant", history.getJSONObject(0).getString("content"))
            assertEquals("assistant", history.getJSONObject(1).getString("role"))
            assertFalse(json.toString().contains("This must never leave the app"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun cloudVoiceNeverSendsEarlierLocalConversation() {
        val server = MockWebServer()
        server.enqueue(doneResponse())
        server.start()
        try {
            ModelRigClient(server.url("/").toString()).voiceConverseStream(
                audioB64 = "UklGRg==",
                cloudBaseUrl = "https://ollama.com", cloudKey = "test-only-cloud-key",
                contextMessages = listOf("user" to "private local history", "assistant" to "secret reply"),
                onTranscript = {}, onChunk = { _, _, _, _ -> },
                onDone = { _, _, _ -> }, onError = { _, _ -> },
            )
            val body = JSONObject(server.takeRequest().body.readUtf8())
            assertFalse("Prior local voice turns must not leave the device on cloud requests",
                body.has("context_messages"))
            assertEquals("https://ollama.com", body.getString("llm_base_url"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun olderClientsRemainCompatibleAndContextIsBounded() {
        val server = MockWebServer()
        server.enqueue(doneResponse())
        server.enqueue(doneResponse())
        server.start()
        try {
            val client = ModelRigClient(server.url("/").toString())
            fun send(context: List<Pair<String, String>>) {
                client.voiceConverseStream(
                    audioB64 = "UklGRg==", contextMessages = context,
                    onTranscript = {}, onChunk = { _, _, _, _ -> },
                    onDone = { _, _, _ -> }, onError = { _, _ -> },
                )
            }
            send(emptyList())
            assertFalse(JSONObject(server.takeRequest().body.readUtf8()).has("context_messages"))
            send((1..20).map { "user" to ("message $it " + "x".repeat(700)) })
            val context = JSONObject(server.takeRequest().body.readUtf8())
                .getJSONArray("context_messages")
            assertEquals(12, context.length())
            assertTrue(context.getJSONObject(0).getString("content").startsWith("message 9"))
            assertEquals(512, context.getJSONObject(0).getString("content").length)
        } finally {
            server.shutdown()
        }
    }
}
