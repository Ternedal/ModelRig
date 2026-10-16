package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.atomic.AtomicInteger

/**
 * Exercise the exact Android HTTP signing and response handling with a local
 * in-memory OkHttp interceptor. No LAN, rig or Nest Hub is needed.
 */
class HubMirrorClientWireTest {
    private fun fixtureClient(status: Int, capture: (okhttp3.Request) -> Unit): OkHttpClient =
        OkHttpClient.Builder()
            .followRedirects(false)
            .followSslRedirects(false)
            .addInterceptor { chain ->
                val request = chain.request()
                capture(request)
                Response.Builder()
                    .request(request)
                    .protocol(Protocol.HTTP_1_1)
                    .code(status)
                    .message("fixture")
                    .body("{}".toResponseBody("application/json".toMediaType()))
                    .build()
            }.build()

    @Test
    fun androidEmitsProperlySignedCompletedReplyAndNothingElse() {
        val secret = "a".repeat(64)
        val text = "Hej fra Kaliv! 😀"
        val observed = AtomicInteger(0)
        val http = fixtureClient(202) { request ->
            observed.incrementAndGet()
            assertEquals("POST", request.method)
            assertEquals("192.168.1.100", request.url.host)
            assertEquals(8765, request.url.port)
            assertEquals("/v1/events", request.url.encodedPath)
            assertNull(request.header("Authorization"))
            assertNull(request.header("Cookie"))
            assertTrue(request.header("Content-Type").orEmpty().startsWith("application/json"))

            val bytes = okio.Buffer().also { request.body!!.writeTo(it) }.readUtf8()
            val obj = JSONObject(bytes)
            assertEquals(setOf("version", "type", "event_id", "text"),
                obj.keys().asSequence().toSet())
            assertEquals(1, obj.getInt("version"))
            assertEquals("assistant_complete", obj.getString("type"))
            assertEquals(text, obj.getString("text"))
            assertTrue(obj.getString("event_id").isNotEmpty())

            val ts = request.header("X-Kaliv-Timestamp")!!
            assertTrue(ts.toLong() > 1700000000L)
            val digest = request.header("X-Kaliv-Signature")
            assertEquals(HubMirrorClient.signature(secret, ts, bytes), digest)
            assertTrue(digest!!.startsWith("v1="))
        }
        assertTrue(HubMirrorClient.sendCompletedWithClient(
            "http://192.168.1.100:8765", secret, text, http))
        assertEquals(1, observed.get())
    }

    @Test
    fun refusesNonPrivateTargetsBeforeAnyHttpRequest() {
        val observed = AtomicInteger(0)
        val http = fixtureClient(202) { observed.incrementAndGet() }
        assertFalse(HubMirrorClient.sendCompletedWithClient(
            "http://example.org:8765", "s".repeat(40), "Hej", http))
        assertFalse(HubMirrorClient.sendCompletedWithClient(
            "http://127.0.0.1:8765", "s".repeat(40), "Hej", http))
        assertFalse(HubMirrorClient.sendCompletedWithClient(
            "http://192.168.1.100:8765", "short", "Hej", http))
        assertFalse(HubMirrorClient.sendCompletedWithClient(
            "http://192.168.1.100:8765", "s".repeat(40), "  ", http))
        assertEquals(0, observed.get())
    }

    @Test
    fun onlyQueueOrDuplicateAcknowledgementsCountAsAccepted() {
        for ((status, accepted) in listOf(
            202 to true,
            409 to true,
            200 to false,
            302 to false,
            401 to false,
            503 to false,
        )) {
            val http = fixtureClient(status) {}
            assertEquals("HTTP status $status", accepted, HubMirrorClient.sendCompletedWithClient(
                "http://192.168.1.100:8765", "s".repeat(40), "Hej", http))
        }
    }

    @Test
    fun nonBmpUnicodeCannotExceedReceiversUtf16Limit() {
        val http = fixtureClient(202) { request ->
            val body = okio.Buffer().also { request.body!!.writeTo(it) }.readUtf8()
            val text = JSONObject(body).getString("text")
            assertEquals(2000, text.length)
            assertEquals(1000, text.codePointCount(0, text.length))
            assertTrue(text.endsWith("😀"))
        }
        assertTrue(HubMirrorClient.sendCompletedWithClient(
            "http://192.168.1.100:8765", "s".repeat(40), "😀".repeat(1200), http))
    }
}
