package dk.ternedal.modelrig.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MediaGalleryEntryTest {
    @Test
    fun parsesVideoForVRPlayback() {
        val entry = MediaGalleryEntry.parse(
            "clip_1", "video", "equirectangular_180", "left_right",
            "thumb_1", "/experimental/media/clip_1", "/experimental/media/thumb_1"
        )
        assertEquals("/experimental/media/clip_1", entry?.mediaPath())
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
            null, "/experimental/media/../private", null
        ))
    }

    @Test
    fun rejectsInvalidThumbnail() {
        assertNull(MediaGalleryEntry.parse(
            "clip_1", "video", "flat", "mono",
            "thumb_1", "/experimental/media/clip_1", "/experimental/media/other"
        ))
    }
}
