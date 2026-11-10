package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.JOB_ID
import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.SDXL
import dk.ternedal.modelrig.net.MediaJobException
import dk.ternedal.modelrig.net.MediaJobException.Reason
import dk.ternedal.modelrig.net.MediaJobProfile
import dk.ternedal.modelrig.net.MediaJobState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The generate screen's state machine, without Android. */
class MediaGeneratePresentationTest {
    private val other = MediaJobProfile("flux-b", listOf("text_to_image"), listOf(768 to 768), 30, 200)

    private fun job(state: MediaJobState, assetId: String? = null, cancelRequested: Boolean = false, error: String? = null,
                    id: String = JOB_ID) = MediaJob(id, state, "sdxl-a", assetId, error, cancelRequested)

    private fun ready(prompt: String = "a red bicycle") =
        MediaGenerate.editPrompt(MediaGenerate.profilesLoaded(MediaGenerateState(), listOf(SDXL, other)), prompt)

    private fun following(state: MediaJobState = MediaJobState.QUEUED) =
        MediaGenerate.submitted(MediaGenerate.submitting(ready()), job(state))

    @Test
    fun `profiles pick the first profile and its first size`() {
        val state = ready("")
        assertEquals(MediaGeneratePhase.Ready, state.phase)
        assertEquals("sdxl-a", state.profileId)
        assertEquals(1024 to 1024, state.size)
        assertFalse("no prompt yet", state.canSubmit)
    }

    @Test
    fun `no image profile, a 404 or an answer not understood is unavailable`() {
        assertTrue(MediaGenerate.profilesLoaded(MediaGenerateState(), emptyList()).phase is MediaGeneratePhase.Unavailable)
        for (reason in listOf(Reason.UNAVAILABLE, Reason.UNAUTHORIZED, Reason.NETWORK)) {
            val state = MediaGenerate.profilesFailed(MediaGenerateState(), MediaJobException(reason, "x"))
            assertTrue(state.phase is MediaGeneratePhase.Unavailable)
            assertNull(MediaGenerate.request(state))
        }
    }

    @Test
    fun `changing profile keeps a size it allows and resets one it does not`() {
        val state = MediaGenerate.selectProfile(MediaGenerate.selectSize(ready(), 832 to 1216), "flux-b")
        assertEquals(768 to 768, state.size)
        assertEquals(state, MediaGenerate.selectSize(state, 1024 to 1024))
        assertEquals(state, MediaGenerate.selectProfile(state, "not-listed"))
    }

    @Test
    fun `the prompt is capped by the profile and the request is trimmed`() {
        val state = MediaGenerate.editPrompt(ready(), "x".repeat(600))
        assertEquals(500, state.prompt.length)
        val request = MediaGenerate.request(MediaGenerate.editPrompt(ready(), "  a cat  "))!!
        assertEquals("a cat", request.prompt)
        assertEquals("text_to_image", request.task)
        assertNull(MediaGenerate.request(MediaGenerate.editPrompt(ready(), "   ")))
    }

    @Test
    fun `submit goes to following, and a queued job can be cancelled once`() {
        val state = following()
        assertTrue(state.polling)
        assertTrue(state.canCancel)
        assertFalse(state.canSubmit)
        val cancelling = MediaGenerate.cancelling(state)
        assertFalse(cancelling.canCancel)
        assertTrue(cancelling.polling)
    }

    @Test
    fun `polls move the job on and stop at a terminal state`() {
        var state = MediaGenerate.polled(following(), job(MediaJobState.RUNNING))
        assertEquals("Genererer …", MediaGenerate.stateLabel((state.phase as MediaGeneratePhase.Following).job))
        state = MediaGenerate.polled(state, job(MediaJobState.PUBLISHING))
        assertTrue(state.polling)
        state = MediaGenerate.polled(state, job(MediaJobState.COMPLETED, assetId = "asset_1"))
        assertFalse(state.polling)
        assertEquals("asset_1", state.completedAssetId)
        assertTrue("another picture can be started", state.canSubmit)
    }

    @Test
    fun `failed, cancelled and expired are finished without a picture`() {
        for ((terminal, label) in listOf(
            job(MediaJobState.FAILED, error = "interrupted_by_restart") to "Afbrudt: riggen genstartede",
            job(MediaJobState.FAILED, error = "something_new") to "Genereringen fejlede",
            job(MediaJobState.FAILED, error = "too_late") to "For sent at annullere: billedet var allerede ved at blive gemt",
            job(MediaJobState.CANCELLED) to "Annulleret",
            job(MediaJobState.EXPIRED, error = "expired_unclaimed") to
                "Udløbet: riggen nåede ikke at starte jobbet inden for et døgn",
        )) {
            val state = MediaGenerate.polled(following(), terminal)
            assertFalse(state.polling)
            assertNull(state.completedAssetId)
            assertEquals(label, MediaGenerate.stateLabel((state.phase as MediaGeneratePhase.Finished).job))
        }
    }

    @Test
    fun `a poll for another job is refused`() {
        val state = MediaGenerate.polled(following(), job(MediaJobState.COMPLETED, assetId = "asset_1", id = "f".repeat(32)))
        assertTrue(state.phase is MediaGeneratePhase.Unavailable)
        assertNull(state.completedAssetId)
    }

    @Test
    fun `a network blip keeps following, a lost job or a broken answer ends it`() {
        val blip = MediaGenerate.pollFailed(following(), MediaJobException(Reason.NETWORK, "Riggen kan ikke nås"))
        assertTrue(blip.polling)
        assertEquals("Riggen kan ikke nås", blip.error)
        assertEquals(MediaJobState.RUNNING,
            (MediaGenerate.polled(blip, job(MediaJobState.RUNNING)).phase as MediaGeneratePhase.Following).job.state)
        for (reason in listOf(Reason.NOT_FOUND, Reason.UNAVAILABLE, Reason.UNAUTHORIZED)) {
            val state = MediaGenerate.pollFailed(following(), MediaJobException(reason, "x"))
            assertFalse(state.polling)
            assertTrue(state.phase is MediaGeneratePhase.Unavailable)
        }
    }

    @Test
    fun `cancel answers are shown, and a cancel that came too late keeps following`() {
        val cancelled = MediaGenerate.cancelled(MediaGenerate.cancelling(following()), job(MediaJobState.CANCELLED))
        assertEquals(MediaJobState.CANCELLED, (cancelled.phase as MediaGeneratePhase.Finished).job.state)
        val requested = MediaGenerate.cancelled(MediaGenerate.cancelling(following(MediaJobState.RUNNING)),
            job(MediaJobState.RUNNING, cancelRequested = true))
        assertTrue(requested.polling)
        assertFalse("already requested", requested.canCancel)
        val gone = MediaGenerate.cancelFailed(MediaGenerate.cancelling(following()), MediaJobException(Reason.NOT_FOUND, "x"))
        assertTrue(gone.polling)
        assertEquals("Jobbet var allerede færdigt", gone.error)
        val none = MediaGenerate.cancelled(MediaGenerate.cancelling(following()), null)
        assertTrue(none.canCancel)
    }

    @Test
    fun `submit failures keep the form unless the rig is unavailable`() {
        val busy = MediaGenerate.submitFailed(MediaGenerate.submitting(ready()),
            MediaJobException(Reason.BUSY, "x", "active_limit"))
        assertEquals(MediaGeneratePhase.Ready, busy.phase)
        assertEquals("Du har allerede tre job i gang; vent til ét er færdigt", busy.error)
        assertEquals("a red bicycle", busy.prompt)
        assertEquals("Riggens kø er fuld; prøv igen om lidt", MediaGenerate.submitFailed(ready(),
            MediaJobException(Reason.BUSY, "x", "queue_full")).error)
        assertEquals("Profilen er ikke slået til på riggen", MediaGenerate.submitFailed(ready(),
            MediaJobException(Reason.INVALID_REQUEST, "x", "profile_not_enabled")).error)
        val off = MediaGenerate.submitFailed(ready(), MediaJobException(Reason.UNAVAILABLE, "Billedgenerering er ikke tilgængelig"))
        assertTrue(off.phase is MediaGeneratePhase.Unavailable)
    }

    @Test
    fun `again returns to the form with the prompt kept`() {
        val done = MediaGenerate.polled(following(), job(MediaJobState.FAILED, error = "generation_failed"))
        val again = MediaGenerate.again(done)
        assertEquals(MediaGeneratePhase.Ready, again.phase)
        assertEquals("a red bicycle", again.prompt)
    }
}
