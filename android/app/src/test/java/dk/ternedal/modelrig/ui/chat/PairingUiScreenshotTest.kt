package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.RobolectricDeviceQualifiers
import com.github.takahirom.roborazzi.captureRoboImage
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.components.KalivPrimaryButton
import dk.ternedal.modelrig.ui.theme.KalivTheme
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
class PairingUiScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    @Composable
    private fun Screen5() {
        Column(
            Modifier.fillMaxWidth().background(KalivTheme.colors.background)
                .padding(horizontal = 20.dp, vertical = 14.dp),
        ) {
            PairingHeader(subtitle = "V\u00e6lg mindst \u00e9n kilde for at starte")
            Spacer(Modifier.height(22.dp))
            Surface(
                color = KalivTheme.colors.surface,
                shape = RoundedCornerShape(17.dp),
                border = BorderStroke(2.dp, KalivTheme.colors.hairline),
            ) {
                Column(Modifier.fillMaxWidth().padding(18.dp)) {
                    PairingCardHeader(
                        icon = R.drawable.ic_kaliv_rig,
                        iconTint = KalivTheme.colors.accent,
                        title = "Din rig",
                        subtitle = "Lokale modeller + Viden (RAG)",
                        modifier = Modifier.padding(bottom = 14.dp),
                    )
                    PairingField("Server-URL", "http://192.168.1.10:8080", {})
                    PairingField("Parringskode", "9F2A \u00b7 7K10", {}, letterSpacingEm = 0.16f)
                    PairingBindNote()
                    KalivPrimaryButton(text = "Forbind", onClick = {}, modifier = Modifier.fillMaxWidth())
                }
            }
            Spacer(Modifier.height(13.dp))
            Surface(
                color = KalivTheme.colors.surface,
                shape = RoundedCornerShape(17.dp),
                border = BorderStroke(KalivTokens.Layout.hairline, KalivTheme.colors.hairline),
            ) {
                Row(Modifier.fillMaxWidth().padding(18.dp)) {
                    PairingCardHeader(
                        icon = R.drawable.ic_kaliv_cloud,
                        iconTint = KalivTheme.colors.textMuted,
                        title = "Ollama Cloud",
                        subtitle = "gpt-oss:120b \u00b7 ingen rig p\u00e5kr\u00e6vet",
                        trailing = {
                            Icon(
                                painterResource(R.drawable.ic_kaliv_chevron_right),
                                contentDescription = null,
                                tint = KalivTheme.colors.faint,
                                modifier = Modifier.size(18.dp),
                            )
                        },
                    )
                }
            }
            Spacer(Modifier.height(14.dp))
        }
    }

    @Test
    fun screen5Dark() {
        compose.setContent { ModelRigTheme(dark = true) { Screen5() } }
        compose.onRoot().captureRoboImage()
    }

    @Test
    fun screen5Light() {
        compose.setContent { ModelRigTheme(dark = false) { Screen5() } }
        compose.onRoot().captureRoboImage()
    }
}
