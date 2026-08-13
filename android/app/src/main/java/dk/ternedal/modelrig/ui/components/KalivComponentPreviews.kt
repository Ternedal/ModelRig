package dk.ternedal.modelrig.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType
import dk.ternedal.modelrig.ui.theme.ModelRigTheme

/** Preview-galleri for komponentbiblioteket — begge temaer, ingen runtime-brug. */

@Composable
private fun ComponentBoard() {
    Column(
        modifier = Modifier
            .background(KalivTheme.colors.background)
            .padding(KalivTokens.Spacing.s4),
        verticalArrangement = Arrangement.spacedBy(KalivTokens.Spacing.s3),
    ) {
        KalivPrimaryButton(text = "Forbind", onClick = {})
        KalivSecondaryButton(text = "Indtast kode manuelt", onClick = {})
        ChipRow(background = KalivTheme.colors.background) {
            KontekstChip(text = "qwen3:14b", onClick = {})
            KontekstChip(text = "RAG \u00b7 Til", onClick = {}, selected = true)
            KontekstChip(text = "V\u00e6rkt\u00f8jer", onClick = {})
            KontekstChip(text = "Agent", onClick = {})
        }
        CapsLabel("I dag")
        Row(
            horizontalArrangement = Arrangement.spacedBy(KalivTokens.Spacing.s3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StatusDot(KalivTheme.colors.success)
            Text("Forbundet", style = KalivType.Secondary, color = KalivTheme.colors.textMuted)
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
}

@Preview(name = "Komponenter - moerk", showBackground = true, backgroundColor = 0xFF0B0A09)
@Composable
private fun ComponentBoardDarkPreview() {
    ModelRigTheme(dark = true) { ComponentBoard() }
}

@Preview(name = "Komponenter - lys", showBackground = true, backgroundColor = 0xFFF7F3EC)
@Composable
private fun ComponentBoardLightPreview() {
    ModelRigTheme(dark = false) { ComponentBoard() }
}
