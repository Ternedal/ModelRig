package dk.ternedal.modelrig.ui.chat

import android.graphics.Bitmap
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.geometry.Offset
import androidx.media3.datasource.DataSource
import dk.ternedal.modelrig.net.MediaGalleryException
import dk.ternedal.modelrig.net.MediaGallerySource
import dk.ternedal.modelrig.net.MediaItem
import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobCancel
import dk.ternedal.modelrig.net.MediaJobException
import dk.ternedal.modelrig.net.MediaJobException.Reason
import dk.ternedal.modelrig.net.MediaJobProfile
import dk.ternedal.modelrig.net.MediaJobRequest
import dk.ternedal.modelrig.net.MediaJobSource
import dk.ternedal.modelrig.net.MediaJobState
import dk.ternedal.modelrig.net.MediaPage
import dk.ternedal.modelrig.net.MediaVideoStream
import dk.ternedal.modelrig.ui.MediaGenerate
import dk.ternedal.modelrig.ui.theme.ModelRigTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.ByteArrayOutputStream

/**
 * #2419 slice B: the image bubble against a fake rig; no network, no prompt.
 *
 * The pure logic ([ImageJobBubbleLogic]) is checked directly; the composable is
 * driven through its fakes for the three outcomes a user sees: a picture, the
 * rig's error text, and giving up after transient failures.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [36])
class ImageJobBubbleTest {
    @get:Rule
    val compose = createComposeRule()

    private val jobId = "0123456789abcdef0123456789abcdef"

    private fun job(state: MediaJobState, assetId: String? = null, error: String? = null) =
        MediaJob(jobId, state, "sdxl-a", assetId, error, false)

    private fun png(): ByteArray {
        val bitmap = Bitmap.createBitmap(32, 24, Bitmap.Config.ARGB_8888)
        return ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
    }

    /** Answers each poll from [statuses] in turn, repeating the last; a status may throw instead. */
    private class FakeJobs(statuses: List<() -> MediaJob>) : MediaJobSource {
        private val queue = statuses.toMutableList()
        val polled = mutableListOf<String>()
        override fun profiles(): List<MediaJobProfile> = emptyList()
        override fun submit(request: MediaJobRequest, profile: MediaJobProfile): MediaJob = error("not used")
        override fun status(id: String): MediaJob {
            polled += id
            val next = if (queue.size > 1) queue.removeAt(0) else queue.first()
            return next()
        }
        override fun cancel(id: String): MediaJobCancel = error("not used")
    }

    private class FakeGallery(private val bytes: () -> ByteArray) : MediaGallerySource {
        val assets = mutableListOf<String>()
        override fun page(limit: Int, cursor: String?): MediaPage = error("not used")
        override fun thumbnail(item: MediaItem): ByteArray = error("not used")
        override fun image(item: MediaItem): ByteArray = error("not used")
        override fun video(item: MediaItem): MediaVideoStream =
            MediaVideoStream("http://127.0.0.1/x", DataSource.Factory { error("no network in UI tests") })
        override fun asset(assetId: String): ByteArray { assets += assetId; return bytes() }
    }

    private fun show(jobs: MediaJobSource, gallery: MediaGallerySource) {
        compose.setContent {
            ModelRigTheme(dark = true) {
                ImageJobBubble(jobId, jobs, gallery, io = Dispatchers.Unconfined, pollMillis = 5)
            }
        }
        compose.waitForIdle()
    }

    private fun waitForTag(tag: String) =
        compose.waitUntil(5_000) { compose.onAllNodesWithTag(tag).fetchSemanticsNodes().isNotEmpty() }

    private fun waitForText(text: String) =
        compose.waitUntil(5_000) { compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty() }

    // --- composable ---------------------------------------------------------------

    @Test
    fun `queued, running, completed - the picture is fetched once by the job's asset id`() {
        val jobs = FakeJobs(listOf(
            { job(MediaJobState.QUEUED) },
            { job(MediaJobState.RUNNING) },
            { job(MediaJobState.COMPLETED, assetId = "asset-77") },
        ))
        val gallery = FakeGallery(::png)
        show(jobs, gallery)
        waitForTag("image-job-picture")
        compose.onNodeWithTag("image-job-picture").assertIsDisplayed()
        assertEquals(listOf("asset-77"), gallery.assets)
        assertTrue("every poll named this job", jobs.polled.all { it == jobId })
        assertEquals("polling stops at the terminal state", 3, jobs.polled.size)
    }

    @Test
    fun `a failed job shows the rig's error code as text, never a crash`() {
        show(FakeJobs(listOf({ job(MediaJobState.FAILED, error = "gpu_unavailable") })), FakeGallery(::png))
        waitForText(MediaGenerate.errorText("gpu_unavailable"))
        compose.onNodeWithText("Grafikkortet på riggen er ikke ledigt").assertIsDisplayed()
    }

    @Test
    fun `a job the rig no longer knows ends the bubble`() {
        show(FakeJobs(listOf({ throw MediaJobException(Reason.NOT_FOUND, "x", "job_not_found") })), FakeGallery(::png))
        waitForText("Jobbet findes ikke længere på riggen")
    }

    @Test
    fun `transient failures back off and give up after the limit`() {
        val jobs = FakeJobs(listOf({ throw MediaJobException(Reason.TRANSIENT, "x") }))
        show(jobs, FakeGallery(::png))
        waitForText(ImageJobBubbleLogic.GAVE_UP_TEXT)
        assertEquals(ImageJobBubbleLogic.MAX_FAILURES, jobs.polled.size)
    }

    // --- review 6004386757: cancellation, and a picture that exists but could not be fetched once ---

    private fun gone() = MediaGalleryException(MediaGalleryException.Reason.NETWORK, "Riggen svarer ikke")

    /** Runs [ImageJobBubbleLogic.follow] to its end on the test thread and returns every phase it reported. */
    private fun followed(jobs: MediaJobSource, gallery: MediaGallerySource): List<ImageJobPhase> {
        val phases = mutableListOf<ImageJobPhase>()
        kotlinx.coroutines.runBlocking {
            ImageJobBubbleLogic.follow(jobId, jobs, gallery, Dispatchers.Unconfined, pollMillis = 1) { phases += it }
        }
        return phases
    }

    @Test
    fun `a finished picture the rig could not hand over once is fetched again`() {
        val jobs = FakeJobs(listOf({ job(MediaJobState.COMPLETED, assetId = "asset-9") }))
        var calls = 0
        val gallery = FakeGallery { calls += 1; if (calls < 3) throw gone() else png() }
        val phases = followed(jobs, gallery)
        assertTrue("it ends with the picture", phases.last() is ImageJobPhase.Shown)
        assertEquals("the same asset, three times", listOf("asset-9", "asset-9", "asset-9"), gallery.assets)
        assertEquals("the job is not asked again: it is finished", 1, jobs.polled.size)
        assertEquals(
            "the failures in a row are counted on the way",
            listOf(1, 2),
            phases.filterIsInstance<ImageJobPhase.Following>().map { it.failures }.filter { it > 0 },
        )
    }

    @Test
    fun `a rig that stays away ends the fetch after the limit, with the rig's words`() {
        val gallery = FakeGallery { throw gone() }
        val phases = followed(FakeJobs(listOf({ job(MediaJobState.COMPLETED, assetId = "asset-9") })), gallery)
        assertEquals(ImageJobPhase.Ended("Riggen svarer ikke"), phases.last())
        assertEquals(ImageJobBubbleLogic.MAX_FAILURES, gallery.assets.size)
    }

    @Test
    fun `a picture that can never be shown is not asked for twice`() {
        val gallery = FakeGallery { throw MediaGalleryException(MediaGalleryException.Reason.TOO_LARGE, "For stort") }
        val phases = followed(FakeJobs(listOf({ job(MediaJobState.COMPLETED, assetId = "asset-9") })), gallery)
        assertEquals(ImageJobPhase.Ended("For stort"), phases.last())
        assertEquals(1, gallery.assets.size)
        val undecodable = FakeGallery { byteArrayOf(1, 2, 3) }
        val bad = kotlinx.coroutines.runBlocking {
            val seen = mutableListOf<ImageJobPhase>()
            ImageJobBubbleLogic.follow(
                jobId, FakeJobs(listOf({ job(MediaJobState.COMPLETED, assetId = "asset-9") })), undecodable,
                Dispatchers.Unconfined, pollMillis = 1, decode = { throw IllegalStateException("not a picture") },
            ) { seen += it }
            seen
        }
        assertEquals(ImageJobPhase.Ended("Billedet kunne ikke hentes fra riggen"), bad.last())
        assertEquals("bytes that do not decode would not decode next time either", 1, undecodable.assets.size)
    }

    @Test
    fun `catching never turns a cancellation into a result`() {
        assertEquals(7, ImageJobBubbleLogic.catching { 7 }.getOrNull())
        assertTrue(ImageJobBubbleLogic.catching<Int> { throw IllegalStateException("x") }.isFailure)
        var thrown: Throwable? = null
        try {
            ImageJobBubbleLogic.catching<Int> { throw kotlinx.coroutines.CancellationException("left") }
        } catch (e: kotlinx.coroutines.CancellationException) {
            thrown = e
        }
        assertEquals("left", thrown?.message)
    }

    @Test
    fun `a cancellation raised inside a rig call ends the loop instead of counting as a failure`() {
        // What runCatching used to swallow: the call itself throws CancellationException.
        val jobs = FakeJobs(listOf({ throw kotlinx.coroutines.CancellationException("left the composition") }))
        val phases = mutableListOf<ImageJobPhase>()
        var escaped: Throwable? = null
        try {
            kotlinx.coroutines.runBlocking {
                ImageJobBubbleLogic.follow(jobId, jobs, FakeGallery(::png), Dispatchers.Unconfined, pollMillis = 1) { phases += it }
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            escaped = e
        }
        assertEquals("left the composition", escaped?.message)
        assertEquals("asked once, never again", 1, jobs.polled.size)
        assertTrue("and no phase was reported for it", phases.isEmpty())
    }

    @Test
    fun `cancelling the coroutine stops the asking - while waiting and while fetching`() {
        // While waiting between polls of a job that never finishes.
        val running = FakeJobs(listOf({ job(MediaJobState.RUNNING) }))
        val seen = mutableListOf<ImageJobPhase>()
        kotlinx.coroutines.runBlocking {
            val following = launch {
                ImageJobBubbleLogic.follow(jobId, running, FakeGallery(::png), Dispatchers.Unconfined, pollMillis = 20) { seen += it }
            }
            while (running.polled.isEmpty()) kotlinx.coroutines.yield()
            following.cancel()
            following.join()
            assertTrue(following.isCancelled)
        }
        val pollsAtCancel = running.polled.size
        val phasesAtCancel = seen.size
        Thread.sleep(80)
        assertEquals("no poll after the cancel", pollsAtCancel, running.polled.size)
        assertEquals("no phase after the cancel", phasesAtCancel, seen.size)
        assertTrue("it never ended on its own", seen.none { it is ImageJobPhase.Ended })

        // While the picture is being retried: the cancel must not become "the rig failed".
        val gallery = FakeGallery { throw gone() }
        val fetching = mutableListOf<ImageJobPhase>()
        kotlinx.coroutines.runBlocking {
            val following = launch {
                ImageJobBubbleLogic.follow(
                    jobId, FakeJobs(listOf({ job(MediaJobState.COMPLETED, assetId = "asset-9") })), gallery,
                    Dispatchers.Unconfined, pollMillis = 50,
                ) { fetching += it }
            }
            while (gallery.assets.isEmpty()) kotlinx.coroutines.yield()
            following.cancel()
            following.join()
        }
        assertTrue("cancelled between two fetches: no Ended phase", fetching.none { it is ImageJobPhase.Ended })
        assertTrue("and fewer fetches than the limit", gallery.assets.size < ImageJobBubbleLogic.MAX_FAILURES)
    }

    @Test
    fun `a completed job whose picture cannot be fetched says so`() {
        val jobs = FakeJobs(listOf({ job(MediaJobState.COMPLETED, assetId = "asset-1") }))
        show(jobs, FakeGallery { throw MediaGalleryException(MediaGalleryException.Reason.TOO_LARGE, "For stort til at blive vist på telefonen") })
        waitForText("For stort til at blive vist på telefonen")
    }

    @Test
    fun `tapping the picture opens the full-size viewer, close returns to the bubble`() {
        show(FakeJobs(listOf({ job(MediaJobState.COMPLETED, assetId = "asset-9") })), FakeGallery(::png))
        waitForTag("image-job-picture")
        compose.onNodeWithTag("image-job-picture").performClick()
        waitForTag("image-viewer")
        compose.onNodeWithTag("image-viewer-picture").assertIsDisplayed()
        compose.onNodeWithTag("image-viewer-close").performClick()
        compose.waitUntil(5_000) { compose.onAllNodesWithTag("image-viewer").fetchSemanticsNodes().isEmpty() }
        compose.onNodeWithTag("image-job-picture").assertIsDisplayed()
    }

    @Test
    fun `a status bubble is not tappable`() {
        show(FakeJobs(listOf({ job(MediaJobState.RUNNING) })), FakeGallery(::png))
        waitForTag("image-job-status")
        compose.onNodeWithTag("image-job-status").assertIsDisplayed()
        assertTrue(compose.onAllNodesWithTag("image-job-picture").fetchSemanticsNodes().isEmpty())
    }

    // --- pure logic ----------------------------------------------------------------

    @Test
    fun `zoom is clamped and pan only counts when zoomed in`() {
        assertEquals(1f, ZoomableImage.nextScale(1f, 0.5f))
        assertEquals(2f, ZoomableImage.nextScale(1f, 2f))
        assertEquals(ZoomableImage.MAX_SCALE, ZoomableImage.nextScale(5f, 3f))
        assertEquals(Offset.Zero, ZoomableImage.nextOffset(Offset(40f, 40f), Offset(10f, 0f), 1f))
        assertEquals(Offset(50f, 40f), ZoomableImage.nextOffset(Offset(40f, 40f), Offset(10f, 0f), 2f))
    }


    @Test
    fun `backoff doubles per failure and is capped`() {
        val base = 2_000L
        assertEquals(base, ImageJobBubbleLogic.delayMillis(ImageJobPhase.Following(null, 0), base))
        assertEquals(4_000L, ImageJobBubbleLogic.delayMillis(ImageJobPhase.Following(null, 1), base))
        assertEquals(16_000L, ImageJobBubbleLogic.delayMillis(ImageJobPhase.Following(null, 3), base))
        assertEquals(MediaGenerate.MAX_POLL_BACKOFF_MILLIS, ImageJobBubbleLogic.delayMillis(ImageJobPhase.Following(null, 9), base))
    }

    @Test
    fun `a completed job without an asset id ends, it is not fetched`() {
        val phase = ImageJobBubbleLogic.polled(job(MediaJobState.COMPLETED, assetId = null))
        assertTrue(phase is ImageJobPhase.Ended)
        assertEquals(null, ImageJobBubbleLogic.toFetch(phase))
    }

    @Test
    fun `a definite failure ends at once, a transient one counts`() {
        val start = ImageJobBubbleLogic.initial()
        assertTrue(ImageJobBubbleLogic.pollFailed(start, MediaJobException(Reason.UNAUTHORIZED, "x")) is ImageJobPhase.Ended)
        val once = ImageJobBubbleLogic.pollFailed(start, MediaJobException(Reason.NETWORK, "x"))
        assertEquals(1, (once as ImageJobPhase.Following).failures)
        assertTrue(ImageJobBubbleLogic.polling(once))
    }

    @Test
    fun `cancelled and expired end with the generate screen's words`() {
        assertEquals("Annulleret", ImageJobBubbleLogic.label(ImageJobBubbleLogic.polled(job(MediaJobState.CANCELLED))))
        assertTrue(ImageJobBubbleLogic.label(ImageJobBubbleLogic.polled(job(MediaJobState.EXPIRED))).startsWith("Udløbet"))
    }
}
