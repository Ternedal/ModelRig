package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Anders 2026-10-26 (#2275): only the current user message may reach Ollama
 * Cloud, for text as for voice. These tests read the request body each client
 * actually sends.
 */
class CloudCurrentMessageOnlyTest {
    private val conversation = listOf(
        "system" to "Du er Kaliv.",
        "user" to "Mit lokale kodeord er kodeord-7731",
        "assistant" to "Det husker jeg.",
        "system" to "REPLAYED MID-CONVERSATION SYSTEM",
        "user" to "hvad er klokken",
    )

    @Test
    fun turnKeepsLeadingInstructionsAndCurrentMessageOnly() {
        assertEquals(
            listOf("system" to "Du er Kaliv.", "user" to "hvad er klokken"),
            cloudTurnMessages(conversation),
        )
    }

    @Test
    fun turnWithoutInstructionsIsJustTheCurrentMessage() {
        assertEquals(listOf("user" to "b"), cloudTurnMessages(listOf("user" to "a", "assistant" to "x", "user" to "b")))
    }

    @Test
    fun directCloudChatSendsOnlyCurrentMessageAndKeepsImage() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"message":{"content":"Tolv."},"done":true}""" + "\n"),
        )
        server.start()
        try {
            CloudClient("test-only-key", server.url("/").toString())
                .chatStream("gpt-oss:120b", conversation, imageB64 = "aW1n", onDelta = {})
            val body = JSONObject(server.takeRequest().body.readUtf8())
            val messages = body.getJSONArray("messages")
            assertEquals(2, messages.length())
            assertEquals("system", messages.getJSONObject(0).getString("role"))
            assertEquals("hvad er klokken", messages.getJSONObject(1).getString("content"))
            assertTrue("image stays on the current message", messages.getJSONObject(1).has("images"))
            assertFalse(body.toString().contains("kodeord-7731"))
            assertFalse(body.toString().contains("REPLAYED"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun toolsChatThroughRigOmitsHistoryInCloudModeOnly() {
        val server = MockWebServer()
        repeat(2) { server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"answered","answer":"OK"}""")) }
        server.start()
        try {
            val prior = listOf("user" to "Mit lokale kodeord er kodeord-7731", "assistant" to "Det husker jeg.")
            val client = ModelRigClient(server.url("/").toString())

            client.toolsChat("hvad er klokken", cloudBaseUrl = "https://ollama.com", cloudKey = "k", history = prior)
            val cloud = JSONObject(server.takeRequest().body.readUtf8())
            assertFalse(cloud.has("history"))
            assertFalse(cloud.toString().contains("kodeord-7731"))

            client.toolsChat("hvad er klokken", history = prior)
            val local = JSONObject(server.takeRequest().body.readUtf8())
            assertEquals("local tools turn keeps its history (control)", 2, local.getJSONArray("history").length())
        } finally {
            server.shutdown()
        }
    }
}
