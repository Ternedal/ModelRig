package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
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
 * Skaerm 1 (Tom-tilstand) samlet 1:1 — baseline sammenlignes visuelt mod
 * mockup-kontaktarkets skaerm 1 i begge temaer (DDR-001-afvigelser undtaget).
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [36], qualifiers = RobolectricDeviceQualifiers.Pixel6)
class ChatScreen1ScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Screen1() {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(KalivTheme.colors.background),
        ) {
            Spacer(Modifier.height(12.dp)) // statusbar-zone (systemets i drift)
            ChatTopBar(dark = KalivTheme.colors.isDark, onToggleDark = {}, onOverflow = {})
            ChatChipRow(modelLabel = "qwen3:14b", onModel = {}, onRag = {}, onTools = {})
            Column(
                modifier = Modifier.fillMaxSize().weight(1f),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                ChatEmptyState(
                    suggestions = listOf(
                        "Opsumm\u00e9r et dokument",
                        "Forklar en fejl i min kode",
                        "Udkast til en e-mail",
                    ),
                    onSuggestion = {},
                )
            }
            ChatComposer(
                text = "",
                placeholder = "Skriv til Kaliv \u2026",
                onAttach = {},
                onMic = {},
                onSend = {},
                sendEnabled = false,
            )
            Spacer(Modifier.height(10.dp))
        }
    }

    @Test
    fun screen1Dark() {
        compose.setContent { ModelRigTheme(dark = true) { Screen1() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen1Light() {
        compose.setContent { ModelRigTheme(dark = false) { Screen1() } }
        compose.onRoot().captureRoboImage()
    }
}
