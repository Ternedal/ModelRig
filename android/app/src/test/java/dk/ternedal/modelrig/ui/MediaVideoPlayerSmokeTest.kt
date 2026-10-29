package dk.ternedal.modelrig.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.assertIsDisplayed
import androidx.media3.datasource.DataSource
import dk.ternedal.modelrig.net.MediaGalleryContract
import dk.ternedal.modelrig.net.MediaGalleryContractTest.Companion.video
import dk.ternedal.modelrig.net.MediaVideoStream
import dk.ternedal.modelrig.ui.theme.ModelRigTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * The real Media3 player and PlayerView build, compose and release without a
 * device, and open no data source before the user presses play.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class MediaVideoPlayerSmokeTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun realPlayerComposesAndIsReleasedWhenRemoved() {
        val clip = MediaGalleryContract.parseItem(video("clip"))!!
        var opened = 0
        val stream = MediaVideoStream("http://127.0.0.1:9/api/v1/media/clip", DataSource.Factory {
            opened++
            error("the player must not fetch before the user presses play")
        })
        var shown by mutableStateOf(true)
        compose.setContent {
            ModelRigTheme(dark = true) {
                if (shown) MediaVideoPlayer(stream, clip, onError = {})
            }
        }
        compose.waitForIdle()
        compose.onRoot().assertIsDisplayed()
        // Give the playback thread a moment; an eager prepare() would open the source.
        Thread.sleep(300)
        compose.waitForIdle()
        assertEquals("no request before play", 0, opened)
        shown = false
        compose.waitForIdle()
    }
}
