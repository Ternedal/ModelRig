package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import dk.ternedal.modelrig.desktop.net.DesktopMediaException.Reason
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.OutputStream
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** Wire behaviour of the desktop media client against a real HTTP boundary (no rig). */
class DesktopMediaClientTest {
    private val id = "0123456789abcdef0123456789abcdef"

    private fun server(handler: (HttpExchange) -> Unit): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange ->
            try {
                handler(exchange)
            } finally {
                exchange.close()
            }
        }
        server.start()
        return server
    }

    private fun HttpExchange.reply(status: Int, type: String?, body: ByteArray) {
        if (type != null) responseHeaders.add("Content-Type", type)
        sendResponseHeaders(status, if (body.isEmpty()) -1 else body.size.toLong())
        if (body.isNotEmpty()) responseBody.use { it.write(body) }
    }

    private fun client(server: HttpServer, token: String? = "desktop-token") =
        DesktopMediaClient("http://127.0.0.1:${server.address.port}/", token)

    private fun <T> withServer(handler: (HttpExchange) -> Unit, block: (HttpServer) -> T): T {
        val server = server(handler)
        try {
            return block(server)
        } finally {
            server.stop(0)
        }
    }

    private fun running() =
        """{"schema":"kaliv-media-job/v1","id":"$id","state":"running","profile_id":"sdxl-a","asset_id":null,"asset_url":null,"error":null,"cancel_requested":false}"""

    @Test
    fun statusAsksTheJobRouteWithTheBearerAndReadsTheJob() {
        val authorization = AtomicReference<String>()
        val path = AtomicReference<String>()
        val method = AtomicReference<String>()
        val job = withServer({ exchange ->
            authorization.set(exchange.requestHeaders.getFirst("Authorization"))
            path.set(exchange.requestURI.rawPath)
            method.set(exchange.requestMethod)
            exchange.reply(200, "application/json; charset=utf-8", running().toByteArray())
        }) { client(it).status(id) }
        assertEquals(DesktopMediaJobState.RUNNING, job.state)
        assertEquals("Bearer desktop-token", authorization.get())
        assertEquals("/api/v1/media/jobs/$id", path.get())
        assertEquals("GET", method.get())
    }

    @Test
    fun aBlankTokenSendsNoAuthorizationHeader() {
        val authorization = AtomicReference<String?>("unset")
        withServer({ exchange ->
            authorization.set(exchange.requestHeaders.getFirst("Authorization"))
            exchange.reply(200, "application/json", running().toByteArray())
        }) { client(it, token = " ").status(id) }
        assertEquals(null, authorization.get())
    }

    @Test
    fun httpStatusMapsToADistinctReason() {
        val cases = listOf(
            Triple(401, """{"detail":"unauthorized"}""", Reason.UNAUTHORIZED),
            Triple(403, "{}", Reason.UNAUTHORIZED),
            Triple(404, """{"detail":"job_not_found"}""", Reason.NOT_FOUND),
            // The route itself is absent: the switch is off on this rig.
            Triple(404, """{"detail":"Not Found"}""", Reason.UNAVAILABLE),
            Triple(405, "", Reason.UNAVAILABLE),
            Triple(501, "", Reason.UNAVAILABLE),
            Triple(500, "", Reason.TRANSIENT),
            Triple(502, "", Reason.TRANSIENT),
            Triple(503, """{"detail":"work_area_unavailable"}""", Reason.TRANSIENT),
            Triple(504, "", Reason.TRANSIENT),
            Triple(418, "", Reason.HTTP),
        )
        for ((status, body, reason) in cases) {
            val e = withServer({ it.reply(status, "application/json", body.toByteArray()) }) { server ->
                assertFailsWith<DesktopMediaException>("$status $body") { client(server).status(id) }
            }
            assertEquals(reason, e.reason, "$status $body")
        }
    }

    @Test
    fun aStatusAnswerThatIsNotTheJobContractIsUnavailable() {
        val wrongType = withServer({ it.reply(200, "text/html", running().toByteArray()) }) { server ->
            assertFailsWith<DesktopMediaException> { client(server).status(id) }
        }
        assertEquals(Reason.UNAVAILABLE, wrongType.reason)
        val tooBig = ByteArray((DesktopMediaClient.STATUS_MAX_BYTES + 1).toInt()) { ' '.code.toByte() }
        val huge = withServer({ it.reply(200, "application/json", tooBig) }) { server ->
            assertFailsWith<DesktopMediaException> { client(server).status(id) }
        }
        assertEquals(Reason.UNAVAILABLE, huge.reason)
        // An id that is not a job id never becomes a request.
        val requests = AtomicInteger()
        val bad = withServer({ requests.incrementAndGet(); it.reply(200, "application/json", running().toByteArray()) }) { server ->
            assertFailsWith<DesktopMediaException> { client(server).status("../../healthz") }
        }
        assertEquals(Reason.NOT_FOUND, bad.reason)
        assertEquals(0, requests.get())
    }

    @Test
    fun aRedirectIsRefusedAndNeverFollowed() {
        val elsewhereRequests = AtomicInteger()
        val elsewhere = server { exchange ->
            elsewhereRequests.incrementAndGet()
            exchange.reply(200, "application/json", running().toByteArray())
        }
        try {
            val target = "http://127.0.0.1:${elsewhere.address.port}/steal"
            for (call in listOf<(DesktopMediaClient) -> Unit>(
                { it.status(id) },
                { it.image("img_1") },
                { it.videoInto("clip_1", ByteArrayOutputStream()) },
            )) {
                val e = withServer({ exchange ->
                    exchange.responseHeaders.add("Location", target)
                    exchange.reply(302, null, ByteArray(0))
                }) { server -> assertFailsWith<DesktopMediaException> { call(client(server)) } }
                assertEquals(Reason.REDIRECT_REFUSED, e.reason)
            }
            assertEquals(0, elsewhereRequests.get())
        } finally {
            elsewhere.stop(0)
        }
    }

    @Test
    fun imageIsFetchedFromThePathDerivedFromTheIdAndMustBeAnImage() {
        val png = ByteArray(2048) { (it % 251).toByte() }
        val path = AtomicReference<String>()
        val authorization = AtomicReference<String>()
        val bytes = withServer({ exchange ->
            path.set(exchange.requestURI.rawPath)
            authorization.set(exchange.requestHeaders.getFirst("Authorization"))
            exchange.reply(200, "image/png", png)
        }) { client(it).image("img_abc-1") }
        assertContentEquals(png, bytes)
        assertEquals("/api/v1/media/img_abc-1", path.get())
        assertEquals("Bearer desktop-token", authorization.get())

        val html = withServer({ it.reply(200, "text/html", "<svg/>".toByteArray()) }) { server ->
            assertFailsWith<DesktopMediaException> { client(server).image("img_1") }
        }
        assertEquals(Reason.PROTOCOL, html.reason)
        val gone = withServer({ it.reply(404, "application/json", "{}".toByteArray()) }) { server ->
            assertFailsWith<DesktopMediaException> { client(server).image("img_1") }
        }
        assertEquals(Reason.NOT_FOUND, gone.reason)
        val storage = withServer({ it.reply(503, "application/json", "{}".toByteArray()) }) { server ->
            assertFailsWith<DesktopMediaException> { client(server).image("img_1") }
        }
        assertEquals(Reason.TRANSIENT, storage.reason)
        val requests = AtomicInteger()
        val unsafe = withServer({ requests.incrementAndGet(); it.reply(200, "image/png", png) }) { server ->
            assertFailsWith<DesktopMediaException> { client(server).image("../secret") }
        }
        assertEquals(Reason.NOT_FOUND, unsafe.reason)
        assertEquals(0, requests.get())
    }

    @Test
    fun aClipIsStreamedOnceIntoTheCallersStreamAndMustBeAVideo() {
        val clip = ByteArray(300_000) { (it % 13).toByte() }
        val out = ByteArrayOutputStream()
        val accept = AtomicReference<String>()
        val written = withServer({ exchange ->
            accept.set(exchange.requestHeaders.getFirst("Accept"))
            exchange.reply(200, "video/mp4", clip)
        }) { client(it).videoInto("clip_1", out) }
        assertEquals(clip.size.toLong(), written)
        assertContentEquals(clip, out.toByteArray())
        assertEquals("video/mp4", accept.get())

        val sink = ByteArrayOutputStream()
        val picture = withServer({ it.reply(200, "image/png", clip) }) { server ->
            assertFailsWith<DesktopMediaException> { client(server).videoInto("clip_1", sink) }
        }
        assertEquals(Reason.PROTOCOL, picture.reason)
        assertEquals(0, sink.size())
    }

    @Test
    fun aFailingDestinationIsTheCallersErrorNotTheRigs() {
        val clip = ByteArray(200_000) { 1 }
        val full = object : OutputStream() {
            override fun write(b: Int) {
                throw IOException("disk full")
            }

            override fun write(b: ByteArray, off: Int, len: Int) {
                throw IOException("disk full")
            }
        }
        withServer({ it.reply(200, "video/mp4", clip) }) { server ->
            assertFailsWith<IOException> { client(server).videoInto("clip_1", full) }
        }
    }

    @Test
    fun anUnreachableRigIsANetworkErrorAndABadAddressIsRefusedUpFront() {
        val closed = server { it.reply(200, "application/json", running().toByteArray()) }
        val port = closed.address.port
        closed.stop(0)
        val e = assertFailsWith<DesktopMediaException> {
            DesktopMediaClient("http://127.0.0.1:$port", "t").status(id)
        }
        assertEquals(Reason.NETWORK, e.reason)
        for (address in listOf("", "   ", "ftp://127.0.0.1", "not a url", "localhost:8080")) {
            val refused = assertFailsWith<DesktopMediaException>(address) { DesktopMediaClient(address, "t") }
            assertEquals(Reason.UNAVAILABLE, refused.reason, address)
        }
    }
}
