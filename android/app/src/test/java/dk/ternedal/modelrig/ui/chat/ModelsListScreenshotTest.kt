package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
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
class ModelsListScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Screen10() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background)) {
            Spacer(Modifier.height(10.dp))
            ConversationsTopBar(title = "Modeller", onBack = {}, onNew = {})
            ModelsVramLine(text = "Din rig \u00b7 8,4 GB VRAM i brug", onReload = {}, modifier = Modifier.padding(bottom = 13.dp))
            Column(Modifier.padding(horizontal = 17.dp), verticalArrangement = Arrangement.spacedBy(11.dp)) {
                InstalledModelCard(InstalledModelUi("qwen3:14b", standard = true, loaded = true, metaLabel = "9,0 GB \u00b7 14B parametre \u00b7 8,4 GB VRAM"), onLongPress = {})
                InstalledModelCard(InstalledModelUi("llama3.1:8b", standard = false, loaded = false, metaLabel = "4,9 GB \u00b7 8B parametre"), onLongPress = {})
                InstalledModelCard(InstalledModelUi("mistral:7b", standard = false, loaded = false, metaLabel = "4,1 GB \u00b7 7B parametre"), onLongPress = {})
                PullProgressCard(name = "gemma2:9b", progressText = "Henter \u00b7 3,4 af 5,4 GB", fraction = 0.62f)
                KalivOutlineActionCard("Hent ny model", {})
            }
            Spacer(Modifier.height(14.dp))
        }
    }

    @Test
    fun screen10Dark() {
        compose.setContent { ModelRigTheme(dark = true) { Screen10() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen10Light() {
        compose.setContent { ModelRigTheme(dark = false) { Screen10() } }
        compose.onRoot().captureRoboImage()
    }
}
