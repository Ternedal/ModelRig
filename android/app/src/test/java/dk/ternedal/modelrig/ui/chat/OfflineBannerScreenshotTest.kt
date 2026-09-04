package dk.ternedal.modelrig.ui.chat

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
class OfflineBannerScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Banner() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background)) {
            Spacer(Modifier.height(12.dp))
            RigOfflineBanner(
                lastSeenLabel = "10:43",
                showCloudSwitch = true,
                retryBusy = false,
                onRetry = {}, onSwitchCloud = {},
                modifier = Modifier.padding(horizontal = 15.dp),
            )
            Spacer(Modifier.height(12.dp))
        }
    }

    @Test
    fun bannerDark() {
        compose.setContent { ModelRigTheme(dark = true) { Banner() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun bannerLight() {
        compose.setContent { ModelRigTheme(dark = false) { Banner() } }
        compose.onRoot().captureRoboImage()
    }
}
