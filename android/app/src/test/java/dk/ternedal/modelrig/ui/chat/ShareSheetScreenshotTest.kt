package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
class ShareSheetScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun shareLandingTextDark() {
        compose.setContent {
            ModelRigTheme(dark = true) {
                Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(15.dp)) {
                    ShareLandingCard(
                        title = "Artikel om lokale modeller",
                        preview = "Kvantisering gør det muligt at køre større modeller på mindre kort …",
                        isDocument = false,
                        truncated = false,
                        rigAvailable = true,
                        busy = false,
                        onAsk = {},
                        onSaveToKnowledge = {},
                        onDismiss = {},
                    )
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun shareLandingNoRigDark() {
        compose.setContent {
            ModelRigTheme(dark = true) {
                Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(15.dp)) {
                    ShareLandingCard(
                        title = "rapport.pdf",
                        preview = "application/pdf",
                        isDocument = true,
                        truncated = true,
                        rigAvailable = false,
                        busy = false,
                        onAsk = {},
                        onSaveToKnowledge = {},
                        onDismiss = {},
                    )
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }
}
