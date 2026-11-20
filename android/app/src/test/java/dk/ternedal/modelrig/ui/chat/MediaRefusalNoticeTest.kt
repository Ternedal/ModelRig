package dk.ternedal.modelrig.ui.chat

import dk.ternedal.modelrig.net.MediaJobRef
import dk.ternedal.modelrig.net.MediaRefusal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The line under an answer when the rig refused a picture or a clip (rig 20/11). */
class MediaRefusalNoticeTest {
    private fun image(code: String) = MediaRefusal(MediaJobRef.Kind.IMAGE, code)
    private fun video(code: String) = MediaRefusal(MediaJobRef.Kind.VIDEO, code)

    @Test
    fun `nothing refused means no line`() {
        assertNull(MediaRefusalNotice.text(emptyList(), queuedJobs = 0))
    }

    @Test
    fun `a job queued in the same turn means no line - the bubble is the answer`() {
        assertNull(MediaRefusalNotice.text(listOf(image("invalid_arguments")), queuedJobs = 1))
    }

    @Test
    fun `a busy rig says wait and names the picture`() {
        val text = MediaRefusalNotice.text(listOf(image("owner_limit")), queuedJobs = 0)!!
        assertTrue(text, text.startsWith("Riggen er optaget") && text.contains("billedet") && text.endsWith("(owner_limit)"))
        assertTrue(MediaRefusalNotice.text(listOf(video("queue_full")), 0)!!.contains("videoen"))
    }

    @Test
    fun `something the model sent says try again`() {
        for (code in listOf("invalid_arguments", "invalid_request", "profile_not_enabled")) {
            val text = MediaRefusalNotice.text(listOf(image(code)), 0)!!
            assertTrue(text, text.contains("bede om billedet igen") && text.endsWith("($code)"))
        }
    }

    @Test
    fun `no finished picture to animate is said as that`() {
        val text = MediaRefusalNotice.text(listOf(video("no_source_image")), 0)!!
        assertTrue(text, text.startsWith("Der er ikke et f\u00e6rdigt billede") && text.endsWith("(no_source_image)"))
    }

    @Test
    fun `an unknown code is shown as given, never interpreted`() {
        assertEquals("Riggen lavede ikke billedet. (media_jobs_api_off)", MediaRefusalNotice.text(listOf(image("media_jobs_api_off")), 0))
        assertEquals("Riggen lavede ikke videoen. (some_new_code)", MediaRefusalNotice.text(listOf(video("some_new_code")), 0))
    }

    @Test
    fun `the last refusal of the turn is the one that stands`() {
        val text = MediaRefusalNotice.text(listOf(image("invalid_arguments"), image("owner_limit")), 0)!!
        assertTrue(text, text.endsWith("(owner_limit)"))
    }
}
