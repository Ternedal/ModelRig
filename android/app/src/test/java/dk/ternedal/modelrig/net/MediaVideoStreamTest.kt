package dk.ternedal.modelrig.net

import android.net.Uri
import androidx.annotation.OptIn
import androidx.media3.common.PlaybackException
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.HttpDataSource
import dk.ternedal.modelrig.net.MediaGalleryContractTest.Companion.image
import dk.ternedal.modelrig.net.MediaGalleryContractTest.Companion.video
import dk.ternedal.modelrig.net.MediaGalleryException.Reason
import dk.ternedal.modelrig.ui.playbackReason
import dk.ternedal.modelrig.ui.videoAspect
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * The video path through Media3's real OkHttp data source, against MockWebServer.
 * Robolectric only for android.net.Uri inside DataSpec; no player, no device.
 */
@OptIn(UnstableApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class MediaVideoStreamTest {
    private lateinit var server: MockWebServer
    private lateinit var client: MediaGalleryClient
    private val clip get() = MediaGalleryContract.parseItem(video("clip"))!!

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        client = MediaGalleryClient(server.url("/").toString().trimEnd('/'), "device-token")
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun read(stream: MediaVideoStream, uri: String, position: Long, length: Long): ByteArray {
        val source = stream.dataSourceFactory.createDataSource()
        try {
            source.open(DataSpec.Builder().setUri(Uri.parse(uri)).setPosition(position).setLength(length).build())
            val out = ByteArray(length.toInt())
            var read = 0
            while (read < out.size) {
                val n = source.read(out, read, out.size - read)
                if (n < 0) break
                read += n
            }
            return out.copyOf(read)
        } finally {
            source.close()
        }
    }

    @Test
    fun `player requests a byte range from the derived path with the bearer token`() {
        val stream = client.video(clip)
        assertEquals(server.url("/api/v1/media/clip").toString(), stream.url)
        val body = ByteArray(50) { it.toByte() }
        server.enqueue(MockResponse().setResponseCode(206)
            .setHeader("Content-Type", "video/mp4")
            .setHeader("Content-Range", "bytes 100-149/10000")
            .setBody(Buffer().write(body)))
        assertArrayEquals(body, read(stream, stream.url, position = 100, length = 50))
        val request = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("/api/v1/media/clip", request.path)
        assertEquals("Bearer device-token", request.getHeader("Authorization"))
        assertEquals("bytes=100-149", request.getHeader("Range"))
    }

    @Test
    fun `a redirect is refused, never followed, by the player's data source`() {
        val elsewhere = MockWebServer().apply { start() }
        try {
            server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", elsewhere.url("/steal").toString()))
            val stream = client.video(clip)
            val e = assertThrows(HttpDataSource.InvalidResponseCodeException::class.java) {
                read(stream, stream.url, 0, 10)
            }
            assertEquals(302, e.responseCode)
            assertEquals("the redirect target was never contacted", 0, elsewhere.requestCount)
        } finally {
            elsewhere.shutdown()
        }
    }

    @Test
    fun `the origin guard stops any player request outside the paired rig`() {
        val elsewhere = MockWebServer().apply { start() }
        try {
            val stream = client.video(clip)
            val e = assertThrows(HttpDataSource.HttpDataSourceException::class.java) {
                read(stream, elsewhere.url("/api/v1/media/clip").toString(), 0, 10)
            }
            assertTrue(generateSequence<Throwable>(e) { it.cause }.any { it is MediaOriginRefusedIOException })
            assertEquals("the token never left the paired origin", 0, elsewhere.requestCount)
        } finally {
            elsewhere.shutdown()
        }
    }

    @Test
    fun `video needs range support and must be a video`() {
        val noRange = MediaGalleryContract.parseItem(video("flat").put("playback", JSONObject().put("supports_range", false)))!!
        assertEquals(Reason.UNPLAYABLE, assertThrows(MediaGalleryException::class.java) { client.video(noRange) }.reason)
        assertThrows(IllegalArgumentException::class.java) { client.video(MediaGalleryContract.parseItem(image("pic"))!!) }
        assertEquals("building a stream makes no request", 0, server.requestCount)
    }

    @Test
    fun `player errors map to the gallery's reasons`() {
        fun http(code: Int) = PlaybackException(
            "x",
            HttpDataSource.InvalidResponseCodeException(
                code, null, IOException(), emptyMap(), DataSpec(Uri.parse("http://127.0.0.1/x")), ByteArray(0),
            ),
            PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS,
        )
        assertEquals(Reason.REDIRECT_REFUSED, playbackReason(http(302)))
        assertEquals(Reason.UNAUTHORIZED, playbackReason(http(401)))
        assertEquals(Reason.NOT_FOUND, playbackReason(http(404)))
        assertEquals(Reason.STORAGE_UNAVAILABLE, playbackReason(http(503)))
        assertEquals(Reason.HTTP, playbackReason(http(500)))
        val guarded = PlaybackException(
            "x", IOException(MediaOriginRefusedIOException("refused")), PlaybackException.ERROR_CODE_IO_UNSPECIFIED,
        )
        assertEquals(Reason.ORIGIN_REFUSED, playbackReason(guarded))
        assertEquals(Reason.NETWORK, playbackReason(PlaybackException("x", null, PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED)))
        assertEquals(Reason.UNPLAYABLE, playbackReason(PlaybackException("x", null, PlaybackException.ERROR_CODE_DECODING_FAILED)))
        assertEquals(Reason.UNPLAYABLE, playbackReason(PlaybackException("x", null, PlaybackException.ERROR_CODE_PARSING_CONTAINER_MALFORMED)))
    }

    @Test
    fun `aspect ratio comes from the catalogue when sane`() {
        assertEquals(16f / 9f, videoAspect(clip), 0.001f)
        val square = MediaGalleryContract.parseItem(video("sq").put("width", 1000).put("height", 1000))!!
        assertEquals(1f, videoAspect(square), 0.001f)
        val unknown = MediaGalleryContract.parseItem(video("u").put("width", JSONObject.NULL).put("height", JSONObject.NULL))!!
        assertEquals(16f / 9f, videoAspect(unknown), 0.001f)
        val absurd = MediaGalleryContract.parseItem(video("a").put("width", 100000).put("height", 1))!!
        assertEquals(4f, videoAspect(absurd), 0.001f)
    }
}
