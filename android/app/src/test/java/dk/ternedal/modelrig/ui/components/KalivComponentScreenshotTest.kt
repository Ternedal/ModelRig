package dk.ternedal.modelrig.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import com.github.takahirom.roborazzi.RobolectricDeviceQualifiers
import com.github.takahirom.roborazzi.captureRoboImage
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.ModelRigTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Screenshot-baseline for komponentbiblioteket (DDR-001 fase 1).
 *
 * Roborazzi paa Robolectric (JVM, ingen emulator): NATIVE graphics + SDK 36
 * (kraever JDK 21 — matcher CI). Baselines bor i src/test/screenshots og
 * verificeres i CI via -Proborazzi.test.verify=true; en bevidst visuel
 * aendring regenereres med :app:recordRoborazziDebug og reviewes som diff.
 * Animationer fanges paa foerste frame (hviletilstand).
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [36], qualifiers = RobolectricDeviceQualifiers.Pixel6)
class KalivComponentScreenshotTest {

    @get:Rule
    val compose = createComposeRule()

    private fun snap(dark: Boolean, content: @Composable () -> Unit) {
        compose.setContent {
            ModelRigTheme(dark = dark) {
                Column(
                    modifier = Modifier
                        .background(KalivTheme.colors.background)
                        .padding(KalivTokens.Spacing.s4),
                    verticalArrangement = Arrangement.spacedBy(KalivTokens.Spacing.s3),
                ) {
                    content()
                }
            }
        }
        compose.onRoot().captureRoboImage()
    }

    @Composable
    private fun Buttons() {
        KalivPrimaryButton(text = "Forbind", onClick = {})
        KalivSecondaryButton(text = "Indtast kode manuelt", onClick = {})
        KalivPrimaryButton(text = "Deaktiveret", onClick = {}, enabled = false)
    }

    @Composable
    private fun Chips() {
        ChipRow(background = KalivTheme.colors.background) {
            KontekstChip(text = "qwen3:14b", onClick = {})
            KontekstChip(text = "RAG \u00b7 Til", onClick = {}, selected = true)
            KontekstChip(text = "V\u00e6rkt\u00f8jer", onClick = {})
            KontekstChip(text = "Agent", onClick = {})
            KontekstChip(text = "Stemme", onClick = {})
        }
    }

    @Composable
    private fun Controls() {
        CapsLabel("I dag")
        Row(
            horizontalArrangement = Arrangement.spacedBy(KalivTokens.Spacing.s3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StatusDot(KalivTheme.colors.success)
            KalivBadge("Standard")
            KalivSwitch(checked = true, onCheckedChange = {})
            KalivSwitch(checked = false, onCheckedChange = {})
        }
        Row(
            horizontalArrangement = Arrangement.spacedBy(KalivTokens.Spacing.s4),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StreamingCursor()
            EqualizerBars()
        }
        KalivDragHandle()
    }

    @Test
    fun buttonsDark() = snap(dark = true) { Buttons() }

    @Test
    fun buttonsLight() = snap(dark = false) { Buttons() }

    @Test
    fun chipsDark() = snap(dark = true) { Chips() }

    @Test
    fun chipsLight() = snap(dark = false) { Chips() }

    @Test
    fun controlsDark() = snap(dark = true) { Controls() }

    @Test
    fun controlsLight() = snap(dark = false) { Controls() }
}
