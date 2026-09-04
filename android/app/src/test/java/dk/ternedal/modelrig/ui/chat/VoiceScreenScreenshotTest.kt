package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.RobolectricDeviceQualifiers
import com.github.takahirom.roborazzi.captureRoboImage
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.ModelRigTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [36], qualifiers = RobolectricDeviceQualifiers.Pixel6)
class VoiceScreenScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Screen6() {
        VoiceOverlayContent(
            pillText = "Lokalt",
            pillDot = KalivTheme.colors.success,
            stateText = "Lytter \u2026",
            transcript = "hvad er vejret i morgen?",
            buttonLabel = "Tryk for at sende",
            onMainTap = {}, onClose = {},
            modifier = Modifier.fillMaxSize().height(820.dp),
        )
    }

    @Test
    fun screen6Dark() {
        compose.setContent { ModelRigTheme(dark = true) { Screen6() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen6Light() {
        compose.setContent { ModelRigTheme(dark = false) { Screen6() } }
        compose.onRoot().captureRoboImage()
    }
}
