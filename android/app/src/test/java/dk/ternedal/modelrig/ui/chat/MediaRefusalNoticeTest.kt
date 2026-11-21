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

    @Test
    fun `jobs queued before a confirmation card and after it are one turn`() {
        val a = MediaJobRef("0123456789abcdef0123456789abcdef", MediaJobRef.Kind.IMAGE)
        val b = MediaJobRef("fedcba9876543210fedcba9876543210", MediaJobRef.Kind.VIDEO)
        assertEquals(listOf(a, b), MediaTurnJobs.across(listOf(a), listOf(b)))
        assertEquals(listOf(a), MediaTurnJobs.across(listOf(a), listOf(a)))
        assertEquals(listOf(a), MediaTurnJobs.across(listOf(a), emptyList()))
        assertEquals(emptyList<MediaJobRef>(), MediaTurnJobs.across(emptyList(), emptyList()))
    }

    @Test
    fun `the conversation's pictures are named oldest first, clips left out, a repeat at its latest place`() {
        val a = MediaJobRef("0123456789abcdef0123456789abcdef", MediaJobRef.Kind.IMAGE)
        val b = MediaJobRef("fedcba9876543210fedcba9876543210", MediaJobRef.Kind.IMAGE)
        val clip = MediaJobRef("ffffffffffffffffffffffffffffffff", MediaJobRef.Kind.VIDEO)
        assertEquals(listOf(a.jobId, b.jobId), MediaTurnJobs.pictures(listOf(emptyList(), listOf(a), listOf(clip), listOf(b))))
        assertEquals(listOf(b.jobId, a.jobId), MediaTurnJobs.pictures(listOf(listOf(a), listOf(b), listOf(a))))
        assertEquals(emptyList<String>(), MediaTurnJobs.pictures(listOf(listOf(clip), emptyList())))
        val many = (0 until 40).map { listOf(MediaJobRef("%032x".format(it), MediaJobRef.Kind.IMAGE)) }
        val kept = MediaTurnJobs.pictures(many)
        assertEquals(MediaTurnJobs.MAX_PICTURES, kept.size)
        assertEquals("%032x".format(39), kept.last())
    }

    /**
     * #2462 review: a turn that queued a picture but said nothing was shown and then forgotten;
     * and a turn parked on a confirmation card kept its references on the card, in memory only.
     */
    @Test
    fun `a turn with a job is saved whether or not it has words`() {
        val job = listOf(MediaJobRef("a".repeat(32), MediaJobRef.Kind.IMAGE))
        assertTrue(MediaTurnJobs.worthSaving("Billedet er på vej.", job))
        assertTrue(MediaTurnJobs.worthSaving("", job))
        assertTrue(MediaTurnJobs.worthSaving("  \n", job))
        assertTrue("words alone, as before", MediaTurnJobs.worthSaving("hej", emptyList()))
        // nothing to show is still nothing to save: no blank bubble in the history
        assertTrue(!MediaTurnJobs.worthSaving("", emptyList()))
        assertTrue(!MediaTurnJobs.worthSaving("   ", emptyList()))
    }

    @Test
    fun `references saved with the parked turn are not saved again with the answer`() {
        // The card carries none, so the answer's union is only what was queued after the decision.
        val before = listOf(MediaJobRef("a".repeat(32), MediaJobRef.Kind.IMAGE))
        val after = listOf(MediaJobRef("b".repeat(32), MediaJobRef.Kind.VIDEO))
        assertEquals(after, MediaTurnJobs.across(emptyList(), after))
        assertEquals(emptyList<MediaJobRef>(), MediaTurnJobs.across(emptyList(), emptyList()))
        assertEquals("a card from an older build of this code still carries them", before + after,
            MediaTurnJobs.across(before, after))
    }
}
