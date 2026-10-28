package dk.ternedal.modelrig.net

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.test.core.app.ApplicationProvider
import dk.kaliv.visionrig.producer.ProducerRunConfig
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
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

/**
 * The vendored VisionRig producer, bound by the app, against a fake gateway
 * speaking VisionRig's protocol (fixtures as in VisionRig's GatewayClientTest).
 * The camera stays closed: VisionRig's desired-state says disabled.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class VisionRigProducerBindingTest {
    private lateinit var gateway: MockWebServer
    private lateinit var elsewhere: MockWebServer
    private val token = "p".repeat(VisionRigConnection.MIN_TOKEN_CHARS)
    private val seen = CopyOnWriteArrayList<RecordedRequest>()

    private class StopTest : RuntimeException()

    private val owner = object : LifecycleOwner {
        val registry = LifecycleRegistry.createUnsafe(this).apply { currentState = Lifecycle.State.RESUMED }
        override val lifecycle: Lifecycle get() = registry
    }

    private fun json(body: String) = MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json").setBody(body)

    private fun protocol(desiredState: (RecordedRequest) -> MockResponse) = object : Dispatcher() {
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
                else -> MockResponse().setResponseCode(404)
            }
        }
    }

    private val disabled = json(
        """{"schema_id":"visionrig/sensor-desired-state/v2","source_id":"kaliv-android",
        "enabled":false,"revision":3,"production_authority":false}""",
    )

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

    private fun bound(connection: VisionRigConnection): VisionRigCameraProducer =
        VisionRigProducerBinding.create(
            context = ApplicationProvider.getApplicationContext(),
            lifecycleOwner = owner,
            connection = connection,
            http = VisionRigHttp.client(connection),
            runConfig = ProducerRunConfig(disabledPollMillis = 250),
        )

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
}
