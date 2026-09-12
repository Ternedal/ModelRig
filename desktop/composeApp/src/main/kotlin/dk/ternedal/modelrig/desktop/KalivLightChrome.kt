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
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
 * #1274 / #1273: bounded light-mode migration for the default CHAT shell.
 *
 * These overloads intentionally match the exact arity used by App.kt. The
 * handoff-era implementations in KalivScreens.kt remain available to call
 * sites that explicitly pass their optional modifier/onClose parameters, but
 * App's normal CHAT path selects these exact-arity functions. That keeps this
 * migration small and lets desktop compilation prove the overload boundary.
 *
 * Dark mode keeps the established handoff literals where preserving the
 * current visual is important. Light mode never receives those literals: it
 * derives shell backgrounds, text, borders and accent washes from KalivTheme.
 */

@Composable
fun KalivTitleBar(
    subtitle: String,
    live: String?,
) {
    val c = KalivTheme.colors
    val background = if (c.isDark) Color(0x990B0A09) else c.Surface
    val wordmark = if (c.isDark) Color(0xFFE9DFCE) else c.TextHigh
    val subtitleInk = if (c.isDark) Color(0xFF6F665C) else c.TextMuted

    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .height(40.dp)
            .background(background)
            .padding(start = 14.dp),
    ) {
        KalivAnkh(24)
        Spacer(Modifier.width(11.dp))
        Text(
            "KALIV",
            fontFamily = FontFamily.Serif,
            fontSize = 14.sp,
            letterSpacing = 3.sp,
            fontWeight = FontWeight.Medium,
            color = wordmark,
        )
        Spacer(Modifier.width(10.dp))
        Text(subtitle, fontSize = 11.5.sp, color = subtitleInk)
        if (live != null) {
            Spacer(Modifier.width(14.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(7.dp).clip(CircleShape).background(c.Warning))
                Spacer(Modifier.width(6.dp))
                Text(live, fontSize = 11.sp, color = c.Warning)
            }
        }
        Spacer(Modifier.weight(1f))
    }
}

private data class LightShellNavItem(
    val screen: KalivScreen,
    val label: String,
    val glyph: String,
)

private val lightShellNavItems = listOf(
    LightShellNavItem(KalivScreen.CHAT, "Chat", "\u25AC"),
    LightShellNavItem(KalivScreen.AGENT, "Agent", "\u25C8"),
    LightShellNavItem(KalivScreen.COMPUTER, "Computer-use", "\u25A6"),
    LightShellNavItem(KalivScreen.MODELS, "Modeller", "\u25F0"),
    LightShellNavItem(KalivScreen.DOCS, "Dokumenter", "\u25A4"),
    LightShellNavItem(KalivScreen.SETTINGS, "Indstillinger", "\u2699"),
)

@Composable
fun KalivNavRail(
    active: KalivScreen,
    onSelect: (KalivScreen) -> Unit,
    modelName: String,
    vramUsedGb: Double,
    vramTotalGb: Double,
    modelBackend: String,
) {
    // Compatibility surface for older explicit callers and the L2a overload gate.
    // Supplied numeric values are treated as observations; no defaults are invented.
    KalivNavRail(
        active = active,
        onSelect = onSelect,
        status = KalivSidebarStatus(
            modelName = modelName.ifBlank { "Lokal model ikke valgt" },
            modelAuthority = "Lokal · $modelBackend",
            privacyTitle = "Chat: kun lokal",
            privacyDetail = "Legacy-kald uden cloud-routing authority",
            localOnly = true,
        ),
        vram = KalivVramTelemetry.Measured(vramUsedGb, vramTotalGb),
    )
}

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
        lightShellNavItems.forEach { item ->
            LightShellNavRow(
                item = item,
                active = item.screen == active,
                onClick = { onSelect(item.screen) },
            )
            Spacer(Modifier.height(4.dp))
        }

        Spacer(Modifier.weight(1f))
        LightShellActiveModelCard(status, vram)
        Spacer(Modifier.height(12.dp))
        LightShellPrivacySeal(status)
    }
}

@Composable
private fun LightShellNavRow(
    item: LightShellNavItem,
    active: Boolean,
    onClick: () -> Unit,
) {
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
        Text(
            item.glyph,
            color = if (active) c.Highlight else c.TextMuted,
            fontSize = 15.sp,
            modifier = Modifier.width(24.dp),
        )
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
private fun LightShellActiveModelCard(
    status: KalivSidebarStatus,
    vram: KalivVramTelemetry,
) {
    val c = KalivTheme.colors
    val shape = RoundedCornerShape(11.dp)
    val border = if (c.isDark) Color(0x33785A37) else c.Border
    val vramPresentation = presentVram(vram)
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
                    .background(if (status.localOnly) c.Success else c.Amber),
            )
            Spacer(Modifier.width(7.dp))
            Text(status.modelName, color = c.TextHigh, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
        }
        Spacer(Modifier.height(3.dp))
        Text(status.modelAuthority, color = c.TextMuted, fontSize = 11.5.sp)
        vramPresentation.fraction?.let { fraction ->
            Spacer(Modifier.height(9.dp))
            LightShellMetaBar(fraction)
        }
        Spacer(Modifier.height(5.dp))
        Text(
            vramPresentation.label,
            color = c.TextMuted,
            fontSize = 10.5.sp,
            fontFamily = FontFamily.Monospace,
        )
    }
}

@Composable
private fun LightShellMetaBar(fraction: Float) {
    val c = KalivTheme.colors
    val trough = if (c.isDark) Color(0xFF100C09) else c.Border.copy(alpha = 0.55f)
    Box(
        Modifier
            .fillMaxWidth()
            .height(6.dp)
            .clip(CircleShape)
            .background(trough),
    ) {
        Box(
            Modifier
                .fillMaxHeight()
                .fillMaxWidth(fraction.coerceIn(0f, 1f))
                .clip(CircleShape)
                .background(Brush.horizontalGradient(listOf(c.Signal, c.Highlight))),
        )
    }
}

@Composable
private fun LightShellPrivacySeal(status: KalivSidebarStatus) {
    val c = KalivTheme.colors
    val shape = RoundedCornerShape(11.dp)
    val background = if (c.isDark) Color(0x1A9A7136) else c.Signal.copy(alpha = 0.08f)
    val border = if (c.isDark) Color(0x339A7136) else c.Signal.copy(alpha = 0.24f)
    val headline = if (c.isDark) Color(0xFFE9DFCE) else c.TextHigh

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
            Text(status.privacyTitle, color = headline, fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
            Text(status.privacyDetail, color = c.TextMuted, fontSize = 10.5.sp)
        }
    }
}

private fun lightShellFmtGb(value: Double): String {
    val s = String.format(java.util.Locale.US, "%.1f", value)
    return (if (s.endsWith(".0")) s.dropLast(2) else s).replace('.', ',')
}

@Composable
fun KalivContextPanel(
    ragOn: Boolean,
    onToggleRag: () -> Unit,
    docs: List<RagDocRow>,
    onAddDocument: () -> Unit,
    tokensPerSec: Int,
    responseSeconds: Double,
    sparkline: List<Float>,
) {
    // Compatibility surface: callers supplying observations are explicitly
    // declaring them measured. The normal App path uses the typed overload.
    KalivContextPanel(
        ragOn = ragOn,
        onToggleRag = onToggleRag,
        docs = docs,
        onAddDocument = onAddDocument,
        performance = KalivPerformanceTelemetry.Measured(
            tokensPerSecond = tokensPerSec,
            responseSeconds = responseSeconds,
            sparkline = sparkline,
        ),
    )
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
        LightShellCard {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("Kontekst & RAG", color = c.TextHigh, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                PillToggle(on = ragOn, label = "Kontekst & RAG", onToggle = onToggleRag)
            }
            Spacer(Modifier.height(8.dp))
            Text(
                if (ragOn) {
                    "Dokumenter indgår i svar. Kun lokalt — intet sendes til sky uden dit samtykke."
                } else {
                    "RAG er slået fra. Slå til for at lade Kaliv svare ud fra dine dokumenter."
                },
                color = c.TextMuted,
                fontSize = 12.sp,
                lineHeight = 18.sp,
            )
        }

        LightShellCard {
            SectionLabel("Aktive dokumenter")
            Spacer(Modifier.height(10.dp))
            if (docs.isEmpty()) {
                Text("(ingen dokumenter ingesteret endnu)", color = c.TextMuted, fontSize = 12.sp)
            } else {
                docs.take(6).forEach { doc ->
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 4.dp)) {
                        val tile = if (c.isDark) Color(0xFF2A211A) else c.Graphite
                        Box(
                            Modifier
                                .size(26.dp)
                                .clip(RoundedCornerShape(7.dp))
                                .background(tile),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                doc.kind,
                                color = c.Highlight,
                                fontSize = 8.5.sp,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(doc.name, color = c.TextHigh, fontSize = 12.5.sp, maxLines = 1)
                            if (doc.size.isNotBlank()) {
                                Text(doc.size, color = c.TextMuted, fontSize = 10.5.sp)
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            LightShellOutlineChip("+ Tilføj dokument", onAddDocument)
        }

        LightShellCard {
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
                Text(
                    "Vises først, når en rigtig svartur er målt.",
                    color = c.TextMuted,
                    fontSize = 10.5.sp,
                )
            }
        }
    }
}

@Composable
private fun LightShellCard(
    content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit,
) {
    val c = KalivTheme.colors
    val shape = RoundedCornerShape(12.dp)
    val background = if (c.isDark) c.Surface else c.SurfaceHigh
    val border = if (c.isDark) Color(0x4D785A37) else c.Border
    Column(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(background)
            .border(1.dp, border, shape)
            .padding(14.dp),
        content = content,
    )
}

@Composable
private fun LightShellOutlineChip(label: String, onClick: () -> Unit) {
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
