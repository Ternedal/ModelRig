package dk.ternedal.modelrig.net

import dk.ternedal.modelrig.net.MediaGalleryContractTest.Companion.image
import dk.ternedal.modelrig.net.MediaGalleryContractTest.Companion.page
import dk.ternedal.modelrig.net.MediaGalleryException.Reason
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/** Wire behaviour of the gallery client against a real HTTP boundary (no rig). */
class MediaGalleryClientTest {
    private lateinit var server: MockWebServer
    private lateinit var client: MediaGalleryClient

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        // MockWebServer listens on loopback over plain HTTP, which the policy allows.
        client = MediaGalleryClient(server.url("/").toString().trimEnd('/'), "device-token")
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun json(body: String, code: Int = 200) = MockResponse()
        .setResponseCode(code)
        .setHeader("Content-Type", "application/json")
        .setBody(body)

    private fun bytes(data: ByteArray, type: String = "image/png") = MockResponse()
        .setHeader("Content-Type", type)
        .setBody(Buffer().write(data))

    private val item get() = MediaGalleryContract.parseItem(image("pic"))!!

    @Test
    fun `list sends bearer, limit and the opaque cursor as given`() {
        server.enqueue(json(page(listOf(image("a")), cursor = "\"next+/=\"")))
        server.enqueue(json(page(emptyList())))
        val first = client.page(limit = 25)
        val second = client.page(limit = 25, cursor = first.nextCursor)
        assertEquals("next+/=", first.nextCursor)
        assertNull(second.nextCursor)
        val one = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("GET", one.method)
        assertEquals("Bearer device-token", one.getHeader("Authorization"))
        assertEquals("/api/v1/media?limit=25", one.path)
        val two = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("/api/v1/media?limit=25&cursor=next%2B%2F%3D", two.path)
        assertEquals("next+/=", two.requestUrl!!.queryParameter("cursor"))
    }

    @Test
    fun `http status maps to a distinct reason`() {
        val cases = mapOf(
            400 to Reason.BAD_REQUEST,
            401 to Reason.UNAUTHORIZED,
            403 to Reason.UNAUTHORIZED,
            404 to Reason.NOT_FOUND,
            503 to Reason.STORAGE_UNAVAILABLE,
            500 to Reason.HTTP,
        )
        cases.forEach { (code, reason) ->
            server.enqueue(json("""{"detail":"server text never shown"}""", code))
            val e = assertThrows(MediaGalleryException::class.java) { client.page() }
            assertEquals("HTTP $code", reason, e.reason)
            assertFalse(e.message!!.contains("server text"))
        }
    }

    @Test
    fun `redirects are refused, never followed, for list, thumbnail and image`() {
        val elsewhere = MockWebServer().apply { start() }
        try {
            repeat(3) {
                server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", elsewhere.url("/steal").toString()))
            }
            listOf({ client.page() }, { client.thumbnail(item) }, { client.image(item) }).forEach { call ->
                val e = assertThrows(MediaGalleryException::class.java) { call() }
                assertEquals(Reason.REDIRECT_REFUSED, e.reason)
            }
            assertEquals("the token never left the paired origin", 0, elsewhere.requestCount)
        } finally {
            elsewhere.shutdown()
        }
    }

    @Test
    fun `an injected client that follows redirects still never follows one`() {
        // Review 5684792570: the guard must hold for the effective client, not
        // only for defaultHttp(). The target would answer 200 if it were reached.
        val elsewhere = MockWebServer().apply { start() }
        try {
            repeat(3) {
                elsewhere.enqueue(json(page(emptyList())))
                server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", elsewhere.url("/steal").toString()))
            }
            val following = okhttp3.OkHttpClient.Builder().followRedirects(true).followSslRedirects(true).build()
            val injected = MediaGalleryClient(server.url("/").toString().trimEnd('/'), "device-token", following)
            listOf({ injected.page() }, { injected.thumbnail(item) }, { injected.image(item) }).forEach { call ->
                val e = assertThrows(MediaGalleryException::class.java) { call() }
                assertEquals(Reason.REDIRECT_REFUSED, e.reason)
            }
            assertEquals(3, server.requestCount)
            assertEquals("the redirect target was never contacted", 0, elsewhere.requestCount)
        } finally {
            elsewhere.shutdown()
        }
    }

    @Test
    fun `thumbnail and image are fetched from paths derived from the id`() {
        val png = byteArrayOf(1, 2, 3)
        server.enqueue(bytes(png))
        server.enqueue(bytes(png, "image/png; charset=binary"))
        assertArrayEquals(png, client.thumbnail(item))
        assertArrayEquals(png, client.image(item))
        assertEquals("/api/v1/media/thumb_pic", server.takeRequest(1, TimeUnit.SECONDS)!!.path)
        val full = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("/api/v1/media/pic", full.path)
        assertEquals("Bearer device-token", full.getHeader("Authorization"))
        assertNull("no Range for a plain image fetch", full.getHeader("Range"))
    }

    @Test
    fun `oversized thumbnail by Content-Length is refused before the body is read`() {
        val huge = ByteArray((MediaGalleryClient.THUMBNAIL_MAX_BYTES + 1).toInt())
        server.enqueue(bytes(huge))
        val e = assertThrows(MediaGalleryException::class.java) { client.thumbnail(item) }
        assertEquals(Reason.TOO_LARGE, e.reason)
    }

    @Test
    fun `oversized thumbnail without Content-Length stops while streaming`() {
        val huge = ByteArray((MediaGalleryClient.THUMBNAIL_MAX_BYTES + 64 * 1024).toInt())
        server.enqueue(MockResponse().setHeader("Content-Type", "image/png").setChunkedBody(Buffer().write(huge), 64 * 1024))
        val e = assertThrows(MediaGalleryException::class.java) { client.thumbnail(item) }
        assertEquals(Reason.TOO_LARGE, e.reason)
    }

    @Test
    fun `thumbnail exactly at the cap is accepted`() {
        val atCap = ByteArray(MediaGalleryClient.THUMBNAIL_MAX_BYTES.toInt())
        server.enqueue(bytes(atCap))
        assertEquals(atCap.size, client.thumbnail(item).size)
    }

    @Test
    fun `image listed above the cap is never requested`() {
        val big = MediaGalleryContract.parseItem(
            image("big").put("size_bytes", MediaGalleryClient.IMAGE_MAX_BYTES + 1),
        )!!
        val e = assertThrows(MediaGalleryException::class.java) { client.image(big) }
        assertEquals(Reason.TOO_LARGE, e.reason)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `wrong content type is a protocol error`() {
        server.enqueue(bytes("<svg/>".toByteArray(), "text/html"))
        assertEquals(Reason.PROTOCOL, assertThrows(MediaGalleryException::class.java) { client.thumbnail(item) }.reason)
        server.enqueue(MockResponse().setHeader("Content-Type", "text/plain").setBody(page(emptyList())))
        assertEquals(Reason.PROTOCOL, assertThrows(MediaGalleryException::class.java) { client.page() }.reason)
    }

    @Test
    fun `list body over 1 MiB is refused`() {
        val padding = "x".repeat(MediaGalleryClient.LIST_MAX_BYTES.toInt())
        server.enqueue(json(page(listOf(image("a").put("pad", padding)))))
        assertEquals(Reason.TOO_LARGE, assertThrows(MediaGalleryException::class.java) { client.page() }.reason)
    }

    @Test
    fun `unreachable rig is a network error`() {
        val port = server.port
        server.shutdown()
        val offline = MediaGalleryClient("http://127.0.0.1:$port", "device-token")
        assertEquals(Reason.NETWORK, assertThrows(MediaGalleryException::class.java) { offline.page() }.reason)
        server = MockWebServer().apply { start() } // for tearDown
    }

    @Test
    fun `item without thumbnail makes no request`() {
        val bare = MediaGalleryContract.parseItem(
            image("bare").put("thumbnail_id", JSONObject.NULL).put("thumbnail_url", JSONObject.NULL),
        )!!
        assertEquals(Reason.NOT_FOUND, assertThrows(MediaGalleryException::class.java) { client.thumbnail(bare) }.reason)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `origin policy`() {
        val allowed = listOf(
            "https://rig.example.org", "https://100.101.50.10:8443", "http://192.168.1.27:8080",
            "http://10.0.0.5:8080", "http://172.16.0.1", "http://172.31.255.255:1", "http://127.0.0.1:8080",
            "http://localhost:8080", "http://[::1]:8080", "http://192.168.1.27:8080/",
        )
        allowed.forEach { MediaOriginPolicy.requireAllowed(it) }
        val refused = listOf(
            "http://rig.example.org", "http://100.101.50.10:8080", "http://172.32.0.1", "http://8.8.8.8",
            "http://192.168.1.027", "http://user:pw@192.168.1.27", "http://192.168.1.27/api",
            "http://192.168.1.27/?x=1", "ftp://192.168.1.27", "not a url",
        )
        refused.forEach { origin ->
            val e = assertThrows(origin, MediaGalleryException::class.java) { MediaOriginPolicy.requireAllowed(origin) }
            assertEquals(origin, Reason.ORIGIN_REFUSED, e.reason)
        }
        assertEquals(Reason.NOT_PAIRED, assertThrows(MediaGalleryException::class.java) { MediaOriginPolicy.requireAllowed(null) }.reason)
        assertEquals(Reason.NOT_PAIRED, assertThrows(MediaGalleryException::class.java) { MediaGalleryClient("http://127.0.0.1:1", "") }.reason)
        assertTrue(MediaOriginPolicy.isLoopbackOrRfc1918("127.8.9.10"))
    }
}
