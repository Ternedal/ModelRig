package dk.ternedal.modelrig.ui.chat

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.RobolectricDeviceQualifiers
import com.github.takahirom.roborazzi.captureRoboImage
import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobState
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.ModelRigTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * #2419: the three faces of the image bubble, dark and light, under an assistant
 * line -- queued/running (status), shown (picture), ended (rig error). Baselines
 * are recorded by the record-goldens workflow on the PR branch and reviewed as
 * any other diff; a drift here is a visual change someone has to mean.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [36], qualifiers = RobolectricDeviceQualifiers.Pixel6)
class ImageJobBubbleScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    private val jobId = "0123456789abcdef0123456789abcdef"

    private fun job(state: MediaJobState, assetId: String? = null, error: String? = null) =
        MediaJob(jobId, state, "realvisxl-4-0", assetId, error, false)

    /** A deterministic stand-in picture: two flat tones and a diagonal, no decoder involved. */
    private fun picture(): Bitmap {
        val bmp = Bitmap.createBitmap(640, 400, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        c.drawColor(Color.rgb(0x3a, 0x4a, 0x5c))
        val p = Paint().apply { color = Color.rgb(0xd9, 0xb3, 0x6c); isAntiAlias = true }
        c.drawCircle(460f, 150f, 70f, p)
        p.color = Color.rgb(0x22, 0x2b, 0x33)
        c.drawRect(0f, 300f, 640f, 400f, p)
        return bmp
    }

    @Composable
    private fun Faces() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(horizontal = 15.dp)) {
            Spacer(Modifier.height(12.dp))
            ImageJobBubbleContent(ImageJobPhase.Following(job(MediaJobState.RUNNING), 0))
            ImageJobBubbleContent(ImageJobPhase.Shown(job(MediaJobState.COMPLETED, assetId = "a"), picture(), ByteArray(0)))
            ImageJobBubbleContent(ImageJobPhase.Ended("Grafikkortet på riggen er ikke ledigt"))
            Spacer(Modifier.height(12.dp))
        }
    }

    @Test
    fun imageBubbleDark() {
        compose.setContent { ModelRigTheme(dark = true) { Faces() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun imageBubbleLight() {
        compose.setContent { ModelRigTheme(dark = false) { Faces() } }
        compose.onRoot().captureRoboImage()
    }
}
