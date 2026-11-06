package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class MediaJobPresentationTest {

    private fun job(state: MediaJobState, error: String? = null) = MediaJob(
        id = "j1", state = state, profileId = "sdxl-base",
        createdAt = Instant.EPOCH, updatedAt = Instant.EPOCH,
        expiresAt = if (state == MediaJobState.QUEUED) Instant.EPOCH.plusSeconds(86_400) else null,
        assetId = if (state == MediaJobState.COMPLETED) "img_1" else null, error = error,
    )

    @Test
    fun `every state has a Danish label`() {
        for (s in MediaJobState.entries) assertTrue(MediaJobPresentation.stateLabel(s).isNotBlank())
        assertEquals("Udløbet", MediaJobPresentation.stateLabel(MediaJobState.EXPIRED))
    }

    @Test
    fun `active jobs have no outcome yet`() {
        for (s in listOf(MediaJobState.QUEUED, MediaJobState.RUNNING, MediaJobState.PUBLISHING)) {
            assertNull(MediaJobPresentation.outcome(job(s)))
        }
    }

    @Test
    fun `expired explains the 24 hours and allows a resubmit`() {
        val o = MediaJobPresentation.outcome(job(MediaJobState.EXPIRED, "expired_unclaimed"))!!
        assertTrue(o.message.contains("24 timer"))
        assertEquals(MediaJobRetry.RESUBMIT, o.retry)
    }

    @Test
    fun `retry follows the cause`() {
        fun retry(code: String) = MediaJobPresentation.outcome(job(MediaJobState.FAILED, code))!!.retry
        assertEquals(MediaJobRetry.FIX_INPUT, retry("generation_request_rejected"))
        assertEquals(MediaJobRetry.FIX_INPUT, retry("source_image_unavailable"))
        assertEquals(MediaJobRetry.LATER, retry("gpu_busy"))
        assertEquals(MediaJobRetry.LATER, retry("gpu_unavailable"))
        assertEquals(MediaJobRetry.LATER, retry("gpu_memory_retained"))
        assertEquals(MediaJobRetry.RESUBMIT, retry("generation_failed"))
        assertEquals(MediaJobRetry.RESUBMIT, retry("interrupted by restart"))
    }

    @Test
    fun `restart codes and the older sentences read the same`() {
        fun outcome(error: String) = MediaJobPresentation.outcome(job(MediaJobState.FAILED, error))
        assertEquals(outcome("interrupted_by_restart"), outcome("interrupted by restart"))
        assertEquals(outcome("interrupted_during_publication"), outcome("interrupted during publication"))
        assertFalse(outcome("interrupted_by_restart")!!.message == "Jobbet fejlede.")
    }

    @Test
    fun `an unknown error is generic and never echoed`() {
        val o = MediaJobPresentation.outcome(job(MediaJobState.FAILED, "C:\\Kaliv\\secret path"))!!
        assertEquals("Jobbet fejlede.", o.message)
        assertFalse(o.message.contains("Kaliv"))
    }

    @Test
    fun `completed and cancelled offer no retry`() {
        assertEquals(MediaJobRetry.NONE, MediaJobPresentation.outcome(job(MediaJobState.COMPLETED))!!.retry)
        assertEquals(MediaJobRetry.NONE, MediaJobPresentation.outcome(job(MediaJobState.CANCELLED))!!.retry)
    }

    @Test
    fun `polling stops at a terminal state`() {
        for (s in MediaJobState.entries.filter { it.terminal }) assertNull(MediaJobPolling.nextDelayMs(s, 0))
    }

    @Test
    fun `polling backs off to a cap per state`() {
        assertEquals(2_000L, MediaJobPolling.nextDelayMs(MediaJobState.RUNNING, 0))
        assertEquals(4_000L, MediaJobPolling.nextDelayMs(MediaJobState.RUNNING, 1))
        assertEquals(15_000L, MediaJobPolling.nextDelayMs(MediaJobState.RUNNING, 10))
        assertEquals(60_000L, MediaJobPolling.nextDelayMs(MediaJobState.QUEUED, 10))
        assertEquals(120_000L, MediaJobPolling.nextDelayMs(MediaJobState.RUNNING, 10, lastRequestFailed = true))
        // Before the first answer the state is unknown: poll, never stop.
        assertEquals(2_000L, MediaJobPolling.nextDelayMs(null, 0))
        // No overflow however long it runs.
        assertEquals(60_000L, MediaJobPolling.nextDelayMs(MediaJobState.QUEUED, Int.MAX_VALUE))
    }
}
