package dk.ternedal.modelrig.net

import dk.kaliv.visionrig.producer.EncodedCapture
import dk.kaliv.visionrig.producer.EncodedFrame
import okhttp3.Request
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/** The stop gate on its own: what may still happen after stop, on the wire and at the camera. */
class VisionRigStopGateTest {
    private lateinit var server: MockWebServer
    private val token = "q".repeat(VisionRigConnection.MIN_TOKEN_CHARS)

    @Before
    fun setUp() {
        server = MockWebServer()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun serve(handler: (RecordedRequest) -> MockResponse) {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest) = handler(request)
        }
        server.start()
    }

    private fun gated(gate: VisionRigStopGate) =
        gate.client(VisionRigHttp.client(VisionRigConnection.create(server.url("/").toString(), token).getOrThrow()))

    private fun get(client: okhttp3.OkHttpClient, path: String = "/x") =
        client.newCall(Request.Builder().url(server.url(path)).build()).execute()

    @Test
    fun noRequestLeavesThePhoneAfterStop() {
        serve { MockResponse().setBody("ok") }
        val gate = VisionRigStopGate()
        val client = gated(gate)
        get(client).use { assertEquals(200, it.code) }
        gate.stop()
        assertThrows(IOException::class.java) { get(client).close() }
        assertEquals("only the call before stop reached the server", 1, server.requestCount)
    }

    @Test
    fun anAnswerWrittenAfterStopNeverReachesTheCaller() {
        val gate = VisionRigStopGate()
        serve {
            gate.stop()
            MockResponse().setBody("""{"enabled":true}""")
        }
        assertThrows(IOException::class.java) { get(gated(gate)).close() }
    }

    @Test
    fun stopCancelsACallThatIsWaitingForTheGateway() {
        val inFlight = CountDownLatch(1)
        val release = CountDownLatch(1)
        serve {
            inFlight.countDown()
            release.await(30, TimeUnit.SECONDS)
            MockResponse().setBody("late")
        }
        val gate = VisionRigStopGate()
        val client = gated(gate)
        var failure: Throwable? = null
        val caller = thread { failure = runCatching { get(client).close() }.exceptionOrNull() }
        try {
            assertTrue(inFlight.await(10, TimeUnit.SECONDS))
            gate.stop()
            caller.join(5_000)
            assertFalse("the call ended without the gateway's answer", caller.isAlive)
            assertTrue("it ended as an I/O failure, not a response", failure is IOException)
        } finally {
            release.countDown()
            caller.join(30_000)
        }
    }

    @Test
    fun theGatedClientKeepsTheGuardOfVisionRigHttp() {
        val elsewhere = MockWebServer().apply { start() }
        try {
            serve { MockResponse().setResponseCode(307).setHeader("Location", elsewhere.url("/stolen").toString()) }
            val client = gated(VisionRigStopGate())
            assertFalse(client.followRedirects)
            assertThrows(VisionRigOriginRefusedIOException::class.java) { get(client).close() }
            assertThrows(VisionRigOriginRefusedIOException::class.java) {
                client.newCall(Request.Builder().url(elsewhere.url("/direct")).build()).execute().close()
            }
            assertEquals("the redirect target and the foreign origin were never contacted", 0, elsewhere.requestCount)
        } finally {
            elsewhere.shutdown()
        }
    }

    private class Camera(private val onOpen: () -> Unit = {}, private val onCapture: () -> Unit = {}) : EncodedCapture {
        val opens = AtomicInteger()
        val closes = AtomicInteger()
        @Volatile override var isOpen = false
        override fun open() {
            opens.incrementAndGet()
            isOpen = true
            onOpen()
        }
        override fun close() {
            closes.incrementAndGet()
            isOpen = false
        }
        override fun capture(): EncodedFrame {
            onCapture()
            return EncodedFrame(byteArrayOf(1, 2, 3))
        }
    }

    @Test
    fun theCameraDoesNotOpenAfterStop() {
        val gate = VisionRigStopGate()
        val camera = Camera()
        gate.stop()
        assertThrows(VisionRigStoppedIOException::class.java) { gate.capture(camera).open() }
        assertEquals(0, camera.opens.get())
    }

    @Test
    fun aStopDuringOpenClosesTheCameraAgain() {
        val gate = VisionRigStopGate()
        val camera = Camera(onOpen = { gate.stop() })
        assertThrows(VisionRigStoppedIOException::class.java) { gate.capture(camera).open() }
        assertEquals(1, camera.closes.get())
        assertFalse(camera.isOpen)
    }

    @Test
    fun aFrameCapturedAcrossTheStopIsDiscarded() {
        val gate = VisionRigStopGate()
        val gated = gate.capture(Camera(onCapture = { gate.stop() }))
        gated.open()
        assertThrows(VisionRigStoppedIOException::class.java) { gated.capture() }
    }
}
