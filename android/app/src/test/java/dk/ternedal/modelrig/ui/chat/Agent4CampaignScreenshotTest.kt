package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
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
class Agent4CampaignScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Campaigns() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background)) {
            Spacer(Modifier.height(10.dp))
            ConversationsTopBar(title = "Agent 4", onBack = {})
            Column(Modifier.padding(horizontal = 15.dp), verticalArrangement = Arrangement.spacedBy(11.dp)) {
                Text(
                    "Skrivebeskyttet oversigt \u00b7 nyeste f\u00f8rst \u00b7 hash-verificeret timeline",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 13.5.sp,
                )
                Agent4CampaignCard(
                    ui = Agent4CampaignCardUi(
                        id = "c1", name = "Opgrad\u00e9r RAG-indeks",
                        statusLabel = "K\u00d8RER", statusKind = Agent4StatusKind.Running,
                        subLine = "Uddelegeret til Agent 3 \u00b7 fors\u00f8g 1 af 3",
                        timelineCount = 48, evidenceCount = 12, attemptLabel = "1 af 3",
                    ),
                    onOpen = {},
                )
                Agent4CampaignCard(
                    ui = Agent4CampaignCardUi(
                        id = "c2", name = "Natlig model-eval",
                        statusLabel = "I K\u00d8", statusKind = Agent4StatusKind.Waiting,
                        subLine = "Arbejdsgang nightly_eval",
                        timelineCount = 4, evidenceCount = 0, attemptLabel = "0 af 3",
                    ),
                    onOpen = {},
                )
                Agent4CampaignCard(
                    ui = Agent4CampaignCardUi(
                        id = "c3", name = "Ryd gamle checkpoints",
                        statusLabel = "FEJLET", statusKind = Agent4StatusKind.Failed,
                        subLine = "Retry-policy udt\u00f8mt \u00b7 kr\u00e6ver din beslutning",
                        timelineCount = 23, evidenceCount = 6, attemptLabel = "3 af 3",
                    ),
                    onOpen = {},
                )
                Agent4FooterFacts(latestHashShort = "9f2a\u20267c41")
            }
            Spacer(Modifier.height(14.dp))
        }
    }

    @Test
    fun agent4CampaignsDark() {
        compose.setContent { ModelRigTheme(dark = true) { Campaigns() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun agent4CampaignsLight() {
        compose.setContent { ModelRigTheme(dark = false) { Campaigns() } }
        compose.onRoot().captureRoboImage()
    }
}
