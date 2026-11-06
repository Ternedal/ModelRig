package dk.ternedal.modelrig.net

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/** `kaliv-media-gallery/v1` as agreed on ModelRig #2275 (6468949085 + 6469270137). */
class MediaGalleryContractTest {

    @Test
    fun `valid page parses every field and derives paths from the id`() {
        val page = MediaGalleryContract.parsePage(page(listOf(image("img_1"), video("vid-2")), cursor = "\"c1\""))
        assertEquals(listOf("img_1", "vid-2"), page.items.map { it.id })
        assertEquals("c1", page.nextCursor)
        assertEquals(0, page.skipped)
        val image = page.items[0]
        assertEquals(MediaKind.IMAGE, image.kind)
        assertEquals("image/png", image.mimeType)
        assertEquals(Instant.parse("2026-10-28T12:00:00Z"), image.createdAt)
        assertEquals(1_234_567L, image.sizeBytes)
        assertEquals(1920, image.width)
        assertEquals(1080, image.height)
        assertNull(image.durationSeconds)
        assertEquals("/api/v1/media/img_1", image.mediaPath)
        assertEquals("/api/v1/media/thumb_img_1", image.thumbnailPath)
        val clip = page.items[1]
        assertEquals(MediaKind.VIDEO, clip.kind)
        assertEquals(65.5, clip.durationSeconds!!, 0.0)
        assertTrue(clip.supportsRange)
    }

    @Test
    fun `null next_cursor is the end of the list`() {
        assertNull(MediaGalleryContract.parsePage(page(listOf(image("a")), cursor = "null")).nextCursor)
    }

    @Test
    fun `unknown fields are ignored`() {
        val withExtra = image("a").put("prompt", "never shown").put("future_field", JSONObject().put("x", 1))
        assertEquals(1, MediaGalleryContract.parsePage(page(listOf(withExtra))).items.size)
    }

    @Test
    fun `an invalid item is skipped and counted, the rest of the page survives`() {
        val broken = listOf(
            image("../etc"),                                           // unsafe id
            image("a1").put("kind", "audio"),                          // unknown kind
            image("a2").put("mime_type", "image/svg+xml"),             // svg can carry script
            image("a3").put("mime_type", "video/mp4"),                 // kind/mime mismatch
            image("a4").put("created_at", "2026-10-28T14:00:00+02:00"), // not UTC
            image("a5").put("created_at", "i går"),
            image("a6").put("size_bytes", -1),
            image("a7").put("size_bytes", 1.5),
            image("a8").put("size_bytes", "12"),
            image("a9").put("width", -3),
            image("b1").put("duration_seconds", 4),                    // image with a duration
            video("b2").put("duration_seconds", -1),
            image("b3").put("projection", "fisheye"),
            image("b4").put("stereo", "anaglyph"),
            image("b5").put("url", "https://evil.example/api/v1/media/b5"),
            image("b6").put("url", "/api/v1/media/other"),
            image("b7").put("thumbnail_url", "/api/v1/media/someone_else"),
            image("b8").put("thumbnail_id", JSONObject.NULL),           // url without id
            image("b9").put("playback", "yes"),
            image("c1").put("playback", JSONObject().put("supports_range", "true")),
        )
        val good = image("ok")
        val parsed = MediaGalleryContract.parsePage(page(broken + good))
        assertEquals(listOf("ok"), parsed.items.map { it.id })
        assertEquals(broken.size, parsed.skipped)
    }

    @Test
    fun `integral-looking decimals are refused like on the phone`() {
        // Android's org.json yields Double for 1.0 and 1e3; the test library may
        // yield BigDecimal. Both must be refused the same way.
        val asText = page(listOf(image("x"))).replace("\"size_bytes\":1234567", "\"size_bytes\":1.0")
        assertEquals(1, MediaGalleryContract.parsePage(asText).skipped)
        val exponent = page(listOf(image("y"))).replace("\"size_bytes\":1234567", "\"size_bytes\":1e3")
        assertEquals(1, MediaGalleryContract.parsePage(exponent).skipped)
    }

    @Test
    fun `item without thumbnail is valid`() {
        val bare = image("bare").put("thumbnail_id", JSONObject.NULL).put("thumbnail_url", JSONObject.NULL)
        val item = MediaGalleryContract.parsePage(page(listOf(bare))).items.single()
        assertNull(item.thumbnailPath)
    }

    @Test
    fun `duplicate ids in one page are shown once`() {
        val parsed = MediaGalleryContract.parsePage(page(listOf(image("same"), image("same"))))
        assertEquals(1, parsed.items.size)
        assertEquals(1, parsed.skipped)
    }

    @Test
    fun `page-level damage rejects the whole page`() {
        val cases = listOf(
            "not json",
            """{"schema":"kaliv-media-gallery/v2","items":[],"next_cursor":null}""",
            """{"schema":"kaliv-media-gallery/v1","next_cursor":null}""",
            """{"schema":"kaliv-media-gallery/v1","items":{},"next_cursor":null}""",
            """{"schema":"kaliv-media-gallery/v1","items":[]}""",
            """{"schema":"kaliv-media-gallery/v1","items":[],"next_cursor":7}""",
            """{"schema":"kaliv-media-gallery/v1","items":[],"next_cursor":""}""",
            """{"schema":"kaliv-media-gallery/v1","items":[],"next_cursor":"has space"}""",
            page(List(101) { image("i$it") }),
        )
        cases.forEach { body ->
            val e = assertThrows(MediaGalleryException::class.java) { MediaGalleryContract.parsePage(body) }
            assertEquals(body.take(60), MediaGalleryException.Reason.PROTOCOL, e.reason)
        }
    }

    @Test
    fun `cursor is opaque but bounded printable ascii`() {
        assertTrue(MediaGalleryContract.isValidCursor("eyJ0IjoiMjAyNi0xMC0yOFQxMjowMDowMFoiLCJpZCI6ImEifQ=="))
        assertTrue(MediaGalleryContract.isValidCursor("a+b/c="))
        assertTrue(!MediaGalleryContract.isValidCursor(""))
        assertTrue(!MediaGalleryContract.isValidCursor("x".repeat(1025)))
        assertTrue(!MediaGalleryContract.isValidCursor("line\nbreak"))
        assertTrue(!MediaGalleryContract.isValidCursor("ø"))
    }

    @Test
    fun `media paths are only built from safe ids`() {
        assertEquals("/api/v1/media/A-z_9", MediaGalleryContract.mediaPath("A-z_9"))
        assertThrows(IllegalArgumentException::class.java) { MediaGalleryContract.mediaPath("a/b") }
        assertThrows(IllegalArgumentException::class.java) { MediaGalleryContract.mediaPath("x".repeat(129)) }
        val longest = image("x".repeat(128)).put("thumbnail_id", JSONObject.NULL).put("thumbnail_url", JSONObject.NULL)
        assertNotNull(MediaGalleryContract.parseItem(longest))
    }

    companion object {
        fun image(id: String): JSONObject = JSONObject()
            .put("id", id)
            .put("kind", "image")
            .put("mime_type", "image/png")
            .put("created_at", "2026-10-28T12:00:00Z")
            .put("size_bytes", 1_234_567)
            .put("width", 1920)
            .put("height", 1080)
            .put("duration_seconds", JSONObject.NULL)
            .put("projection", "flat")
            .put("stereo", "mono")
            .put("thumbnail_id", "thumb_$id")
            .put("url", "/api/v1/media/$id")
            .put("thumbnail_url", "/api/v1/media/thumb_$id")
            .put("playback", JSONObject().put("supports_range", false))

        fun video(id: String): JSONObject = image(id)
            .put("kind", "video")
            .put("mime_type", "video/mp4")
            .put("duration_seconds", 65.5)
            .put("projection", "equirectangular_360")
            .put("stereo", "top_bottom")
            .put("playback", JSONObject().put("supports_range", true))

        fun page(items: List<JSONObject>, cursor: String = "null"): String =
            """{"schema":"kaliv-media-gallery/v1","items":[${items.joinToString(",")}],"next_cursor":$cursor}"""
    }
}
