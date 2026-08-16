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
import dk.ternedal.modelrig.net.UsedChunk
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
class CitationsScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun citationsDark() {
        compose.setContent {
            ModelRigTheme(dark = true) {
                Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(15.dp)) {
                    CitationsList(
                        chunks = listOf(
                            UsedChunk("kvartalsnoter.md", 2, 0.71, "Omsætningen steg i andet kvartal, drevet af de nye abonnementer …"),
                            UsedChunk("regnskab.pdf", 0, 0.58, "Note 4: Periodiseringer er opgjort efter samme princip som sidste år."),
                        ),
                    )
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }
}
