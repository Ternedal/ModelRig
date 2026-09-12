package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * #1278 current-main reconciliation adapters.
 *
 * The qualified pkt. 8 App.kt consumes authority-aware sidebar/performance
 * models. Current main's #1277 light-chrome overloads intentionally keep their
 * historical numeric signatures. These overloads bridge that API boundary
 * without inventing measurements or routing/privacy state, while leaving the
 * landed light-theme source untouched.
 */

private data class Pkt8NavItem(
    val screen: KalivScreen,
    val label: String,
    val glyph: String,
)

private val pkt8NavItems = listOf(
    Pkt8NavItem(KalivScreen.CHAT, "Chat", "\u25AC"),
    Pkt8NavItem(KalivScreen.AGENT, "Agent", "\u25C8"),
    Pkt8NavItem(KalivScreen.COMPUTER, "Computer-use", "\u25A6"),
    Pkt8NavItem(KalivScreen.MODELS, "Modeller", "\u25F0"),
    Pkt8NavItem(KalivScreen.DOCS, "Dokumenter", "\u25A4"),
    Pkt8NavItem(KalivScreen.SETTINGS, "Indstillinger", "\u2699"),
)

@Composable
fun KalivNavRail(
    active: KalivScreen,
    onSelect: (KalivScreen) -> Unit,
    status: KalivSidebarStatus,
    vram: KalivVramTelemetry,
) {
    val c = KalivTheme.colors
    val railBackground = if (c.isDark) Color(0x8C14110E) else c.Surface

    Column(
        Modifier
            .width(246.dp)
            .fillMaxHeight()
            .background(railBackground)
            .padding(horizontal = 14.dp, vertical = 16.dp),
    ) {
        pkt8NavItems.forEach { item ->
            Pkt8NavRow(
                item = item,
                active = item.screen == active,
                onClick = { onSelect(item.screen) },
            )
            Spacer(Modifier.height(4.dp))
        }

        Spacer(Modifier.weight(1f))
        Pkt8AuthorityModelCard(status, vram)
        Spacer(Modifier.height(12.dp))
        Pkt8AuthorityPrivacySeal(status)
    }
}

@Composable
private fun Pkt8NavRow(item: Pkt8NavItem, active: Boolean, onClick: () -> Unit) {
    val c = KalivTheme.colors
    val shape = RoundedCornerShape(9.dp)
    val base = Modifier
        .fillMaxWidth()
        .clip(shape)
        .clickable(onClickLabel = item.label, role = Role.Tab, onClick = onClick)
    val decorated = if (active) {
        val start = if (c.isDark) Color(0x389A7136) else c.Signal.copy(alpha = 0.12f)
        val end = if (c.isDark) Color(0x0F9A7136) else c.Signal.copy(alpha = 0.04f)
        val border = if (c.isDark) Color(0x599A7136) else c.Signal.copy(alpha = 0.30f)
        base
            .background(Brush.horizontalGradient(listOf(start, end)))
            .border(1.dp, border, shape)
    } else {
        base
    }
    val inactiveInk = if (c.isDark) Color(0xFFC3B8A8) else c.TextMuted

    Row(
        decorated.padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(item.glyph, color = if (active) c.Highlight else c.TextMuted, fontSize = 15.sp, modifier = Modifier.width(24.dp))
        Spacer(Modifier.width(6.dp))
        Text(
            item.label,
            color = if (active) c.TextHigh else inactiveInk,
            fontSize = 13.5.sp,
            fontWeight = if (active) FontWeight.Medium else FontWeight.Normal,
        )
    }
}

@Composable
private fun Pkt8AuthorityModelCard(status: KalivSidebarStatus, vram: KalivVramTelemetry) {
    val c = KalivTheme.colors
    val presentation = presentVram(vram)
    val shape = RoundedCornerShape(11.dp)
    val border = if (c.isDark) Color(0x33785A37) else c.Border

    Column(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(c.SurfaceHigh)
            .border(1.dp, border, shape)
            .padding(horizontal = 13.dp, vertical = 11.dp),
    ) {
        SectionLabel("Primær model")
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(7.dp).clip(CircleShape)
                    .background(if (status.localOnly) c.Success else c.Warning),
            )
            Spacer(Modifier.width(7.dp))
            Text(status.modelName, color = c.TextHigh, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
        }
        Spacer(Modifier.height(3.dp))
        Text(status.modelAuthority, color = c.TextMuted, fontSize = 11.5.sp)
        presentation.fraction?.let { fraction ->
            Spacer(Modifier.height(9.dp))
            MetaBar(fraction)
        }
        Spacer(Modifier.height(5.dp))
        Text(
            presentation.label,
            color = c.TextMuted,
            fontSize = 10.5.sp,
            fontFamily = FontFamily.Monospace,
        )
    }
}

@Composable
private fun Pkt8AuthorityPrivacySeal(status: KalivSidebarStatus) {
    val c = KalivTheme.colors
    val shape = RoundedCornerShape(11.dp)
    val background = if (c.isDark) Color(0x1A9A7136) else c.Signal.copy(alpha = 0.08f)
    val border = if (c.isDark) Color(0x339A7136) else c.Signal.copy(alpha = 0.24f)

    Row(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(background)
            .border(1.dp, border, shape)
            .padding(horizontal = 13.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(if (status.localOnly) "\uD83D\uDD12" else "\u2197", color = c.Highlight, fontSize = 15.sp)
        Spacer(Modifier.width(9.dp))
        Column {
            Text(status.privacyTitle, color = c.TextHigh, fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
            Text(status.privacyDetail, color = c.TextMuted, fontSize = 10.5.sp)
        }
    }
}

@Composable
fun KalivContextPanel(
    ragOn: Boolean,
    onToggleRag: () -> Unit,
    docs: List<RagDocRow>,
    onAddDocument: () -> Unit,
    performance: KalivPerformanceTelemetry,
) {
    val c = KalivTheme.colors
    val panelBackground = if (c.isDark) Color(0x8014110E) else c.Surface
    val performancePresentation = presentPerformance(performance)

    Column(
        Modifier
            .width(300.dp)
            .fillMaxHeight()
            .background(panelBackground)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Pkt8Card {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("Kontekst & RAG", color = c.TextHigh, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                PillToggle(on = ragOn, label = "Kontekst & RAG", onToggle = onToggleRag)
            }
            Spacer(Modifier.height(8.dp))
            Text(
                if (ragOn) "Dokumenter indgår i svar. Kun lokalt — intet sendes til sky uden dit samtykke."
                else "RAG er slået fra. Slå til for at lade Kaliv svare ud fra dine dokumenter.",
                color = c.TextMuted,
                fontSize = 12.sp,
                lineHeight = 18.sp,
            )
        }

        Pkt8Card {
            SectionLabel("Aktive dokumenter")
            Spacer(Modifier.height(10.dp))
            if (docs.isEmpty()) {
                Text("(ingen dokumenter ingesteret endnu)", color = c.TextMuted, fontSize = 12.sp)
            } else {
                docs.take(6).forEach { doc ->
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 4.dp)) {
                        val tile = if (c.isDark) Color(0xFF2A211A) else c.Graphite
                        Box(
                            Modifier.size(26.dp).clip(RoundedCornerShape(7.dp)).background(tile),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(doc.kind, color = c.Highlight, fontSize = 8.5.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
                        }
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(doc.name, color = c.TextHigh, fontSize = 12.5.sp, maxLines = 1)
                            if (doc.size.isNotBlank()) Text(doc.size, color = c.TextMuted, fontSize = 10.5.sp)
                        }
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            Pkt8OutlineChip("+ Tilføj dokument", onAddDocument)
        }

        Pkt8Card {
            SectionLabel("Ydelse")
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                Column(Modifier.weight(1f)) {
                    Text("Tokens / sek.", color = c.TextMuted, fontSize = 11.sp)
                    Text(
                        performancePresentation.tokensPerSecondText,
                        color = if (performancePresentation.measured) c.Highlight else c.TextMuted,
                        fontSize = if (performancePresentation.measured) 22.sp else 12.5.sp,
                        fontWeight = if (performancePresentation.measured) FontWeight.SemiBold else FontWeight.Normal,
                    )
                }
                performancePresentation.sparkline?.let { points ->
                    Sparkline(points, Modifier.width(120.dp).height(34.dp))
                }
            }
            Spacer(Modifier.height(10.dp))
            Row {
                Text("Svartid", color = c.TextMuted, fontSize = 11.sp)
                Spacer(Modifier.weight(1f))
                Text(
                    performancePresentation.responseTimeText,
                    color = if (performancePresentation.measured) c.TextHigh else c.TextMuted,
                    fontSize = 12.5.sp,
                    fontFamily = FontFamily.Monospace,
                )
            }
            if (!performancePresentation.measured) {
                Spacer(Modifier.height(6.dp))
                Text("Vises først, når en rigtig svartur er målt.", color = c.TextMuted, fontSize = 10.5.sp)
            }
        }
    }
}

@Composable
private fun Pkt8Card(content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    val c = KalivTheme.colors
    val shape = RoundedCornerShape(12.dp)
    val background = if (c.isDark) c.Surface else c.SurfaceHigh
    val border = if (c.isDark) Color(0x4D785A37) else c.Border
    Column(
        Modifier.fillMaxWidth().clip(shape).background(background).border(1.dp, border, shape).padding(14.dp),
        content = content,
    )
}

@Composable
private fun Pkt8OutlineChip(label: String, onClick: () -> Unit) {
    val c = KalivTheme.colors
    val shape = RoundedCornerShape(9.dp)
    val border = if (c.isDark) Color(0x4D785A37) else c.Border
    Box(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(c.SurfaceHigh)
            .border(1.dp, border, shape)
            .clickable(onClick = onClick)
            .padding(vertical = 9.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = c.Signal, fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
    }
}

/**
 * The qualified stack deliberately fails this legacy call shape closed: it has
 * no bound endpoint/auth/model snapshot and therefore cannot honestly claim a
 * live computer-use run. The current-main parameterized implementation remains
 * available to callers that actually supply that authority.
 */
@Composable
fun KalivComputerUse(onRunningChange: (Boolean) -> Unit) {
    val presentation = presentComputerUse()
    LaunchedEffect(Unit) { onRunningChange(false) }

    Box(
        Modifier.fillMaxSize().background(KalivTheme.colors.Graphite).padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Pkt8Card {
            Row(verticalAlignment = Alignment.CenterVertically) {
                KalivAnkh(24)
                Spacer(Modifier.width(10.dp))
                SectionLabel("Computer-use")
                Spacer(Modifier.weight(1f))
                Box(
                    Modifier
                        .clip(RoundedCornerShape(999.dp))
                        .background(KalivTheme.colors.SurfaceHigh)
                        .border(1.dp, KalivTheme.colors.Border, RoundedCornerShape(999.dp))
                        .padding(horizontal = 10.dp, vertical = 4.dp),
                ) {
                    Text("Ikke aktiv", color = KalivTheme.colors.TextMuted, fontSize = 10.5.sp)
                }
            }
            Spacer(Modifier.height(16.dp))
            Text(presentation.title, color = KalivTheme.colors.TextHigh, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            Text(presentation.detail, color = KalivTheme.colors.TextMuted, fontSize = 13.sp, lineHeight = 20.sp)
            Spacer(Modifier.height(14.dp))
            Text(
                "Ingen opgave køres, ingen live-viewport vises, og ingen godkendelse kan sendes fra denne skærm.",
                color = KalivTheme.colors.TextMuted,
                fontSize = 12.sp,
                lineHeight = 18.sp,
            )
        }
    }
}
