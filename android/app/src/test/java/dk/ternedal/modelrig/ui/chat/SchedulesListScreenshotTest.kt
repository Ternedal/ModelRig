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
class SchedulesListScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun SchedulerScreenMock() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background)) {
            Spacer(Modifier.height(10.dp))
            ConversationsTopBar(title = "Scheduler", onBack = {})
            KnowledgeIntroNote(
                Modifier.padding(bottom = 13.dp),
                text = "K\u00f8rer kun p\u00e5 din rig. Oprettelse og fornyelse kr\u00e6ver din godkendelse \u2014 hver gang.",
            )
            Column(Modifier.padding(horizontal = 15.dp), verticalArrangement = Arrangement.spacedBy(11.dp)) {
                ExpiringScheduleCard(
                    ui = ScheduleCardUi(
                        id = "s1", title = "backup.run",
                        sub = "hver nat 03:00 \u00b7 12 af 90 k\u00f8rsler brugt",
                        nextLabel = null, pausedLine = null,
                        runsLabel = "12 af 90", expiresLabel = "16/8",
                        expiresBadge = "UDL\u00d8BER OM 2 DAGE",
                        approvedLine = "Godkendt fra denne enhed",
                        blockedLine = null, enabled = true,
                    ),
                    busy = false, onRenew = {}, onDismiss = {},
                )
                NormalScheduleCard(
                    ui = ScheduleCardUi(
                        id = "s2", title = "Ugentlig genindeksering", sub = "rag.reindex \u00b7 s\u00f8ndage 04:00",
                        nextLabel = "N\u00e6ste: s\u00f8n 04:00", pausedLine = null,
                        runsLabel = "3 af 12", expiresLabel = "30/8",
                        expiresBadge = null, approvedLine = null, blockedLine = null, enabled = true,
                    ),
                    busy = false, expanded = false, onToggle = {}, onClick = {}, onLongPress = {},
                )
                NormalScheduleCard(
                    ui = ScheduleCardUi(
                        id = "s3", title = "fs.cleanup", sub = "mandage 05:00",
                        nextLabel = null, pausedLine = "P\u00e5 pause \u00b7 fornyelse bevarer pausen",
                        runsLabel = "7 af 20", expiresLabel = "22/9",
                        expiresBadge = null, approvedLine = null, blockedLine = null, enabled = false,
                    ),
                    busy = false, expanded = false, onToggle = {}, onClick = {}, onLongPress = {},
                )
                KalivOutlineActionCard("Ny planlagt k\u00f8rsel (preview)", {})
                SchedulesFooterStatus(
                    statusText = "Runtime k\u00f8rer \u00b7 0 aktive",
                    ok = true, errorText = null, onReload = {},
                )
            }
            Spacer(Modifier.height(14.dp))
        }
    }

    @Test
    fun schedulerDark() {
        compose.setContent { ModelRigTheme(dark = true) { SchedulerScreenMock() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun schedulerLight() {
        compose.setContent { ModelRigTheme(dark = false) { SchedulerScreenMock() } }
        compose.onRoot().captureRoboImage()
    }
}
