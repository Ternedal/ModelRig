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
class KnowledgeListScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Screen8() {
        Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background)) {
            Spacer(Modifier.height(10.dp))
            ConversationsTopBar(title = "Viden", onBack = {}, onNew = {})
            KnowledgeIntroNote(Modifier.padding(bottom = 15.dp))
            KnowledgeList(
                docs = listOf(
                    KnowledgeDocUi("Brygning_Guide.pdf", "PDF", knowledgeStatsLine(24, 1_783_000_000.0)),
                    KnowledgeDocUi("Enzymer_i_brygning.md", "MD", knowledgeStatsLine(12, 1_781_000_000.0)),
                    KnowledgeDocUi("Underventil_noter.txt", "TXT", knowledgeStatsLine(3, null)),
                    KnowledgeDocUi("G\u00e6r_datablad.pdf", "PDF"),
                ),
                onAdd = {},
                modifier = Modifier.padding(horizontal = 17.dp),
            )
            KnowledgeCorpusFooter(
                sourceCount = 4,
                chunkCount = 39,
                modifier = Modifier.padding(horizontal = 17.dp, vertical = 6.dp),
            )
            KnowledgeFooterNote(Modifier.padding(horizontal = 17.dp, vertical = 10.dp))
            Spacer(Modifier.height(12.dp))
        }
    }

    @Test
    fun knowledgeDisabledSourceDark() {
        compose.setContent {
            ModelRigTheme(dark = true) {
                Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(15.dp)) {
                    KnowledgeList(
                        docs = listOf(
                            KnowledgeDocUi("noter.md", "MD", "24 udsnit \u00b7 2/7 2026", enabled = true),
                            KnowledgeDocUi("regnskab.pdf", "PDF", "8 udsnit \u00b7 1/7 2026", enabled = false),
                        ),
                        onAdd = {},
                        onToggle = { _, _ -> },
                    )
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen8DeleteConfirmDark() {
        compose.setContent {
            ModelRigTheme(dark = true) {
                Column(Modifier.fillMaxWidth().background(KalivTheme.colors.background).padding(17.dp)) {
                    KnowledgeDeleteConfirm(
                        name = "Brygning_Guide.pdf",
                        chunks = 24,
                        busy = false,
                        onConfirm = {}, onCancel = {},
                    )
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen8Dark() {
        compose.setContent { ModelRigTheme(dark = true) { Screen8() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen8Light() {
        compose.setContent { ModelRigTheme(dark = false) { Screen8() } }
        compose.onRoot().captureRoboImage()
    }
}
