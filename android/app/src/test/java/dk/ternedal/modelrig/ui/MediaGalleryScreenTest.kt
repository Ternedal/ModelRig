package dk.ternedal.modelrig.ui

import android.graphics.Bitmap
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import dk.ternedal.modelrig.net.MediaGalleryContract
import dk.ternedal.modelrig.net.MediaGalleryContractTest.Companion.image
import dk.ternedal.modelrig.net.MediaGalleryContractTest.Companion.video
import dk.ternedal.modelrig.net.MediaGalleryException
import dk.ternedal.modelrig.net.MediaGalleryException.Reason
import dk.ternedal.modelrig.net.MediaGallerySource
import dk.ternedal.modelrig.net.MediaItem
import dk.ternedal.modelrig.net.MediaPage
import dk.ternedal.modelrig.net.MediaVideoStream
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.media3.datasource.DataSource
import dk.ternedal.modelrig.ui.theme.ModelRigTheme
import kotlinx.coroutines.Dispatchers
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.ByteArrayOutputStream

/** Gallery states against a fake source; no network, no rig. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [36])
class MediaGalleryScreenTest {
    @get:Rule
    val compose = createComposeRule()

    private class FakeSource(
        private val pages: MutableList<Result<MediaPage>>,
        private val thumbnail: () -> ByteArray = { throw MediaGalleryException(Reason.NOT_FOUND, "x") },
        private val full: () -> ByteArray = { throw MediaGalleryException(Reason.NOT_FOUND, "x") },
        private val stream: (MediaItem) -> MediaVideoStream = { MediaVideoStream("http://127.0.0.1/api/v1/media/${it.id}", DataSource.Factory { error("no network in UI tests") }) },
    ) : MediaGallerySource {
        val cursors = mutableListOf<String?>()
        override fun page(limit: Int, cursor: String?): MediaPage {
            cursors += cursor
            return pages.removeAt(0).getOrThrow()
        }
        override fun thumbnail(item: MediaItem) = thumbnail()
        override fun image(item: MediaItem) = full()
        override fun video(item: MediaItem) = stream(item)
    }

    private fun item(id: String) = MediaGalleryContract.parseItem(image(id))!!

    /** Stands in for Media3: shows which stream it got and can report a player error. */
    private val fakePlayer: @androidx.compose.runtime.Composable (MediaVideoStream, MediaItem, (Reason) -> Unit) -> Unit =
        { stream, _, onError ->
            // A Column, not the detail's Box: stacked buttons would overlap and steal clicks.
            androidx.compose.foundation.layout.Column {
                Text("player:" + stream.url)
                Button(onClick = { onError(Reason.UNPLAYABLE) }) { Text("simulate decode failure") }
                Button(onClick = { onError(Reason.NETWORK) }) { Text("simulate network failure") }
            }
        }

    private fun show(source: MediaGallerySource) {
        compose.setContent {
            ModelRigTheme(dark = true) {
                MediaGalleryContent(source, onClose = {}, io = Dispatchers.Main, videoPlayer = fakePlayer)
            }
        }
        compose.waitForIdle()
    }

    private fun png(): ByteArray {
        val bitmap = Bitmap.createBitmap(64, 48, Bitmap.Config.ARGB_8888)
        return ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
    }

    @Test
    fun emptyLibrary() {
        show(FakeSource(mutableListOf(Result.success(MediaPage(emptyList(), null, 0)))))
        compose.onNodeWithText("Ingen billeder eller videoer endnu.").assertIsDisplayed()
    }

    @Test
    fun storageUnavailableOnFirstPageOffersRetry() {
        val source = FakeSource(mutableListOf(
            Result.failure(MediaGalleryException(Reason.STORAGE_UNAVAILABLE, "x")),
            Result.success(MediaPage(listOf(item("a")), null, 0)),
        ))
        show(source)
        compose.onNodeWithText(mediaGalleryMessage(Reason.STORAGE_UNAVAILABLE)).assertIsDisplayed()
        compose.onNodeWithText("Prøv igen").performClick()
        compose.waitForIdle()
        compose.onNodeWithContentDescription("Billede", substring = true).assertIsDisplayed()
    }

    @Test
    fun loadMoreSendsTheCursorAndShowsSkippedCount() {
        val source = FakeSource(mutableListOf(
            Result.success(MediaPage(listOf(item("a")), "c1", skipped = 1)),
            Result.success(MediaPage(listOf(item("b")), null, skipped = 1)),
        ))
        show(source)
        compose.onNodeWithText("1 medie kunne ikke vises.").assertIsDisplayed()
        compose.onNodeWithText("Hent flere").performClick()
        compose.waitForIdle()
        assertEquals(listOf(null, "c1"), source.cursors)
        compose.onNodeWithText("2 medier kunne ikke vises.").assertIsDisplayed()
        assertEquals(0, compose.onAllNodesWithText("Hent flere").fetchSemanticsNodes().size)
    }

    @Test
    fun allInvalidFirstPageStillOffersLoadMore() {
        // Review 5684792570: zero valid items + next_cursor must not look empty.
        val source = FakeSource(mutableListOf(
            Result.success(MediaPage(emptyList(), "c1", skipped = 2)),
            Result.success(MediaPage(listOf(item("later")), null, skipped = 0)),
        ))
        show(source)
        assertEquals(0, compose.onAllNodesWithText("Ingen billeder eller videoer endnu.").fetchSemanticsNodes().size)
        compose.onNodeWithText("2 medier kunne ikke vises.").assertIsDisplayed()
        compose.onNodeWithText("Hent flere").performClick()
        compose.waitForIdle()
        assertEquals(listOf(null, "c1"), source.cursors)
        compose.onNodeWithContentDescription("Billede", substring = true).assertIsDisplayed()
    }

    @Test
    fun staleCursorAsksForRefreshAndStartsOver() {
        val source = FakeSource(mutableListOf(
            Result.success(MediaPage(listOf(item("a")), "old", 0)),
            Result.failure(MediaGalleryException(Reason.BAD_REQUEST, "x")),
            Result.success(MediaPage(listOf(item("fresh")), null, 0)),
        ))
        show(source)
        compose.onNodeWithText("Hent flere").performClick()
        compose.waitForIdle()
        compose.onNodeWithText(mediaGalleryMessage(Reason.BAD_REQUEST)).assertIsDisplayed()
        compose.onAllNodesWithText("Opdater")[1].performClick()
        compose.waitForIdle()
        assertEquals(listOf(null, "old", null), source.cursors)
    }

    @Test
    fun imageDetailShowsMetadata() {
        show(FakeSource(mutableListOf(Result.success(MediaPage(listOf(item("a")), null, 0))), full = ::png))
        compose.onNodeWithContentDescription("Billede", substring = true).performClick()
        compose.waitForIdle()
        compose.onNodeWithText("Til galleriet").assertIsDisplayed()
        compose.onNodeWithText("1920 × 1080").assertIsDisplayed()
        compose.onNodeWithText("1,2 MB").assertIsDisplayed()
    }

    @Test
    fun imageTooLargeIsNotFetched() {
        val big = MediaGalleryContract.parseItem(image("big").put("size_bytes", 30L * 1024 * 1024))!!
        var fetched = false
        show(FakeSource(mutableListOf(Result.success(MediaPage(listOf(big), null, 0))), full = { fetched = true; png() }))
        compose.onNodeWithContentDescription("Billede", substring = true).performClick()
        compose.waitForIdle()
        compose.onNodeWithText(mediaGalleryMessage(Reason.TOO_LARGE)).assertIsDisplayed()
        assertEquals(false, fetched)
    }

    @Test
    fun videoDetailHandsTheStreamToThePlayer() {
        val clip = MediaGalleryContract.parseItem(video("clip"))!!
        show(FakeSource(mutableListOf(Result.success(MediaPage(listOf(clip), null, 0)))))
        compose.onNodeWithText("1:05").assertIsDisplayed()
        compose.onNodeWithContentDescription("Video", substring = true).performClick()
        compose.waitForIdle()
        compose.onNodeWithText("player:http://127.0.0.1/api/v1/media/clip").assertIsDisplayed()
        compose.onNodeWithText("Vises fladt: equirectangular 360, top bottom.").assertIsDisplayed()
    }

    @Test
    fun playerErrorReplacesThePlayerWithItsMessage() {
        val clip = MediaGalleryContract.parseItem(video("clip"))!!
        show(FakeSource(mutableListOf(Result.success(MediaPage(listOf(clip), null, 0)))))
        compose.onNodeWithContentDescription("Video", substring = true).performClick()
        compose.waitForIdle()
        compose.onNodeWithText("simulate decode failure").performClick()
        compose.waitForIdle()
        compose.onNodeWithText(mediaGalleryMessage(Reason.UNPLAYABLE)).assertIsDisplayed()
        assertEquals(0, compose.onAllNodesWithText("player:", substring = true).fetchSemanticsNodes().size)
        assertEquals("a decode failure is final", 0, compose.onAllNodesWithText("Prøv igen").fetchSemanticsNodes().size)
    }

    @Test
    fun networkFailureInThePlayerOffersRetryWhichRebuildsIt() {
        val clip = MediaGalleryContract.parseItem(video("clip"))!!
        show(FakeSource(mutableListOf(Result.success(MediaPage(listOf(clip), null, 0)))))
        compose.onNodeWithContentDescription("Video", substring = true).performClick()
        compose.waitForIdle()
        compose.onNodeWithText("simulate network failure").performClick()
        compose.waitForIdle()
        compose.onNodeWithText(mediaGalleryMessage(Reason.NETWORK)).assertIsDisplayed()
        compose.onNodeWithText("Prøv igen").performClick()
        compose.waitForIdle()
        compose.onNodeWithText("player:http://127.0.0.1/api/v1/media/clip").assertIsDisplayed()
    }

    @Test
    fun imageNetworkFailureCanBeRetried() {
        var calls = 0
        show(FakeSource(
            mutableListOf(Result.success(MediaPage(listOf(item("a")), null, 0))),
            full = { if (calls++ == 0) throw MediaGalleryException(Reason.NETWORK, "x") else png() },
        ))
        compose.onNodeWithContentDescription("Billede", substring = true).performClick()
        compose.waitForIdle()
        compose.onNodeWithText(mediaGalleryMessage(Reason.NETWORK)).assertIsDisplayed()
        compose.onNodeWithText("Prøv igen").performClick()
        compose.waitForIdle()
        assertEquals(2, calls)
        assertEquals(0, compose.onAllNodesWithText(mediaGalleryMessage(Reason.NETWORK)).fetchSemanticsNodes().size)
        compose.onNodeWithText("1920 × 1080").assertIsDisplayed()
    }

    @Test
    fun videoWithoutRangeSupportIsNotPlayed() {
        val clip = MediaGalleryContract.parseItem(video("clip"))!!
        show(FakeSource(
            mutableListOf(Result.success(MediaPage(listOf(clip), null, 0))),
            stream = { throw MediaGalleryException(Reason.UNPLAYABLE, "x") },
        ))
        compose.onNodeWithContentDescription("Video", substring = true).performClick()
        compose.waitForIdle()
        compose.onNodeWithText(mediaGalleryMessage(Reason.UNPLAYABLE)).assertIsDisplayed()
        assertEquals(0, compose.onAllNodesWithText("player:", substring = true).fetchSemanticsNodes().size)
        assertEquals("a stream that cannot be built is final", 0, compose.onAllNodesWithText("Prøv igen").fetchSemanticsNodes().size)
    }

    @Test
    fun decodeSamplesLargeImagesDown() {
        val bitmap = Bitmap.createBitmap(1600, 800, Bitmap.Config.ARGB_8888)
        val bytes = ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
        val decoded = decodeBounded(bytes, maxSidePx = 384)
        assertEquals(400, decoded.width)
        assertEquals(200, decoded.height)
    }

    @Test
    fun undecodableBytesAreAProtocolError() {
        val e = runCatching { decodeBounded(byteArrayOf(1, 2, 3), 384) }.exceptionOrNull()
        assertEquals(Reason.PROTOCOL, (e as MediaGalleryException).reason)
    }
}
