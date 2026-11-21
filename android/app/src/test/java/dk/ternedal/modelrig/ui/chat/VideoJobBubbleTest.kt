package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.media3.datasource.DataSource
import dk.ternedal.modelrig.net.MediaGalleryException
import dk.ternedal.modelrig.net.MediaGallerySource
import dk.ternedal.modelrig.net.MediaItem
import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobCancel
import dk.ternedal.modelrig.net.MediaJobProfile
import dk.ternedal.modelrig.net.MediaJobRequest
import dk.ternedal.modelrig.net.MediaJobSource
import dk.ternedal.modelrig.net.MediaJobState
import dk.ternedal.modelrig.net.MediaKind
import dk.ternedal.modelrig.net.MediaPage
import dk.ternedal.modelrig.net.MediaVideoStream
import dk.ternedal.modelrig.ui.theme.ModelRigTheme
import kotlinx.coroutines.Dispatchers
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.time.Instant

/**
 * The video bubble: polls like the image bubble, then resolves the finished clip
 * through the gallery's newest page and plays it with the gallery's player; a
 * clip not on that page is said to be in the gallery. Pure resolution logic is
 * checked directly.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [36])
class VideoJobBubbleTest {
    @get:Rule
    val compose = createComposeRule()

    private val jobId = "0123456789abcdef0123456789abcdef"

    private fun job(state: MediaJobState, assetId: String? = null, error: String? = null) =
        MediaJob(jobId, state, "wan-t2v", assetId, error, false)

    private fun videoItem(id: String, range: Boolean = true) = MediaItem(
        id = id, kind = MediaKind.VIDEO, mimeType = "video/mp4", createdAt = Instant.EPOCH, sizeBytes = 1_000,
        width = 832, height = 480, durationSeconds = 2.0, projection = "flat", stereo = "mono",
        thumbnailId = null, supportsRange = range,
    )

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

    private class FakeGallery(private val items: List<MediaItem>) : MediaGallerySource {
        val videoRequests = mutableListOf<String>()
        override fun page(limit: Int, cursor: String?): MediaPage = MediaPage(items, null, 0)
        override fun thumbnail(item: MediaItem): ByteArray = error("not used")
        override fun image(item: MediaItem): ByteArray = error("not used")
        override fun video(item: MediaItem): MediaVideoStream {
            videoRequests += item.id
            return MediaVideoStream("http://127.0.0.1/${item.id}", DataSource.Factory { error("no network in UI tests") })
        }
    }

    private fun show(jobs: MediaJobSource, gallery: MediaGallerySource) {
        compose.setContent {
            ModelRigTheme(dark = true) {
                VideoJobBubble(
                    jobId, jobs, gallery, io = Dispatchers.Unconfined, pollMillis = 5,
                    player = { _, _, _ -> Box(Modifier.fillMaxSize().testTag("fake-player")) },
                )
            }
        }
        compose.waitForIdle()
    }

    private fun waitForTag(tag: String) =
        compose.waitUntil(5_000) { compose.onAllNodesWithTag(tag).fetchSemanticsNodes().isNotEmpty() }

    private fun waitForText(text: String) =
        compose.waitUntil(5_000) { compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty() }

    @Test
    fun `a completed clip on the newest page is resolved once and played with the gallery's player`() {
        val jobs = FakeJobs(listOf({ job(MediaJobState.RUNNING) }, { job(MediaJobState.COMPLETED, assetId = "clip-1") }))
        val gallery = FakeGallery(listOf(videoItem("clip-2"), videoItem("clip-1")))
        show(jobs, gallery)
        waitForTag("video-job-player")
        compose.onNodeWithTag("video-job-player").assertIsDisplayed()
        assertEquals(listOf("clip-1"), gallery.videoRequests)
        assertEquals(2, jobs.polled.size)
    }

    @Test
    fun `a clip not on the newest page is said to be in the gallery`() {
        show(FakeJobs(listOf({ job(MediaJobState.COMPLETED, assetId = "old-clip") })), FakeGallery(listOf(videoItem("other"))))
        waitForText(VideoJobBubbleLogic.IN_GALLERY_TEXT)
        assertTrue(compose.onAllNodesWithTag("video-job-player").fetchSemanticsNodes().isEmpty())
    }

    @Test
    fun `while running the status uses video words`() {
        show(FakeJobs(listOf({ job(MediaJobState.PUBLISHING) })), FakeGallery(emptyList()))
        waitForText("Gemmer videoen …")
    }

    @Test
    fun `a failed job shows the rig's code`() {
        show(FakeJobs(listOf({ job(MediaJobState.FAILED, error = "gpu_unavailable") })), FakeGallery(emptyList()))
        waitForText("Grafikkortet på riggen er ikke ledigt")
    }

    @Test
    fun `resolution logic - item required, stream errors are the gallery's words`() {
        val completed = job(MediaJobState.COMPLETED, assetId = "x")
        assertTrue(VideoJobBubbleLogic.resolved(completed, null, null) is VideoJobOutcome.Ended)
        val item = videoItem("x")
        val playable = VideoJobBubbleLogic.resolved(completed, item, Result.success(MediaVideoStream("u", DataSource.Factory { error("x") })))
        assertTrue(playable is VideoJobOutcome.Playable)
        val refused = VideoJobBubbleLogic.resolved(completed, item, Result.failure(MediaGalleryException(MediaGalleryException.Reason.UNPLAYABLE, "Riggen kan ikke streame denne video")))
        assertEquals("Riggen kan ikke streame denne video", (refused as VideoJobOutcome.Ended).text)
        assertNull(VideoJobBubbleLogic.findItem(listOf(videoItem("a")), "b"))
        assertNull(VideoJobBubbleLogic.findItem(listOf(videoItem("a").copy(kind = MediaKind.IMAGE)), "a"))
    }
}
