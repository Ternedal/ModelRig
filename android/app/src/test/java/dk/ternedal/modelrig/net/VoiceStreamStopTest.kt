package dk.ternedal.modelrig.net

import dk.ternedal.modelrig.voice.VoiceTurnCancellation
import java.io.IOException
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Stop must close the voice HTTP stream itself. Cancelling the coroutine does not
 * interrupt OkHttp's blocking execute(), so before this the reader kept going and
 * kept calling back until the rig finished. Here the rest of the stream is throttled
 * to arrive over seconds; a Stop from another thread must end the read at once, with
 * nothing dispatched after it.
 */
class VoiceStreamStopTest {
    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private val transcript = """{"type":"transcript","text":"Hej"}""" + "\n"

    private fun slowStream(): MockResponse {
        val rest = (0 until 8).joinToString("") {
            """{"type":"chunk","index":$it,"text":"sætning $it","audio_base64":""}""" + "\n"
        } + """{"type":"done","reply":"for sent","via_cloud":false}""" + "\n"
        return MockResponse()
            .setResponseCode(200)
            .addHeader("Content-Type", "application/x-ndjson")
            .setBody(transcript + rest)
            // The transcript line arrives at once; everything after it trickles in
            // over roughly ten seconds.
            .throttleBody(transcript.length.toLong(), 1, TimeUnit.SECONDS)
    }

    @Test
    fun stopFromAnotherThreadClosesTheStreamAndNothingMoreArrives() {
        server.enqueue(slowStream())
        val cancellation = VoiceTurnCancellation()
        val events = Collections.synchronizedList(mutableListOf<String>())
        val transcriptSeen = CountDownLatch(1)
        val failure = AtomicReference<Throwable?>(null)
        val reader = Thread {
            try {
                ModelRigClient(server.url("/").toString(), "paired-token").voiceConverseStream(
                    audioB64 = "UklGRg==",
                    registerCall = { cancellation.register(it) },
                    onTranscript = { events.add("transcript:$it"); transcriptSeen.countDown() },
                    onChunk = { _, text, _, _ -> events.add("chunk:$text") },
                    onDone = { reply, _, _ -> events.add("done:$reply") },
                    onError = { status, _ -> events.add("error:$status") },
                )
            } catch (t: Throwable) {
                failure.set(t)
            }
        }
        reader.start()
        assertTrue("transcript never arrived", transcriptSeen.await(5, TimeUnit.SECONDS))

        val stoppedAt = System.nanoTime()
        cancellation.stop()
        reader.join(5_000)
        val tookMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - stoppedAt)

        assertTrue("reader still running after Stop", !reader.isAlive)
        assertTrue("Stop took ${tookMs}ms; the read was not interrupted", tookMs < 2_000)
        assertTrue("expected an IOException, got ${failure.get()}", failure.get() is IOException)
        assertEquals(listOf("transcript:Hej"), events.toList())
        assertTrue(cancellation.stopFlag.get())
    }

    @Test
    fun aStreamThatIsNotStoppedStillCompletes() {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .addHeader("Content-Type", "application/x-ndjson")
                .setBody(transcript + """{"type":"done","reply":"Goddag","via_cloud":false}""" + "\n")
        )
        val cancellation = VoiceTurnCancellation()
        val events = mutableListOf<String>()
        ModelRigClient(server.url("/").toString(), "paired-token").voiceConverseStream(
            audioB64 = "UklGRg==",
            registerCall = { cancellation.register(it) },
            onTranscript = { events.add("transcript:$it") },
            onChunk = { _, text, _, _ -> events.add("chunk:$text") },
            onDone = { reply, _, _ -> events.add("done:$reply") },
            onError = { status, _ -> events.add("error:$status") },
        )
        cancellation.clear()
        assertEquals(listOf("transcript:Hej", "done:Goddag"), events)
    }
}
