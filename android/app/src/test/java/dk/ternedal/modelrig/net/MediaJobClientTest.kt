package dk.ternedal.modelrig.net

import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.JOB_ID
import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.SDXL
import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.job
import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.profile
import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.profiles
import dk.ternedal.modelrig.net.MediaJobException.Reason
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/** Wire behaviour of the job client against a real HTTP boundary (no rig). */
class MediaJobClientTest {
    private lateinit var server: MockWebServer
    private lateinit var client: MediaJobClient

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        client = MediaJobClient(server.url("/").toString().trimEnd('/'), "device-token")
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun json(body: String, code: Int = 200) = MockResponse()
        .setResponseCode(code)
        .setHeader("Content-Type", "application/json")
        .setBody(body)

    private fun reason(block: () -> Unit): MediaJobException = assertThrows(MediaJobException::class.java) { block() }

    private val request = MediaJobRequest("sdxl-a", "a red bicycle under a streetlight", 1024, 1024, null, null)

    @Test
    fun `submit posts exactly the request with the bearer and parses the job`() {
        server.enqueue(json(job(), 202))
        val created = client.submit(request, SDXL)
        assertEquals(JOB_ID, created.id)
        val sent = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("POST", sent.method)
        assertEquals("/api/v1/media/jobs", sent.path)
        assertEquals("Bearer device-token", sent.getHeader("Authorization"))
        assertTrue(sent.getHeader("Content-Type")!!.startsWith("application/json"))
        val body = JSONObject(sent.body.readUtf8())
        assertEquals("a red bicycle under a streetlight", body.getString("prompt"))
        assertFalse(body.has("owner"))
    }

    @Test
    fun `an invalid request is refused locally and never sent`() {
        val e = reason { client.submit(request.copy(width = 1000), SDXL) }
        assertEquals(Reason.INVALID_REQUEST, e.reason)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `the prompt is not in any error message`() {
        for (code in listOf(400, 429, 503, 500)) {
            server.enqueue(json("""{"detail":"invalid_request"}""", code))
            val e = reason { client.submit(request, SDXL) }
            assertFalse(e.message!!.contains("bicycle"))
        }
    }

    @Test
    fun `status and cancel use the job path`() {
        server.enqueue(json(job(state = "running")))
        assertEquals(MediaJobState.RUNNING, client.status(JOB_ID).state)
        server.enqueue(json(JSONObject().put("result", "cancelled").put("job", JSONObject(job(state = "cancelled"))).toString()))
        assertEquals(MediaJobState.CANCELLED, client.cancel(JOB_ID)!!.state)
        assertEquals("/api/v1/media/jobs/$JOB_ID", server.takeRequest(1, TimeUnit.SECONDS)!!.path)
        val cancel = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("POST", cancel.method)
        assertEquals("/api/v1/media/jobs/$JOB_ID/cancel", cancel.path)
    }

    @Test
    fun `profiles are read from the profile route`() {
        server.enqueue(json(profiles(profile())))
        assertEquals(listOf("sdxl-a"), client.profiles().map { it.profileId })
        assertEquals("/api/v1/media/jobs/profiles", server.takeRequest(1, TimeUnit.SECONDS)!!.path)
    }

    @Test
    fun `status codes map to reasons, and 404 is unavailable unless the rig says the job is gone`() {
        val cases = listOf(
            Triple(404, "", Reason.UNAVAILABLE),
            Triple(404, """{"detail":"Not Found"}""", Reason.UNAVAILABLE),
            Triple(503, """{"detail":"media_work_area_not_private"}""", Reason.UNAVAILABLE),
            Triple(401, "", Reason.UNAUTHORIZED),
            Triple(429, """{"detail":"active_limit"}""", Reason.BUSY),
            Triple(400, """{"detail":"profile_not_enabled"}""", Reason.INVALID_REQUEST),
            Triple(500, "", Reason.HTTP),
        )
        for ((code, body, expected) in cases) {
            server.enqueue(json(body, code))
            assertEquals("$code $body", expected, reason { client.profiles() }.reason)
        }
        server.enqueue(json("", 404))
        assertEquals("a bare 404 on a job route is the route missing, not the job", Reason.UNAVAILABLE,
            reason { client.status(JOB_ID) }.reason)
        server.enqueue(json("""{"error":"media job not found"}""", 404))
        assertEquals(Reason.UNAVAILABLE, reason { client.cancel(JOB_ID) }.reason)
        server.enqueue(json("""{"detail":"job_not_found"}""", 404))
        assertEquals(Reason.NOT_FOUND, reason { client.status(JOB_ID) }.reason)
        server.enqueue(json("""{"detail":"job_not_found_or_finished"}""", 404))
        assertEquals(Reason.NOT_FOUND, reason { client.cancel(JOB_ID) }.reason)
        server.enqueue(json("""{"detail":"job_not_found"}""", 404))
        assertEquals("a job code on a collection route is still unavailable", Reason.UNAVAILABLE,
            reason { client.profiles() }.reason)
        server.enqueue(json("""{"detail":"active_limit"}""", 429))
        assertEquals("active_limit", reason { client.submit(request, SDXL) }.code)
        server.enqueue(json("""{"detail":"Some sentence with spaces"}""", 429))
        assertNull(reason { client.submit(request, SDXL) }.code)
    }

    @Test
    fun `redirects are refused, not followed`() {
        server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", server.url("/elsewhere")))
        assertEquals(Reason.REDIRECT_REFUSED, reason { client.status(JOB_ID) }.reason)
        assertEquals(1, server.requestCount)
        // Even an injected client that follows redirects must not (the gallery's #2301 lesson).
        val following = MediaJobClient(server.url("/").toString().trimEnd('/'), "device-token",
            okhttp3.OkHttpClient.Builder().followRedirects(true).followSslRedirects(true).build())
        server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", server.url("/elsewhere")))
        server.enqueue(json(job()))
        assertEquals(Reason.REDIRECT_REFUSED, reason { following.status(JOB_ID) }.reason)
        assertEquals(2, server.requestCount)
    }

    @Test
    fun `a 200 that is not JSON or is too large is unavailable`() {
        server.enqueue(MockResponse().setHeader("Content-Type", "text/html").setBody(job()))
        assertEquals(Reason.UNAVAILABLE, reason { client.status(JOB_ID) }.reason)
        server.enqueue(json("{\"x\":\"" + "a".repeat(70 * 1024) + "\"}"))
        assertEquals(Reason.UNAVAILABLE, reason { client.status(JOB_ID) }.reason)
    }

    @Test
    fun `no pairing or a refused origin fails before any request`() {
        assertEquals(Reason.NOT_PAIRED, reason { MediaJobClient(null, "t") }.reason)
        assertEquals(Reason.NOT_PAIRED, reason { MediaJobClient(server.url("/").toString().trimEnd('/'), "") }.reason)
        assertEquals(Reason.ORIGIN_REFUSED, reason { MediaJobClient("http://203.0.113.5:8080", "t") }.reason)
        assertEquals(Reason.ORIGIN_REFUSED, reason { MediaJobClient("https://rig.example/path", "t") }.reason)
    }
}
