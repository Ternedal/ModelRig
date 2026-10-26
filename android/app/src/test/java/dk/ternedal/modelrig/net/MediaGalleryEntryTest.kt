package dk.ternedal.modelrig.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MediaGalleryEntryTest {
    @Test
    fun parsesVideoForVRPlayback() {
        val entry = MediaGalleryEntry.parse(
            "clip_1", "video", "equirectangular_180", "left_right",
            "thumb_1", "/api/v1/media/clip_1", "/api/v1/media/thumb_1"
        )
        assertEquals("/api/v1/media/clip_1", entry?.mediaPath())
        assertEquals("equirectangular_180", entry?.projection)
        assertEquals("left_right", entry?.stereo)
    }

    @Test
    fun rejectsUntrustedAbsoluteUrl() {
        assertNull(MediaGalleryEntry.parse(
            "clip_1", "video", "flat", "mono",
            null, "https://attacker.example/clip.mp4", null
        ))
    }

    @Test
    fun rejectsPathTraversal() {
        assertNull(MediaGalleryEntry.parse(
            "../private", "image", "flat", "mono",
            null, "/api/v1/media/../private", null
        ))
    }

    @Test
    fun rejectsInvalidThumbnail() {
        assertNull(MediaGalleryEntry.parse(
            "clip_1", "video", "flat", "mono",
            "thumb_1", "/api/v1/media/clip_1", "/api/v1/media/other"
        ))
    }
}
