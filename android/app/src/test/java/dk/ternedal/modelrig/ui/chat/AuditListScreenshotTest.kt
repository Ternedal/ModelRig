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
class AuditListScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Screen11() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background)) {
            Spacer(Modifier.height(10.dp))
            ConversationsTopBar(
                title = "Handlingslog",
                onBack = {},
                onMenu = {},
                menuIcon = dk.ternedal.modelrig.R.drawable.ic_kaliv_filter,
            )
            KnowledgeIntroNote(
                Modifier.padding(bottom = 13.dp),
                text = "Alt hvad v\u00e6rkt\u00f8jer og agent udf\u00f8rer, logges her. Kun p\u00e5 din rig.",
            )
            AuditGroupedList(
                today = listOf(
                    AuditRowUi("L\u00e6ste brygning/m\u00e6skning.md", "V\u00e6rkt\u00f8j: list_documents \u00b7 10:41 \u00b7 lav", "Udf\u00f8rt", AuditBadgeKind.Ok, cloud = false, tool = "list_documents"),
                    AuditRowUi("K\u00f8rte docker compose up -d", "V\u00e6rkt\u00f8j: note_append \u00b7 09:12 \u00b7 h\u00f8j", "Udf\u00f8rt", AuditBadgeKind.Ok, cloud = false, tool = "note_append"),
                    AuditRowUi("Slette build-cache", "V\u00e6rkt\u00f8j: delete_model \u00b7 09:10 \u00b7 h\u00f8j", "Afvist", AuditBadgeKind.Warn, cloud = false, tool = "delete_model"),
                ),
                earlier = listOf(
                    AuditRowUi("Hentede vejrdata", "V\u00e6rkt\u00f8j: web_research \u00b7 i g\u00e5r \u00b7 lav", "Fejl", AuditBadgeKind.Error, cloud = true, tool = "web_research"),
                ),
                modifier = Modifier.padding(horizontal = 20.dp),
            )
            Spacer(Modifier.height(16.dp))
        }
    }

    @Test
    fun screen11Dark() {
        compose.setContent { ModelRigTheme(dark = true) { Screen11() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen11Light() {
        compose.setContent { ModelRigTheme(dark = false) { Screen11() } }
        compose.onRoot().captureRoboImage()
    }
}
