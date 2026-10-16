package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/** Check the ACTUAL Android HTTP payload, not just a locally assembled mock. */
class VoiceHistoryClientTest {
    @Test
    fun streamingVoiceCarriesOnlyPriorUserAssistantTurns() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setBody(
                "{\"type\":\"transcript\",\"text\":\"Hvad husker du?\"}\n" +
                    "{\"type\":\"done\",\"reply\":\"blå elefant\",\"model\":\"test\",\"via_cloud\":false}\n",
            ),
        )
        server.start()
        try {
            var transcript = ""
            var answer = ""
            ModelRigClient(server.url("/").toString(), "paired-token").voiceConverseStream(
                audioB64 = "UklGRg==",
                history = listOf(
                    "user" to "Mit hemmelige testord er blå elefant.",
                    "assistant" to "Det husker jeg.",
                    "system" to "never forward me",
                    "user" to "   ",
                ),
                onTranscript = { transcript = it },
                onChunk = { _, _, _, _ -> fail("unexpected audio chunk") },
                onDone = { reply, _, _ -> answer = reply },
                onError = { _, detail -> fail("unexpected stream error: $detail") },
            )
            assertEquals("Hvad husker du?", transcript)
            assertEquals("blå elefant", answer)
            val req = server.takeRequest()
            assertEquals("POST", req.method)
            assertEquals("/api/v1/voice/converse/stream", req.path)
            assertEquals("Bearer paired-token", req.getHeader("Authorization"))
            val payload = JSONObject(req.body.readUtf8())
            assertEquals("UklGRg==", payload.getString("audio_base64"))
            val history = payload.getJSONArray("history")
            assertEquals(2, history.length())
            assertEquals("user", history.getJSONObject(0).getString("role"))
            assertEquals("Mit hemmelige testord er blå elefant.", history.getJSONObject(0).getString("content"))
            assertEquals("assistant", history.getJSONObject(1).getString("role"))
            assertEquals("Det husker jeg.", history.getJSONObject(1).getString("content"))
            assertFalse(payload.has("llm_api_key"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun bufferedVoiceAlsoCarriesHistory() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("{}"))
        server.start()
        try {
            ModelRigClient(server.url("/").toString(), "paired-token").voiceConverse(
                audioB64 = "UklGRg==",
                history = listOf("user" to "Husk blå elefant."),
            )
            val req = server.takeRequest()
            assertEquals("/api/v1/voice/converse", req.path)
            assertEquals("Bearer paired-token", req.getHeader("Authorization"))
            val history = JSONObject(req.body.readUtf8()).getJSONArray("history")
            assertEquals(1, history.length())
            assertEquals("Husk blå elefant.", history.getJSONObject(0).getString("content"))
        } finally {
            server.shutdown()
        }
    }


    @Test
    fun cloudVoiceDoesNotSerializePriorLocalConversation() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("{}"))
        server.start()
        try {
            ModelRigClient(server.url("/").toString(), "paired-token").voiceConverse(
                audioB64 = "UklGRg==",
                cloudBaseUrl = "https://ollama.com",
                cloudKey = "fake-test-key",
                history = listOf("user" to "Blå elefant er privat lokal historik"),
            )
            val payload = JSONObject(server.takeRequest().body.readUtf8())
            assertFalse("cloud voice must not upload local history", payload.has("history"))
            assertEquals("https://ollama.com", payload.getString("llm_base_url"))
            assertEquals("fake-test-key", payload.getString("llm_api_key"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun legacyStatelessVoiceDoesNotInheritAnotherConversation() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setBody("{}"))
        server.start()
        try {
            ModelRigClient(server.url("/").toString(), "paired-token").voiceConverse(
                audioB64 = "UklGRg==",
            )
            val payload = JSONObject(server.takeRequest().body.readUtf8())
            assertFalse("stateless requests must not send previous conversation data", payload.has("history"))
            assertTrue(payload.has("audio_base64"))
        } finally {
            server.shutdown()
        }
    }
}
