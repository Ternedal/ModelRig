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
class DevicesScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Devices(confirm: Boolean) {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background)) {
            Spacer(Modifier.height(10.dp))
            ConversationsTopBar(title = "Enheder", onBack = {}, onMenu = {}, menuIcon = dk.ternedal.modelrig.R.drawable.ic_kaliv_retry)
            KnowledgeIntroNote(
                Modifier.padding(bottom = 13.dp),
                text = "Enheder der er parret med din rig. Fjernes en enhed, holder dens adgang op med at virke med det samme.",
            )
            Column(Modifier.padding(horizontal = 15.dp)) {
                if (confirm) {
                    DeviceRevokeConfirm(
                        deviceName = "Pixel 6a",
                        isThisDevice = true,
                        busy = false,
                        onConfirm = {}, onCancel = {},
                    )
                    Spacer(Modifier.height(11.dp))
                }
                DeviceRow(
                    ui = DeviceRowUi(
                        id = "d1", name = "Pixel 6a",
                        pairedLabel = "Parret 8/7 2026 21:14",
                        lastSeenLabel = "Sidst set 15/8 2026 11:16",
                        isThisDevice = true,
                    ),
                    busy = false, onRevoke = {},
                )
                Spacer(Modifier.height(11.dp))
                DeviceRow(
                    ui = DeviceRowUi(
                        id = "d2", name = "Desktop (arbejde)",
                        pairedLabel = "Parret 12/6 2026 09:02",
                        lastSeenLabel = "Sidst set 2/8 2026 17:40",
                        isThisDevice = false,
                    ),
                    busy = false, onRevoke = {},
                )
                Spacer(Modifier.height(11.dp))
                DevicesUnknownSelfNote()
            }
            Spacer(Modifier.height(14.dp))
        }
    }

    @Test
    fun devicesDark() {
        compose.setContent { ModelRigTheme(dark = true) { Devices(confirm = false) } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun devicesLight() {
        compose.setContent { ModelRigTheme(dark = false) { Devices(confirm = false) } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun devicesRevokeSelfConfirmDark() {
        compose.setContent { ModelRigTheme(dark = true) { Devices(confirm = true) } }
        compose.onRoot().captureRoboImage()
    }
}
