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
class RigStatusScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    /** Målt tilstand: alle tre målere har tal (referencens celle). */
    @Composable
    private fun RigStatusMeasured() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background)) {
            Spacer(Modifier.height(10.dp))
            ConversationsTopBar(title = "Rig-status", onBack = {}, onMenu = {}, menuIcon = dk.ternedal.modelrig.R.drawable.ic_kaliv_retry)
            Column(Modifier.padding(horizontal = 15.dp)) {
                RigEndpointCard(
                    host = "192.168.1.10:8080",
                    stateText = "Forbundet \u00b7 rig-oppetid " + formatUptime(6 * 3600L + 12 * 60L),
                    online = true,
                )
                Spacer(Modifier.height(19.dp))
                RigSectionCaps("BELASTNING")
                Spacer(Modifier.height(12.dp))
                RigMeterRow("VRAM", "14.2 / 24 GB", 0.592f)
                Spacer(Modifier.height(16.dp))
                RigMeterRow("GPU-temperatur", "61°", 61 / 110f)
                Spacer(Modifier.height(16.dp))
                RigMeterRow("CPU", "23 %", 0.23f)
                Spacer(Modifier.height(19.dp))
                RigFreeVramAction(
                    busy = false,
                    confirming = false,
                    resultLine = null,
                    onAsk = {}, onConfirm = {}, onCancel = {},
                )
                Spacer(Modifier.height(19.dp))
                RigSectionCaps("INDLÆST")
                Spacer(Modifier.height(4.dp))
                RigLoadedModelRow("qwen3:14b", "9.0 GB")
                Spacer(Modifier.height(14.dp))
            }
        }
    }

    /** Umålt tilstand: ældre rig uden endpointet — "ukendt" og ærlig note. */
    @Composable
    private fun RigStatusUnknown() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background)) {
            Spacer(Modifier.height(10.dp))
            Column(Modifier.padding(horizontal = 15.dp)) {
                RigMeterRow("VRAM", "ukendt", null)
                Spacer(Modifier.height(16.dp))
                RigMeterRow("GPU-temperatur", "ukendt", null)
                Spacer(Modifier.height(14.dp))
                RigMeasurementNote(
                    text = "Din rig kender ikke måle-endpointet endnu. Det kom med rig-version 2.0.3 — opdatér riggen, så udfyldes tallene.",
                    onRetry = {},
                )
            }
            Spacer(Modifier.height(14.dp))
        }
    }

    @Test
    fun rigStatusDark() {
        compose.setContent { ModelRigTheme(dark = true) { RigStatusMeasured() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun rigStatusLight() {
        compose.setContent { ModelRigTheme(dark = false) { RigStatusMeasured() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun rigStatusFreeVramConfirmDark() {
        compose.setContent {
            ModelRigTheme(dark = true) {
                Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(15.dp)) {
                    RigFreeVramAction(
                        busy = false,
                        confirming = true,
                        resultLine = null,
                        onAsk = {}, onConfirm = {}, onCancel = {},
                    )
                    Spacer(Modifier.height(12.dp))
                    RigFreeVramAction(
                        busy = false,
                        confirming = false,
                        resultLine = unloadResultLine(1, 9_663_676_416L, 0),
                        onAsk = {}, onConfirm = {}, onCancel = {},
                    )
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun rigStatusUnknownDark() {
        compose.setContent { ModelRigTheme(dark = true) { RigStatusUnknown() } }
        compose.onRoot().captureRoboImage()
    }
}
