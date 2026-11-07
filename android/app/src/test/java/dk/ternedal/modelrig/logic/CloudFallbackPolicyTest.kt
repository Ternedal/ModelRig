package dk.ternedal.modelrig.logic

import dk.ternedal.modelrig.net.CloudClient
import dk.ternedal.modelrig.net.ModelRigClient
import okhttp3.Call
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Pressing Stop must never send the request to Ollama Cloud (C5 F1, #2275).
 *
 * The tests use the real clients against two MockWebServers, one for the rig and one for
 * the cloud. The cloud server's request count is what proves egress happened or not.
 * Stop is reproduced exactly as the screen does it: the register hook records the active
 * call, and Stop is `activeCall?.cancel()`.
 */
class CloudFallbackPolicyTest {
    private lateinit var rigServer: MockWebServer
    private lateinit var cloudServer: MockWebServer
    @Volatile private var activeCall: Call? = null
    private var cloudEntered = 0
    private val hook: (Call) -> Unit = { activeCall = it }
    private val history = listOf("user" to "tidligere", "assistant" to "svar", "user" to "nu")

    @Before
    fun setUp() {
        rigServer = MockWebServer().apply { start() }
        cloudServer = MockWebServer().apply { start() }
        cloudServer.enqueue(
            MockResponse().setResponseCode(200).setBody("""{"message":{"content":"sky"},"done":true}""" + "\n"),
        )
    }

    @After
    fun tearDown() {
        rigServer.shutdown()
        cloudServer.shutdown()
    }

    private fun run(optedIn: () -> Boolean = { true }, hasKey: Boolean = true, out: StringBuilder = StringBuilder(),
                    duringRig: () -> Unit = {}, beforeCloud: () -> Unit = {}): Boolean =
        CloudFallbackPolicy.runLocalFirst(
            hasCloudKey = hasKey,
            optedIn = optedIn,
            register = hook,
            rig = { register, onEmit ->
                duringRig()
                ModelRigClient(rigServer.url("/").toString(), "test-token")
                    .chatStream("rig-model", history, registerCall = register, onDelta = { onEmit(); out.append(it) })
            },
            cloud = { register ->
                cloudEntered++
                beforeCloud()
                CloudClient("test-only-key", cloudServer.url("/").toString())
                    .chatStream("cloud-model", history, registerCall = register, onDelta = { out.append(it) })
            },
        )

    @Test
    fun stopBeforeFirstTokenNeverReachesTheCloud() {
        // The rig accepts the request but sends nothing, so the user is waiting for the first token.
        rigServer.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        val stopper = Thread {
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10)
            while (rigServer.requestCount == 0 && System.nanoTime() < deadline) Thread.sleep(10)
            activeCall?.cancel() // the Stop button
        }
        stopper.start()
        try {
            run()
            fail("a stopped request must surface as a failure, not be answered")
        } catch (e: IOException) {
            // OkHttp's "Canceled"; the screen shows it as an interrupted turn.
        } finally {
            stopper.join()
        }
        assertEquals("a stopped request is not even a fallback candidate", 0, cloudEntered)
        assertEquals("nothing may reach the cloud after Stop", 0, cloudServer.requestCount)
    }

    @Test
    fun stopAfterRigFailureButBeforeCloudCallCancelsTheCloudCall() {
        // The rig fails cleanly (fallback is allowed), and Stop lands in the window before the
        // cloud call exists. Stop therefore cancels the old rig call, which is still the active one.
        rigServer.enqueue(MockResponse().setResponseCode(503).setBody("ollama down"))
        try {
            run(beforeCloud = { activeCall?.cancel() })
            fail("the cloud call must be cancelled before it is sent")
        } catch (e: IOException) {
            // Canceled before execute().
        }
        assertEquals("the fallback started (the rig failure itself was clean)", 1, cloudEntered)
        assertEquals("the cloud call was cancelled before execute()", 0, cloudServer.requestCount)
    }

    @Test
    fun cleanPreOutputFailureFallsBackOnlyWhenOptedIn() {
        rigServer.enqueue(MockResponse().setResponseCode(503).setBody("ollama down"))
        val out = StringBuilder()
        assertTrue(run(optedIn = { true }, out = out))
        assertEquals("sky", out.toString())
        assertEquals(1, cloudServer.requestCount)
        // What reached the cloud is still only the current message (D5).
        val body = cloudServer.takeRequest().body.readUtf8()
        assertTrue(body.contains("\"nu\""))
        assertFalse(body.contains("tidligere"))
    }

    @Test
    fun cleanPreOutputFailureWithoutOptInIsSurfaced() {
        rigServer.enqueue(MockResponse().setResponseCode(503).setBody("ollama down"))
        try {
            run(optedIn = { false })
            fail("without opt-in the rig failure must surface")
        } catch (e: Exception) {
            assertTrue(e.message.orEmpty().contains("503"))
        }
        assertEquals(0, cloudServer.requestCount)
    }

    @Test
    fun cleanPreOutputFailureWithoutKeyIsSurfaced() {
        rigServer.enqueue(MockResponse().setResponseCode(503).setBody("ollama down"))
        try {
            run(hasKey = false)
            fail("without a cloud key the rig failure must surface")
        } catch (e: Exception) {
            assertTrue(e.message.orEmpty().contains("503"))
        }
        assertEquals(0, cloudServer.requestCount)
    }

    @Test
    fun midStreamFailureIsSurfacedNotAnsweredTwice() {
        // One delta, then the body ends without done: the stream contract calls that a failure.
        rigServer.enqueue(MockResponse().setResponseCode(200).setBody("""{"message":{"content":"halv"}}""" + "\n"))
        val out = StringBuilder()
        try {
            run(out = out)
            fail("a truncated stream must surface")
        } catch (e: Exception) {
            // expected
        }
        assertEquals("halv", out.toString())
        assertEquals(0, cloudServer.requestCount)
    }

    @Test
    fun successfulRigAnswerNeverTouchesTheCloud() {
        rigServer.enqueue(
            MockResponse().setResponseCode(200).setBody("""{"message":{"content":"rig"},"done":true}""" + "\n"),
        )
        val out = StringBuilder()
        assertFalse(run(out = out))
        assertEquals("rig", out.toString())
        assertEquals(0, cloudServer.requestCount)
    }

    @Test
    fun coroutineCancellationIsAStopToo() {
        val cancellation = java.util.concurrent.CancellationException("scope cancelled")
        var cloudCalled = false
        try {
            CloudFallbackPolicy.runLocalFirst(
                hasCloudKey = true, optedIn = { true }, register = hook,
                rig = { _, _ -> throw cancellation },
                cloud = { cloudCalled = true },
            )
            fail("cancellation must propagate")
        } catch (e: java.util.concurrent.CancellationException) {
            assertSame(cancellation, e)
        }
        assertFalse(cloudCalled)
    }

    @Test
    fun optOutWhileWaitingForTheRigHoldsForThePendingRequest() {
        // Codex P1 on #2348: the opt-in was captured before the rig call. Turning the fallback
        // off while the rig was still working then had no effect on that request.
        rigServer.enqueue(MockResponse().setResponseCode(503).setBody("ollama down"))
        var optIn = true
        try {
            run(optedIn = { optIn }, duringRig = { optIn = false }) // the overflow toggle, mid-wait
            fail("an opt-out made before the rig failed must hold")
        } catch (e: Exception) {
            assertTrue(e.message.orEmpty().contains("503"))
        }
        assertEquals(0, cloudEntered)
        assertEquals("nothing may reach the cloud after the user opted out", 0, cloudServer.requestCount)
    }

    @Test
    fun optInIsReadOnlyAfterTheRigFailed() {
        rigServer.enqueue(MockResponse().setResponseCode(503).setBody("ollama down"))
        val events = mutableListOf<String>()
        assertTrue(run(optedIn = { events += "read opt-in"; true }, duringRig = { events += "rig started" }))
        assertEquals(listOf("rig started", "read opt-in"), events)
        assertEquals(1, cloudServer.requestCount)
    }

    @Test
    fun aSuccessfulRigAnswerNeverReadsTheOptIn() {
        rigServer.enqueue(
            MockResponse().setResponseCode(200).setBody("""{"message":{"content":"rig"},"done":true}""" + "\n"),
        )
        var reads = 0
        assertFalse(run(optedIn = { reads++; true }))
        assertEquals(0, reads)
    }

    @Test
    fun policyTruthTable() {
        assertTrue(CloudFallbackPolicy.shouldFallback(0, rigCallCancelled = false, hasCloudKey = true, optedIn = true))
        assertFalse(CloudFallbackPolicy.shouldFallback(0, rigCallCancelled = true, hasCloudKey = true, optedIn = true))
        assertFalse(CloudFallbackPolicy.shouldFallback(1, rigCallCancelled = false, hasCloudKey = true, optedIn = true))
        assertFalse(CloudFallbackPolicy.shouldFallback(0, rigCallCancelled = false, hasCloudKey = false, optedIn = true))
        assertFalse(CloudFallbackPolicy.shouldFallback(0, rigCallCancelled = false, hasCloudKey = true, optedIn = false))
    }
}
