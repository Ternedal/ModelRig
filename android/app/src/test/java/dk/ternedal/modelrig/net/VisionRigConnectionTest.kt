package dk.ternedal.modelrig.net

import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** VisionRig pairing rules and the app's VisionRig HTTP client (#2275 transport decision 6476890811). */
class VisionRigConnectionTest {
    private val token = "t".repeat(VisionRigConnection.MIN_TOKEN_CHARS)

    @Test
    fun `origin policy matches the gallery rule`() {
        val allowed = listOf(
            "https://visionrig.tailnet.ts.net", "https://100.101.50.10:8443", "http://192.168.1.10:8111",
            "http://10.0.0.5:8111", "http://172.16.0.1:8111", "http://127.0.0.1:8111", "http://localhost:8111",
            "http://[::1]:8111", "http://192.168.1.10:8111/",
        )
        allowed.forEach { assertTrue(it, PairedOriginPolicy.check(it) is PairedOriginPolicy.Check.Allowed) }
        val refused = listOf(
            "http://100.101.50.10:8111", // Tailscale over plain HTTP: refused by decision
            "http://visionrig.local:8111", "http://8.8.8.8:8111", "http://172.32.0.1", "http://192.168.1.010",
            "http://user:pw@192.168.1.10:8111", "http://192.168.1.10:8111/api", "http://192.168.1.10:8111/?x=1",
            "ftp://192.168.1.10", "", "   ", "not a url",
        )
        refused.forEach { assertTrue(it, PairedOriginPolicy.check(it) is PairedOriginPolicy.Check.Refused) }
        assertTrue(PairedOriginPolicy.check(null) is PairedOriginPolicy.Check.Refused)
    }

    @Test
    fun `token must satisfy VisionRig's producer rule and never appears in toString`() {
        val ok = VisionRigConnection.create("http://192.168.1.10:8111", "  $token  ").getOrThrow()
        assertEquals(token, ok.token)
        assertEquals("http://192.168.1.10:8111", ok.gatewayUrl)
        assertFalse(ok.toString().contains(token))
        listOf("short", "x".repeat(31), "${"x".repeat(32)} y", "${"x".repeat(32)}ø", "x".repeat(513)).forEach { bad ->
            val failure = VisionRigConnection.create("http://192.168.1.10:8111", bad).exceptionOrNull()
            assertTrue(bad.take(10), failure is VisionRigSetupException)
            assertFalse(failure!!.message!!.contains(bad.trim()))
        }
        assertTrue(VisionRigConnection.create("http://100.64.0.1:8111", token).exceptionOrNull() is VisionRigSetupException)
    }

    @Test
    fun `client refuses redirects and never follows them`() {
        val server = MockWebServer().apply { start() }
        val elsewhere = MockWebServer().apply { start() }
        try {
            // 307 would re-send a POST body (a camera frame) to the new host if followed.
            server.enqueue(MockResponse().setResponseCode(307).setHeader("Location", elsewhere.url("/frames").toString()))
            val connection = VisionRigConnection.create(server.url("/").toString(), token).getOrThrow()
            val client = VisionRigHttp.client(connection)
            val request = Request.Builder().url(server.url("/api/sensors/frames"))
                .post(ByteArray(16).toRequestBody()).build()
            assertThrows(VisionRigOriginRefusedIOException::class.java) { client.newCall(request).execute().close() }
            assertEquals(1, server.requestCount)
            assertEquals("the frame never reached the redirect target", 0, elsewhere.requestCount)
        } finally {
            server.shutdown()
            elsewhere.shutdown()
        }
    }

    @Test
    fun `client refuses any request outside the paired origin`() {
        val server = MockWebServer().apply { start() }
        val elsewhere = MockWebServer().apply { start() }
        try {
            val client = VisionRigHttp.client(VisionRigConnection.create(server.url("/").toString(), token).getOrThrow())
            assertThrows(VisionRigOriginRefusedIOException::class.java) {
                client.newCall(Request.Builder().url(elsewhere.url("/api/sensors/heartbeat")).build()).execute().close()
            }
            assertEquals(0, elsewhere.requestCount)
            server.enqueue(MockResponse().setBody("{}"))
            client.newCall(Request.Builder().url(server.url("/api/sensors/heartbeat")).build()).execute().use {
                assertEquals(200, it.code)
            }
        } finally {
            server.shutdown()
            elsewhere.shutdown()
        }
    }
}
