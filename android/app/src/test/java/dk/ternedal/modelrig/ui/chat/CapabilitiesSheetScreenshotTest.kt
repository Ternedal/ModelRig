package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
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
class CapabilitiesSheetScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Sheet4() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.sheet)) {
            Spacer(Modifier.height(20.dp))
            CapabilitiesSheetContent(
                ragOn = true,
                ragSubtitle = "3 dokumenter \u00b7 svarer med kilder",
                ragSourceLabel = "Kilder: Alle",
                onToggleRag = {}, onSources = {},
                toolsOn = false, onToggleTools = {},
                voiceCloudAvailable = false, voiceViaCloud = false, onToggleVoiceCloud = {},
            )
        }
    }

    @Test
    fun sheet4Dark() {
        compose.setContent { ModelRigTheme(dark = true) { Sheet4() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun sheet4Light() {
        compose.setContent { ModelRigTheme(dark = false) { Sheet4() } }
        compose.onRoot().captureRoboImage()
    }
}
