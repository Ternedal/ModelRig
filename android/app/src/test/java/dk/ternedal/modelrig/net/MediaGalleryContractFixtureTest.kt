package dk.ternedal.modelrig.net

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.time.Instant

/**
 * The shared `kaliv-media-gallery/v1` fixture (#2275 backlog item 19). Its `page` is what the
 * Python catalog emits (tests/workflow_media_gallery_contract_fixture.py keeps that true); every
 * one of its items must parse here, and every `invalid_items` entry must be skipped.
 */
class MediaGalleryContractFixtureTest {
    private fun fixture(): JSONObject {
        val cwd = File(System.getProperty("user.dir"))
        val file = generateSequence(cwd) { it.parentFile }
            .map { File(it, "contracts/kaliv-media-gallery-v1-fixtures.json") }
            .firstOrNull { it.isFile }
            ?: error("shared gallery fixture not found from ${cwd.absolutePath}")
        return JSONObject(file.readText(Charsets.UTF_8))
    }

    @Test
    fun everyItemTheCatalogEmitsParsesWithNothingSkipped() {
        val root = fixture()
        assertEquals("kaliv-media-gallery-fixtures/v1", root.getString("schema"))
        val pageJson = root.getJSONObject("page")
        val page = MediaGalleryContract.parsePage(pageJson.toString())
        val expected = pageJson.getJSONArray("items")
        assertEquals(0, page.skipped)
        assertEquals(expected.length(), page.items.size)
        assertNull(page.nextCursor)
        for (i in 0 until expected.length()) {
            val want = expected.getJSONObject(i)
            val got = page.items[i]
            assertEquals(want.getString("id"), got.id)
            assertEquals(want.getString("kind"), got.kind.wire)
            assertEquals(want.getString("mime_type"), got.mimeType)
            assertEquals(Instant.parse(want.getString("created_at")), got.createdAt)
            assertEquals(want.getLong("size_bytes"), got.sizeBytes)
            assertEquals(want.optIntOrNull("width"), got.width)
            assertEquals(want.optIntOrNull("height"), got.height)
            assertEquals(if (want.isNull("duration_seconds")) null else want.getDouble("duration_seconds"), got.durationSeconds)
            assertEquals(want.getString("projection"), got.projection)
            assertEquals(want.getString("stereo"), got.stereo)
            assertEquals(if (want.isNull("thumbnail_id")) null else want.getString("thumbnail_id"), got.thumbnailId)
            assertEquals(want.getJSONObject("playback").getBoolean("supports_range"), got.supportsRange)
        }
        // The VR180 sample keeps its layout and its thumbnail; the producer-shaped ones default to flat mono.
        val vr = page.items.single { it.id == "vid_vr180_lr" }
        assertEquals("equirectangular_180" to "left_right", vr.projection to vr.stereo)
        assertEquals(MediaGalleryContract.mediaPath("img_png_1024"), vr.thumbnailPath)
        assertTrue(page.items.single { it.id == "vid_flat_writer_shape" }.isFlat)
    }

    @Test
    fun everyInvalidItemIsSkippedAndCounted() {
        val cases = fixture().getJSONArray("invalid_items")
        assertTrue(cases.length() > 0)
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val item = case.getJSONObject("item")
            assertNull(case.getString("name"), MediaGalleryContract.parseItem(item))
            val page = MediaGalleryContract.parsePage(
                JSONObject().put("schema", MediaGalleryContract.SCHEMA)
                    .put("items", JSONArray().put(item)).put("next_cursor", JSONObject.NULL).toString(),
            )
            assertEquals(case.getString("name"), 1, page.skipped)
            assertEquals(case.getString("name"), 0, page.items.size)
        }
    }

    @Test
    fun theDropShapeIsNamedSoNoServerReintroducesIt() {
        val names = fixture().getJSONArray("invalid_items").let { a -> (0 until a.length()).map { a.getJSONObject(it).getString("name") } }
        assertTrue("missing_projection_and_stereo" in names)
        val base = fixture().getJSONObject("page").getJSONArray("items").getJSONObject(2)
        assertNotNull(MediaGalleryContract.parseItem(base))
    }

    private fun JSONObject.optIntOrNull(key: String): Int? = if (isNull(key)) null else getInt(key)
}
