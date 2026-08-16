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
import dk.ternedal.modelrig.data.OfflineQueue
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
class OfflineQueueScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    private val now = 1_700_000_000_000L

    @Test
    fun queueWaitingDark() {
        compose.setContent {
            ModelRigTheme(dark = true) {
                Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(15.dp)) {
                    OfflineQueueCard(
                        items = listOf(OfflineQueue.Item("Hvad koster en RTX 4070 brugt?", now - 3_600_000L)),
                        nowMillis = now,
                        rigBack = false,
                        onSend = {}, onEdit = {}, onDiscard = {},
                    )
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun queueRigBackDark() {
        compose.setContent {
            ModelRigTheme(dark = true) {
                Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(15.dp)) {
                    OfflineQueueCard(
                        items = listOf(
                            OfflineQueue.Item("Hvad koster en RTX 4070 brugt?", now - 3_600_000L),
                            OfflineQueue.Item("Opsummer mine noter fra i går", now - 86_400_000L),
                        ),
                        nowMillis = now,
                        rigBack = true,
                        onSend = {}, onEdit = {}, onDiscard = {},
                    )
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }
}
