package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
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
class Agent3CheckpointScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Checkpoint() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(horizontal = 15.dp)) {
            Spacer(Modifier.height(12.dp))
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "Agent 3 \u00b7 run",
                    color = KalivTheme.colors.textHigh,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 20.sp,
                    modifier = Modifier.weight(1f),
                )
                Agent3ReviewBadge()
            }
            Spacer(Modifier.height(10.dp))
            Agent3RunHeader(
                task = "Kontrollér rigstatus og modeller, skriv note",
                waitingLine = "Checkpoint efter get_rig_status \u00b7 venter på dig",
                modifier = Modifier.padding(horizontal = 0.dp),
            )
            Spacer(Modifier.height(12.dp))
            Agent3StepRow(Agent3StepKind.Done, "Read \u00b7 get_rig_status", "Udført \u00b7 resultat klar til gennemsyn", false)
            Agent3StepRow(Agent3StepKind.Pending, "Read \u00b7 list_models", "Pending", true)
            Agent3StepRow(Agent3StepKind.Pending, "Read \u00b7 read_file noter/rig.md", "Pending", true)
            Agent3StepRow(Agent3StepKind.WriteLocked, "Write \u00b7 skriv note", "Immutabel write-tail \u00b7 kræver separat bekræftelse", false)
            Spacer(Modifier.height(8.dp))
            Text(
                "Read-window \u00b7 trin 1\u20133 \u00b7 runnet er pauset her",
                color = KalivTheme.colors.caps,
                fontSize = 13.sp,
            )
            Spacer(Modifier.height(13.dp))
            Agent3ResultCard(
                toolCaps = "GET_RIG_STATUS",
                body = "Forbundet \u00b7 qwen3:14b indlæst \u00b7 14.2 af 24 GB VRAM",
            )
            Spacer(Modifier.height(14.dp))
            Agent3CheckpointActions(busy = false, onContinue = {}, onReplan = {}, onStop = {})
            Spacer(Modifier.height(14.dp))
        }
    }

    @Test
    fun agent3CheckpointDark() {
        compose.setContent { ModelRigTheme(dark = true) { Checkpoint() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun agent3CheckpointLight() {
        compose.setContent { ModelRigTheme(dark = false) { Checkpoint() } }
        compose.onRoot().captureRoboImage()
    }
}
