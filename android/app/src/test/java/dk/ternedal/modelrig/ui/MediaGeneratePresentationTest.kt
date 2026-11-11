package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobCancel
import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.JOB_ID
import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.SDXL
import dk.ternedal.modelrig.net.MediaJobException
import dk.ternedal.modelrig.net.MediaJobException.Reason
import dk.ternedal.modelrig.net.MediaJobProfile
import dk.ternedal.modelrig.net.MediaJobState
import dk.ternedal.modelrig.net.MediaModality
import dk.ternedal.modelrig.net.MediaJobContractTest.Companion.WAN
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The generate screen's state machine, without Android. */
class MediaGeneratePresentationTest {
    private val other = MediaJobProfile("flux-b", MediaModality.IMAGE, listOf("text_to_image"), listOf(768 to 768), 30, 200)

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
        val cancelled = MediaGenerate.cancelled(MediaGenerate.cancelling(following()), MediaJobCancel("cancelled", job(MediaJobState.CANCELLED)))
        assertEquals(MediaJobState.CANCELLED, (cancelled.phase as MediaGeneratePhase.Finished).job.state)
        val requested = MediaGenerate.cancelled(MediaGenerate.cancelling(following(MediaJobState.RUNNING)),
            MediaJobCancel("requested", job(MediaJobState.RUNNING, cancelRequested = true)))
        assertTrue(requested.polling)
        assertFalse("already requested", requested.canCancel)
        val gone = MediaGenerate.cancelFailed(MediaGenerate.cancelling(following()), MediaJobException(Reason.NOT_FOUND, "x"))
        assertTrue(gone.polling)
        assertEquals("Jobbet var allerede færdigt", gone.error)
        val none = MediaGenerate.cancelled(MediaGenerate.cancelling(following()), MediaJobCancel("requested", null))
        assertTrue(none.canCancel)
    }

    @Test
    fun `cancel too late during publishing clears cancelling, says so, and keeps following to completion`() {
        val publishing = MediaGenerate.polled(following(MediaJobState.RUNNING), job(MediaJobState.PUBLISHING))
        assertFalse("nothing to cancel while the picture is being saved", publishing.canCancel)
        // The race: cancel was pressed while the phone still showed running.
        val racing = MediaGenerate.cancelling(following(MediaJobState.RUNNING))
        val late = MediaGenerate.cancelled(racing, MediaJobCancel("too_late", job(MediaJobState.PUBLISHING)))
        val phase = late.phase as MediaGeneratePhase.Following
        assertFalse("no more \"Annulleres …\"", phase.cancelling)
        assertTrue(phase.tooLate)
        assertEquals(MediaGenerate.TOO_LATE_TEXT, late.error)
        assertTrue("still following", late.polling)
        assertFalse(late.canCancel)
        assertEquals("Gemmer billedet …", MediaGenerate.stateLabel(phase.job))
        val stillLate = MediaGenerate.polled(late, job(MediaJobState.PUBLISHING))
        assertTrue((stillLate.phase as MediaGeneratePhase.Following).tooLate)
        assertEquals(MediaGenerate.TOO_LATE_TEXT, stillLate.error)
        val done = MediaGenerate.polled(stillLate, job(MediaJobState.COMPLETED, assetId = "asset_1"))
        assertEquals("asset_1", done.completedAssetId)
        assertEquals("the reason stays with the finished picture", MediaGenerate.TOO_LATE_TEXT, done.error)
        assertNull("a new picture starts clean", MediaGenerate.again(done).error)
        // too_late without a job in the answer keeps following too.
        val bare = MediaGenerate.cancelled(MediaGenerate.cancelling(following(MediaJobState.RUNNING)), MediaJobCancel("too_late", null))
        assertTrue(bare.polling)
        assertFalse((bare.phase as MediaGeneratePhase.Following).cancelling)
        assertEquals(MediaGenerate.TOO_LATE_TEXT, bare.error)
    }

    @Test
    fun `transient poll failures keep the job, back off, stall after a bound, and resume`() {
        var state = following(MediaJobState.RUNNING)
        assertEquals(MediaGenerate.POLL_MILLIS, MediaGenerate.pollDelay(state))
        val delays = mutableListOf<Long>()
        for (reason in listOf(Reason.TRANSIENT, Reason.NETWORK, Reason.TRANSIENT, Reason.TRANSIENT, Reason.NETWORK)) {
            state = MediaGenerate.pollFailed(state, MediaJobException(reason, "Riggen svarer ikke lige nu"))
            assertTrue("$reason keeps following", state.polling)
            assertEquals(JOB_ID, (state.phase as MediaGeneratePhase.Following).job.id)
            delays += MediaGenerate.pollDelay(state)
        }
        assertEquals(listOf(4_000L, 8_000L, 16_000L, 30_000L, 30_000L), delays)
        state = MediaGenerate.pollFailed(state, MediaJobException(Reason.TRANSIENT, "x"))
        val stalled = state.phase as MediaGeneratePhase.Stalled
        assertFalse("bounded: no more polls", state.polling)
        assertEquals("the job id is kept", JOB_ID, stalled.job.id)
        val resumed = MediaGenerate.resume(state)
        assertTrue(resumed.polling)
        assertEquals(MediaGenerate.POLL_MILLIS, MediaGenerate.pollDelay(resumed))
        // A good answer ends a run of failures.
        val blip = MediaGenerate.pollFailed(following(MediaJobState.RUNNING), MediaJobException(Reason.TRANSIENT, "x"))
        val ok = MediaGenerate.polled(blip, job(MediaJobState.RUNNING))
        assertEquals(0, (ok.phase as MediaGeneratePhase.Following).failures)
        assertNull(ok.error)
    }

    @Test
    fun `the too-late note survives a stall and a resume through to the finished picture`() {
        var state = MediaGenerate.cancelled(MediaGenerate.cancelling(following(MediaJobState.RUNNING)),
            MediaJobCancel("too_late", job(MediaJobState.PUBLISHING)))
        repeat(MediaGenerate.MAX_POLL_FAILURES) {
            state = MediaGenerate.pollFailed(state, MediaJobException(Reason.TRANSIENT, "x"))
        }
        val stalled = state.phase as MediaGeneratePhase.Stalled
        assertTrue("the flag travels with the stalled job", stalled.tooLate)
        val resumed = MediaGenerate.resume(state)
        assertTrue((resumed.phase as MediaGeneratePhase.Following).tooLate)
        assertEquals(MediaGenerate.TOO_LATE_TEXT, resumed.error)
        assertFalse("still nothing to cancel", resumed.canCancel)
        val done = MediaGenerate.polled(MediaGenerate.polled(resumed, job(MediaJobState.PUBLISHING)),
            job(MediaJobState.COMPLETED, assetId = "asset_1"))
        assertEquals("asset_1", done.completedAssetId)
        assertEquals(MediaGenerate.TOO_LATE_TEXT, done.error)
        // Without a too-late cancel, a stall and resume carry no note.
        var plain = following(MediaJobState.RUNNING)
        repeat(MediaGenerate.MAX_POLL_FAILURES) { plain = MediaGenerate.pollFailed(plain, MediaJobException(Reason.TRANSIENT, "x")) }
        assertFalse((plain.phase as MediaGeneratePhase.Stalled).tooLate)
        assertNull(MediaGenerate.polled(MediaGenerate.resume(plain), job(MediaJobState.RUNNING)).error)
    }

    @Test
    fun `a video profile submits text_to_video through the same lifecycle`() {
        var state = MediaGenerate.profilesLoaded(MediaGenerateState(), listOf(SDXL, WAN))
        assertEquals("Generér billede eller video", MediaGenerate.title(state))
        state = MediaGenerate.editPrompt(MediaGenerate.selectProfile(state, "wan-t2v"), "a dog running")
        assertEquals(832 to 480, state.size)
        val request = MediaGenerate.request(state)!!
        assertEquals("text_to_video" to "wan-t2v", request.task to request.profileId)
        val videoJob = MediaJob(JOB_ID, MediaJobState.PUBLISHING, "wan-t2v", null, null, false)
        state = MediaGenerate.submitted(MediaGenerate.submitting(state), MediaJob(JOB_ID, MediaJobState.QUEUED, "wan-t2v", null, null, false))
        state = MediaGenerate.polled(state, videoJob)
        assertEquals("Gemmer videoen …", MediaGenerate.stateLabel(videoJob, MediaGenerate.modalityOf(state, videoJob)))
        // Transient failures keep a video job the same way (job-ID continuity).
        state = MediaGenerate.pollFailed(state, MediaJobException(Reason.TRANSIENT, "x"))
        assertEquals(JOB_ID, (state.phase as MediaGeneratePhase.Following).job.id)
        state = MediaGenerate.polled(state, MediaJob(JOB_ID, MediaJobState.COMPLETED, "wan-t2v", "asset_v1", null, false))
        assertEquals("asset_v1", state.completedAssetId)
    }

    @Test
    fun `with video off on the rig the screen is image only`() {
        val state = MediaGenerate.profilesLoaded(MediaGenerateState(), listOf(SDXL))
        assertEquals("Generér billede", MediaGenerate.title(state))
        assertEquals("text_to_image", MediaGenerate.request(MediaGenerate.editPrompt(state, "x"))!!.task)
        val onlyVideo = MediaGenerate.editPrompt(MediaGenerate.profilesLoaded(MediaGenerateState(), listOf(WAN)), "x")
        assertEquals("text_to_video", MediaGenerate.request(onlyVideo)!!.task)
        assertEquals("Gemmer billedet …", MediaGenerate.stateLabel(MediaJob(JOB_ID, MediaJobState.PUBLISHING, "unknown", null, null, false)))
    }

    @Test
    fun `an auth failure while polling stays distinct from a transient one`() {
        val auth = MediaGenerate.pollFailed(following(MediaJobState.RUNNING),
            MediaJobException(Reason.UNAUTHORIZED, "Parringen er ikke længere gyldig"))
        assertEquals(MediaGeneratePhase.Unavailable("Parringen er ikke længere gyldig"), auth.phase)
        assertFalse(auth.polling)
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
