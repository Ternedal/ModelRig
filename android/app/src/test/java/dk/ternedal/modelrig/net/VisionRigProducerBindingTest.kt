package dk.ternedal.modelrig.net

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.test.core.app.ApplicationProvider
import dk.kaliv.visionrig.producer.EncodedCapture
import dk.kaliv.visionrig.producer.EncodedFrame
import dk.kaliv.visionrig.producer.ProducerRunConfig
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * The vendored VisionRig producer, bound by the app, against a fake gateway
 * speaking VisionRig's protocol (fixtures as in VisionRig's GatewayClientTest).
 * Where desired-state enables the source, a fake camera stands in for CameraX.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class VisionRigProducerBindingTest {
    private lateinit var gateway: MockWebServer
    private lateinit var elsewhere: MockWebServer
    private val token = "p".repeat(VisionRigConnection.MIN_TOKEN_CHARS)
    private val seen = CopyOnWriteArrayList<RecordedRequest>()

    private class StopTest : RuntimeException()

    /** Stands in for CameraX: counts opens and captures, returns a small JPEG-typed payload. */
    private class FakeCamera : EncodedCapture {
        val opens = AtomicInteger()
        val captures = AtomicInteger()
        @Volatile override var isOpen = false
        override fun open() {
            opens.incrementAndGet()
            isOpen = true
        }
        override fun close() {
            isOpen = false
        }
        override fun capture(): EncodedFrame {
            captures.incrementAndGet()
            return EncodedFrame(ByteArray(64) { 0x42 })
        }
    }

    private val owner = object : LifecycleOwner {
        val registry = LifecycleRegistry.createUnsafe(this).apply { currentState = Lifecycle.State.RESUMED }
        override val lifecycle: Lifecycle get() = registry
    }

    private fun json(body: String) = MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json").setBody(body)

    private fun protocol(
        frames: (RecordedRequest) -> MockResponse = { MockResponse().setResponseCode(404) },
        desiredState: (RecordedRequest) -> MockResponse,
    ) = object : Dispatcher() {
        override fun dispatch(request: RecordedRequest): MockResponse {
            seen += request
            return when (request.path) {
                "/api/v1/producer-capabilities" -> json(
                    """{"schema":"visionrig/producer-capabilities/v2","max_payload_bytes":1048576,
                    "gateway_max_payload_bytes":1048576,"core_max_payload_bytes":1048576,
                    "sensor_packet_schemas":["visionrig/sensor-packet/v2"],
                    "sensor_packet_compressions":["none","zlib","auto"],
                    "packet_payload_warning_utilization":0.8,"packet_payload_critical_utilization":0.95}""",
                )
                "/api/v1/sensors/kaliv-android/desired-state" -> desiredState(request)
                "/api/v1/sensors/heartbeat" -> json(
                    """{"schema_id":"visionrig/sensor-heartbeat-receipt/v1","status":"accepted",
                    "source_id":"kaliv-android","seen_utc":"2026-10-28T19:00:00Z","production_authority":false}""",
                )
                else -> if (request.path!!.startsWith("/api/v1/frames/ingest")) frames(request) else MockResponse().setResponseCode(404)
            }
        }
    }

    private val disabled = json(
        """{"schema_id":"visionrig/sensor-desired-state/v2","source_id":"kaliv-android",
        "enabled":false,"revision":3,"production_authority":false}""",
    )

    private val enabled get() = json(
        """{"schema_id":"visionrig/sensor-desired-state/v2","source_id":"kaliv-android",
        "enabled":true,"revision":4,"production_authority":false}""",
    )

    /** VisionRig's receipt for a processed frame, echoing the sequence and drop count it was sent. */
    private fun accepted(request: RecordedRequest): MockResponse {
        val url = request.requestUrl!!
        return json(
            """{"schema_id":"visionrig/sensor-frame-receipt/v1","status":"processed","source_id":"kaliv-android",
            "source_type":"camera","frame_sequence":${url.queryParameter("frame_sequence")},"event_id":"evt-1",
            "dropped_frames":${url.queryParameter("dropped_frames")},"production_authority":false}""",
        )
    }

    private val frameRequests get() = seen.count { it.path!!.startsWith("/api/v1/frames") }

    @Before
    fun setUp() {
        gateway = MockWebServer()
        elsewhere = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() {
        gateway.shutdown()
        elsewhere.shutdown()
    }

    private fun connect() = VisionRigConnection.create(gateway.url("/").toString(), token).getOrThrow()

    private fun bound(connection: VisionRigConnection, camera: FakeCamera? = null): VisionRigCameraProducer =
        if (camera == null) {
            VisionRigProducerBinding.create(
                context = ApplicationProvider.getApplicationContext(),
                lifecycleOwner = owner,
                connection = connection,
                http = VisionRigHttp.client(connection),
                runConfig = ProducerRunConfig(disabledPollMillis = 250),
            )
        } else {
            VisionRigProducerBinding.create(
                context = ApplicationProvider.getApplicationContext(),
                lifecycleOwner = owner,
                connection = connection,
                http = VisionRigHttp.client(connection),
                runConfig = ProducerRunConfig(disabledPollMillis = 250),
                captureFactory = { _, _ -> camera },
            )
        }

    /** Runs until the first step VisionRig's loop reports, and returns it. */
    private fun firstStep(producer: VisionRigCameraProducer): VisionRigStep {
        val steps = CopyOnWriteArrayList<VisionRigStep>()
        runBlocking {
            withTimeout(15_000) {
                runCatching {
                    producer.run { step ->
                        steps += step
                        throw StopTest()
                    }
                }.exceptionOrNull().let { assertTrue("stopped by the test, not $it", it is StopTest) }
            }
        }
        producer.close()
        return steps.single()
    }

    @Test
    fun disabledSourceHeartbeatsWithTheProducerTokenAndOpensNoCamera() {
        gateway.dispatcher = protocol { disabled }
        gateway.start()
        val connection = VisionRigConnection.create(gateway.url("/").toString(), token).getOrThrow()
        val producer = bound(connection)
        val steps = CopyOnWriteArrayList<VisionRigStep>()
        runBlocking {
            withTimeout(15_000) {
                runCatching {
                    producer.run { step ->
                        steps += step
                        if (steps.size == 2) throw StopTest()
                    }
                }.exceptionOrNull().let { assertTrue("stopped by the test", it is StopTest) }
            }
        }
        producer.close()
        assertEquals(2, steps.size)
        assertTrue(steps.all { !it.desiredEnabled && !it.captureActive && !it.frameSent })
        val paths = seen.map { it.path }
        assertTrue(paths.contains("/api/v1/sensors/kaliv-android/desired-state"))
        assertTrue(paths.contains("/api/v1/sensors/heartbeat"))
        assertFalse("no frame without desired-state", paths.any { it!!.startsWith("/api/v1/frames") })
        assertTrue("every request carries the VisionRig producer token", seen.all { it.getHeader("Authorization") == "Bearer $token" })
        assertTrue("the token is never part of a URL", seen.none { it.requestUrl.toString().contains(token) })
    }

    @Test
    fun cancellingTheRunStopsAllGatewayTraffic() {
        gateway.dispatcher = protocol { disabled }
        gateway.start()
        val producer = bound(VisionRigConnection.create(gateway.url("/").toString(), token).getOrThrow())
        val firstStep = CompletableDeferred<Unit>()
        runBlocking {
            val job = launch(Dispatchers.IO) { producer.run { firstStep.complete(Unit) } }
            withTimeout(15_000) { firstStep.await() }
            job.cancel() // what ON_STOP does through repeatOnLifecycle
            job.join()
        }
        producer.close()
        val afterCancel = gateway.requestCount
        Thread.sleep(1_000) // several disabled-poll intervals (250 ms)
        assertEquals("no request after cancellation", afterCancel, gateway.requestCount)
    }

    @Test
    fun enabledSourceWithoutCameraPermissionFailsClosedAndSendsNoFrame() {
        // Desired-state says capture, but the app has no CAMERA permission
        // (Robolectric default): the producer must fail closed, not send.
        gateway.dispatcher = protocol {
            json("""{"schema_id":"visionrig/sensor-desired-state/v2","source_id":"kaliv-android",
            "enabled":true,"revision":4,"production_authority":false}""")
        }
        gateway.start()
        val producer = bound(VisionRigConnection.create(gateway.url("/").toString(), token).getOrThrow())
        val failure = runBlocking { withTimeout(15_000) { runCatching { producer.run { } }.exceptionOrNull() } }
        producer.close()
        assertTrue("fails closed", failure != null)
        assertFalse("no frame was sent", seen.any { it.path!!.startsWith("/api/v1/frames") })
        assertFalse("the error does not carry the token", generateSequence(failure) { it.cause }.any { (it.message ?: "").contains(token) })
    }

    @Test
    fun aRedirectFromTheGatewayIsNeverFollowed() {
        // VisionRig's own default client would follow this; the bound one must not.
        gateway.dispatcher = protocol {
            MockResponse().setResponseCode(307).setHeader("Location", elsewhere.url("/api/v1/sensors/kaliv-android/desired-state").toString())
        }
        gateway.start()
        val connection = VisionRigConnection.create(gateway.url("/").toString(), token).getOrThrow()
        val producer = bound(connection)
        val failure = runBlocking {
            withTimeout(15_000) { runCatching { producer.run { } }.exceptionOrNull() }
        }
        producer.close()
        assertTrue("the run fails instead of following", failure != null && failure !is StopTest)
        assertEquals("the redirect target was never contacted", 0, elsewhere.requestCount)
    }

    @Test
    fun stopWhileDesiredStateIsInFlightNeverOpensTheCameraOrSendsAFrame() {
        // Review 5688431923 P1: ON_STOP arrives while VisionRig's synchronous step
        // waits for desired-state, which then answers "enabled".
        val inFlight = CountDownLatch(1)
        val release = CountDownLatch(1)
        gateway.dispatcher = protocol(frames = ::accepted) {
            inFlight.countDown()
            release.await(30, TimeUnit.SECONDS)
            enabled
        }
        gateway.start()
        val camera = FakeCamera()
        val producer = bound(connect(), camera)
        val stoppedPromptly = runBlocking {
            val job = launch(Dispatchers.IO) { runCatching { producer.run { } } }
            assertTrue("desired-state is in flight", inFlight.await(15, TimeUnit.SECONDS))
            job.cancel() // what ON_STOP does through repeatOnLifecycle
            val stopped = withTimeoutOrNull(5_000) { job.join() } != null
            release.countDown() // the late "enabled" answer
            withTimeout(30_000) { job.join() }
            stopped
        }
        producer.close()
        Thread.sleep(500) // room for anything a late answer could still trigger
        assertTrue("the run stops without waiting for the gateway's answer", stoppedPromptly)
        assertEquals("the camera never opened", 0, camera.opens.get())
        assertEquals("no frame was captured", 0, camera.captures.get())
        assertEquals("no frame was sent", 0, frameRequests)
    }

    @Test
    fun closingWhileTheGatewayAnswersEnabledEndsTheRunWithoutCapture() {
        // The answer is written only after the producer was closed: the gate
        // is stopped before the client can read it.
        val producerRef = java.util.concurrent.atomic.AtomicReference<VisionRigCameraProducer>()
        gateway.dispatcher = protocol(frames = ::accepted) {
            producerRef.get().close()
            enabled
        }
        gateway.start()
        val camera = FakeCamera()
        producerRef.set(bound(connect(), camera))
        val failure = runBlocking { withTimeout(15_000) { runCatching { producerRef.get().run { } }.exceptionOrNull() } }
        assertEquals("a stopped run ends quietly, not as a fault", null, failure)
        assertEquals("the camera never opened", 0, camera.opens.get())
        assertEquals("no frame was sent", 0, frameRequests)
    }

    @Test
    fun aFrameVisionRigAcceptsCountsAsSent() {
        gateway.dispatcher = protocol(frames = ::accepted) { enabled }
        gateway.start()
        val camera = FakeCamera()
        val step = firstStep(bound(connect(), camera))
        assertEquals(VisionRigStep(desiredEnabled = true, captureActive = true, frameSent = true, frameDropped = false), step)
        assertEquals(1, camera.opens.get())
        assertEquals(1, frameRequests)
    }

    @Test
    fun aFrameDroppedByAnOverloadedGatewayIsNotCountedAsSent() {
        // Review 5688431923 P2: 429 is DROPPED_OVERLOAD, a SendResult like ACCEPTED.
        gateway.dispatcher = protocol(frames = { MockResponse().setResponseCode(429) }) { enabled }
        gateway.start()
        val step = firstStep(bound(connect(), FakeCamera()))
        assertEquals(VisionRigStep(desiredEnabled = true, captureActive = true, frameSent = false, frameDropped = true), step)
    }

    @Test
    fun aFrameLostToAnUnreachableGatewayIsNotCountedAsSent() {
        // The connection drops after the frame POST is read: DROPPED_UNAVAILABLE.
        gateway.dispatcher = protocol(frames = { MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST) }) { enabled }
        gateway.start()
        val step = firstStep(bound(connect(), FakeCamera()))
        assertEquals(VisionRigStep(desiredEnabled = true, captureActive = true, frameSent = false, frameDropped = true), step)
    }
}
