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

/**
 * Skaerm 3 (Kilde & model) — sheet-indholdet 1:1 mod kontaktarkets celle,
 * begge temaer. Renderes fladt paa sheet-fladen (ModalBottomSheet-vinduet
 * selv kan ikke screenshotes i Robolectric).
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [36], qualifiers = RobolectricDeviceQualifiers.Pixel6)
class SourceModelSheetScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Sheet3() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.sheet)) {
            Spacer(Modifier.height(20.dp))
            SourceModelSheetContent(
                rigSelected = true,
                rigStatus = "Forbundet \u00b7 192.168.1.10:8080",
                rigConnected = true,
                cloudAvailable = true,
                cloudStatus = "gpt-oss:120b \u00b7 forlader enheden",
                models = listOf(
                    ModelRowUi("qwen3:14b", selected = true, loaded = true, paramsLabel = "14B parametre"),
                    ModelRowUi("llama3.1:8b", selected = false, loaded = false, paramsLabel = "8B parametre"),
                    ModelRowUi("mistral:7b", selected = false, loaded = false, paramsLabel = "7B parametre"),
                ),
                onSelectRig = {}, onSelectCloud = {}, onSelectModel = {}, onReload = {}, onDismiss = {},
            )
        }
    }

    @Test
    fun sheet3Dark() {
        compose.setContent { ModelRigTheme(dark = true) { Sheet3() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun sheet3Light() {
        compose.setContent { ModelRigTheme(dark = false) { Sheet3() } }
        compose.onRoot().captureRoboImage()
    }
}
