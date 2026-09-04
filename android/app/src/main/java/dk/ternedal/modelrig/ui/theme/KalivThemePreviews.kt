package dk.ternedal.modelrig.ui.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp

/**
 * Preview-galleri for fase 1 (DDR-001): tjek typografi og farveroller i
 * Android Studio uden at roere nogen skaerm. Ingen runtime-brug.
 */

@Preview(name = "Typografi - moerk", showBackground = true, backgroundColor = 0xFF0B0A09)
@Composable
private fun TypeRampDarkPreview() {
    Column(Modifier.padding(16.dp)) {
        Text("Hvad kan jeg hjaelpe med?", style = KalivType.Title, color = KalivTokens.Dark.text)
        Spacer(Modifier.height(8.dp))
        Text("Kilde & model", style = KalivType.SheetTitle, color = KalivTokens.Dark.text)
        Spacer(Modifier.height(8.dp))
        Text("Opsummer et dokument", style = KalivType.RowTitle, color = KalivTokens.Dark.text)
        Text("Sekundaer tekst om raekken", style = KalivType.Secondary, color = KalivTokens.Dark.muted)
        Text("Sub-/metatekst \u00b7 10:42", style = KalivType.Sub, color = KalivTokens.Dark.faint)
        Spacer(Modifier.height(8.dp))
        Text("I DAG", style = KalivType.CapsLabel, color = KalivTokens.Dark.caps)
        Text("KALIV", style = KalivType.BrandLine, color = KalivTokens.Dark.accent)
    }
}

@Preview(name = "Typografi - lys", showBackground = true, backgroundColor = 0xFFF7F3EC)
@Composable
private fun TypeRampLightPreview() {
    Column(Modifier.padding(16.dp)) {
        Text("Hvad kan jeg hjaelpe med?", style = KalivType.Title, color = KalivTokens.Light.text)
        Spacer(Modifier.height(8.dp))
        Text("Opsummer et dokument", style = KalivType.RowTitle, color = KalivTokens.Light.text)
        Text("Sekundaer tekst om raekken", style = KalivType.Secondary, color = KalivTokens.Light.muted)
        Text("Sub-/metatekst \u00b7 10:42", style = KalivType.Sub, color = KalivTokens.Light.faint)
        Spacer(Modifier.height(8.dp))
        Text("I DAG", style = KalivType.CapsLabel, color = KalivTokens.Light.caps)
        Text("KALIV", style = KalivType.BrandLine, color = KalivTokens.Light.accent)
    }
}

@Composable
private fun Swatch(name: String, color: Color, textColor: Color) {
    Row(Modifier.padding(vertical = 2.dp)) {
        Box(Modifier.size(28.dp).background(color))
        Spacer(Modifier.width(8.dp))
        Text(name, style = KalivType.Sub, color = textColor)
    }
}

@Preview(name = "Farveroller - moerk", showBackground = true, backgroundColor = 0xFF0B0A09)
@Composable
private fun ColorRolesDarkPreview() {
    val t = KalivTokens.Dark
    Column(Modifier.padding(16.dp)) {
        listOf(
            "canvas" to t.canvas, "surface" to t.surface, "surfaceDim" to t.surfaceDim,
            "sheet" to t.sheet, "elevated" to t.elevated, "userBubble" to t.userBubble,
            "border" to t.border, "divider" to t.divider, "accent" to t.accent,
            "gold.fill" to KalivTokens.Gold.fill, "gold.on" to KalivTokens.Gold.on,
            "ok" to t.ok, "warn" to t.warn, "danger" to t.danger,
        ).forEach { (name, c) -> Swatch(name, c, t.text) }
    }
}

@Preview(name = "Farveroller - lys", showBackground = true, backgroundColor = 0xFFF7F3EC)
@Composable
private fun ColorRolesLightPreview() {
    val t = KalivTokens.Light
    Column(Modifier.padding(16.dp)) {
        listOf(
            "canvas" to t.canvas, "surface" to t.surface, "surfaceDim" to t.surfaceDim,
            "elevated" to t.elevated, "userBubble" to t.userBubble,
            "border" to t.border, "divider" to t.divider, "accent" to t.accent,
            "gold.fill" to KalivTokens.Gold.fill, "gold.on" to KalivTokens.Gold.on,
            "ok" to t.ok, "warn" to t.warn, "danger" to t.danger,
        ).forEach { (name, c) -> Swatch(name, c, t.text) }
    }
}
