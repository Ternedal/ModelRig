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
class PairingLinkNoticeScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun pairingLinkNoticeDark() {
        compose.setContent {
            ModelRigTheme(dark = true) {
                Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(15.dp)) {
                    PairingLinkNotice(host = "192.168.1.27:8080", onDismiss = {})
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun pairingLinkNoticeLight() {
        compose.setContent {
            ModelRigTheme(dark = false) {
                Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(15.dp)) {
                    PairingLinkNotice(host = "192.168.1.27:8080", onDismiss = {})
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }
}
