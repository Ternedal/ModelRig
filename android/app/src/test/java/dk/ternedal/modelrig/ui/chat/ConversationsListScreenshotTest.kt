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
class ConversationsListScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Screen7() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background)) {
            Spacer(Modifier.height(10.dp))
            ConversationsTopBar(onBack = {}, onNew = {})
            ConversationsSearchField(query = "", onQuery = {}, modifier = Modifier.padding(horizontal = 15.dp))
            Spacer(Modifier.height(10.dp))
            ConversationsList(
                today = listOf(
                    ConvRowUi(1, "Underventil i \u00f8l", "Hold g\u00e6ringstemperaturen stabil og giv g\u00e6ren tid \u2026", "10:43", cloud = false, active = true),
                    ConvRowUi(2, "Fejl i Docker build", "Pr\u00f8v at rydde cachen med docker builder \u2026", "09:12", cloud = true, active = false),
                ),
                earlier = listOf(
                    ConvRowUi(3, "Rejseplan til Lissabon", "Tag metroen fra lufthavnen til Baixa \u2026", "i g\u00e5r", cloud = true, active = false),
                    ConvRowUi(4, "Regex til datoer", "M\u00f8nsteret matcher \u00c5\u00c5\u00c5\u00c5-MM-DD \u2026", "man", cloud = false, active = false),
                ),
                onOpen = {}, onLongPress = {},
                modifier = Modifier.padding(horizontal = 15.dp),
            )
            Spacer(Modifier.height(16.dp))
        }
    }

    @Test
    fun screen7Dark() {
        compose.setContent { ModelRigTheme(dark = true) { Screen7() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen7Light() {
        compose.setContent { ModelRigTheme(dark = false) { Screen7() } }
        compose.onRoot().captureRoboImage()
    }
}
