package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
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

/** Skaerm 2 (Aktiv samtale) samlet 1:1 — sammenlignes mod kontaktarkets celle 2. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [36], qualifiers = RobolectricDeviceQualifiers.Pixel6)
class ChatScreen2ScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @org.junit.Before
    fun fixTimeZone() {
        java.util.TimeZone.setDefault(java.util.TimeZone.getTimeZone("UTC"))
    }

    @Composable
    private fun Screen2() {
        Column(Modifier.fillMaxSize().background(KalivTheme.colors.background)) {
            Spacer(Modifier.height(12.dp))
            ChatConversationTopBar(title = "Underventil i \u00f8l", onBack = {}, onOverflow = {})
            ChatChipRow(modelLabel = "qwen3:14b", onModel = {}, onRag = {}, onTools = {}, ragActive = true)
            Column(
                Modifier.weight(1f).fillMaxWidth().padding(horizontal = 17.dp),
                verticalArrangement = Arrangement.Bottom,
            ) {
                UserMessage("Hvad betyder underventil i \u00f8lbrygning?")
                AssistantMessage(
                    ChatMessageUi(
                        isUser = false,
                        text = "Underventil beskriver en \u00f8l, hvor g\u00e6ringen ikke er f\u00f8rt helt til ende \u2014 der er stadig restsukker og en fyldig, s\u00f8dlig krop. Modsat overventil, hvor g\u00e6ren har arbejdet for l\u00e6nge.",
                        atMillis = 1755079320000L, // 10:42 lokal tid i baseline-miljoeet
                        sources = listOf("Brygning_Guide.pdf", "Enzymer.md"),
                    ),
                )
                UserMessage("Og hvordan undg\u00e5r jeg det?")
                AssistantMessage(
                    ChatMessageUi(
                        isUser = false,
                        text = "Hold g\u00e6ringstemperaturen stabil og giv g\u00e6ren tid nok. M\u00e5l slutmassefylden to dage i tr\u00e6k",
                        streaming = true,
                    ),
                )
                Spacer(Modifier.height(8.dp))
            }
            ChatComposer(
                text = "", placeholder = "Skriv til Kaliv \u2026",
                onAttach = {}, onMic = {}, onSend = {}, sendEnabled = false,
            )
            Spacer(Modifier.height(10.dp))
        }
    }

    @Test
    fun screen2Dark() {
        compose.setContent { ModelRigTheme(dark = true) { Screen2() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen2Light() {
        compose.setContent { ModelRigTheme(dark = false) { Screen2() } }
        compose.onRoot().captureRoboImage()
    }
}
