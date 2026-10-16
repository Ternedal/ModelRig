package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * A voice NDJSON terminal event is authoritative. Transport EOF can lag behind
 * the terminal line; in particular a proxy may leave the HTTP body open.
 * The reader must not dispatch late events or wait for the socket to close.
 */
class VoiceStreamTerminalTest {
    private fun response(body: String): MockResponse = MockResponse()
        .setResponseCode(200)
        .addHeader("Content-Type", "application/x-ndjson")
        .setBody(body)

    @Test
    fun doneStopsReadingBeforeTrailingEvents() {
        val server = MockWebServer()
        server.enqueue(response(
            """{"type":"transcript","text":"Hej"}
{"type":"chunk","index":0,"text":"Goddag!","audio_base64":"UklGRg=="}
{"type":"done","reply":"Goddag!","model":"gemma4:26b","via_cloud":false}
{"type":"error","status":502,"detail":"late proxy failure"}
{"type":"chunk","index":1,"text":"SHOULD NOT ARRIVE","audio_base64":""}
"""
        ))
        server.start()
        try {
            val events = mutableListOf<String>()
            ModelRigClient(server.url("/").toString(), "paired-token").voiceConverseStream(
                audioB64 = "UklGRg==",
                onTranscript = { events.add("transcript:$it") },
                onChunk = { _, text, _, _ -> events.add("chunk:$text") },
                onDone = { reply, model, viaCloud ->
                    events.add("done:$reply:$model:$viaCloud")
                },
                onError = { status, _ -> events.add("error:$status") },
            )
            assertEquals(
                listOf("transcript:Hej", "chunk:Goddag!", "done:Goddag!:gemma4:26b:false"),
                events,
            )
            val request = server.takeRequest()
            assertEquals("/api/v1/voice/converse/stream", request.path)
            assertEquals("Bearer paired-token", request.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun errorStopsReadingBeforeLateSuccess() {
        val server = MockWebServer()
        server.enqueue(response(
            """{"type":"error","status":503,"detail":"ASR unavailable"}
{"type":"done","reply":"SHOULD NOT ARRIVE","via_cloud":false}
"""
        ))
        server.start()
        try {
            val events = mutableListOf<String>()
            ModelRigClient(server.url("/").toString()).voiceConverseStream(
                audioB64 = "UklGRg==",
                onTranscript = { events.add("transcript") },
                onChunk = { _, _, _, _ -> events.add("chunk") },
                onDone = { _, _, _ -> events.add("done") },
                onError = { status, detail -> events.add("error:$status:$detail") },
            )
            assertEquals(listOf("error:503:ASR unavailable"), events)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun eofWithoutTerminalRemainsAnErrorEvenWithHttp200() {
        val server = MockWebServer()
        server.enqueue(response("""{"type":"transcript","text":"Hej"}
"""))
        server.start()
        try {
            var sawTranscript = false
            val result = runCatching {
                ModelRigClient(server.url("/").toString()).voiceConverseStream(
                    audioB64 = "UklGRg==",
                    onTranscript = { sawTranscript = true },
                    onChunk = { _, _, _, _ -> },
                    onDone = { _, _, _ -> },
                    onError = { _, _ -> },
                )
            }
            assertTrue(sawTranscript)
            assertTrue(result.exceptionOrNull() is ModelRigException)
            assertTrue(result.exceptionOrNull()?.message.orEmpty().contains("afbrudt"))
        } finally {
            server.shutdown()
        }
    }
}
