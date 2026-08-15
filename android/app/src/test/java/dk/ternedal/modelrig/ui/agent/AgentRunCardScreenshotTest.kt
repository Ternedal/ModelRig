package dk.ternedal.modelrig.ui.agent

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.github.takahirom.roborazzi.RobolectricDeviceQualifiers
import com.github.takahirom.roborazzi.captureRoboImage
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivType
import dk.ternedal.modelrig.ui.theme.KalivTokens
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
class AgentRunCardScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Screen12() {
        Column(
            Modifier.fillMaxWidth().background(KalivTheme.colors.background)
                .padding(horizontal = 17.dp, vertical = 14.dp),
        ) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    "KALIV",
                    style = TextStyle(
                        fontFamily = KalivType.Inter, fontWeight = FontWeight.Bold,
                        fontSize = 12.sp, letterSpacing = 0.2.em,
                    ),
                    color = KalivTokens.Gold.fill,
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    "agent \u00b7 trin 3 af 4",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                    color = KalivTheme.colors.faint,
                )
            }
            Spacer(Modifier.height(7.dp))
            AgentRunCard(
                steps = listOf(
                    AgentStepUi("L\u00e6ste 3 dokumenter i Viden", AgentStepState.Done),
                    AgentStepUi("Fandt 2 ledige weekender i kalenderen", AgentStepState.Done),
                    AgentStepUi("Skriver udkast til brygplan \u2026", AgentStepState.Active),
                    AgentStepUi("Gennemgang med dig", AgentStepState.Pending),
                ),
                onStop = {},
            )
        }
    }

    @Test
    fun agentRunStopConfirmDark() {
        compose.setContent {
            ModelRigTheme(dark = true) {
                Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(15.dp)) {
                    AgentRunStopConfirm(busy = false, onConfirm = {}, onCancel = {})
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen12Dark() {
        compose.setContent { ModelRigTheme(dark = true) { Screen12() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen12Light() {
        compose.setContent { ModelRigTheme(dark = false) { Screen12() } }
        compose.onRoot().captureRoboImage()
    }
}
