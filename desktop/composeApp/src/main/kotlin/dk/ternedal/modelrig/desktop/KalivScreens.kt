package dk.ternedal.modelrig.desktop

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.input.key.isShiftPressed
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.SnapshotStateList
import dk.ternedal.modelrig.desktop.net.AuditEntry
import dk.ternedal.modelrig.desktop.net.ToolTurn
import dk.ternedal.modelrig.desktop.net.ToolsClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * The three design directions from the Windows handoff (design_handoff_kaliv_windows):
 *   - CHAT  = 1a "Rolig arbejdsflade" (chat-primary; the evolved App())
 *   - AGENT = 1b "Agent-cockpit" (plan timeline + inline approval + action log)
 *   - COMPUTER = 1c "Computer-use split" (live viewport + step list + pause/stop)
 *   - MODELS/DOCS/SETTINGS route to the existing panels.
 *
 * Selected by the left nav-rail. All colours come from KalivTheme.colors (the
 * KalivDark/KalivLight tokens in Brand.kt) so dark/light follow automatically --
 * no new tokens, per the handoff.
 */
enum class KalivScreen { CHAT, AGENT, COMPUTER, MODELS, DOCS, SETTINGS }

// ---------------------------------------------------------------------------
// Shared design primitives (handoff "Design Tokens" + reused App.kt patterns)
// ---------------------------------------------------------------------------

/** Primary-button gradient from the handoff: linear-gradient(180°, #A87B3B → #8A6530). */
internal val kalivPrimaryGradient: Brush
    get() = Brush.verticalGradient(listOf(Color(0xFFA87B3B), Color(0xFF8A6530)))

internal val kalivPrimaryInk = Color(0xFFFFF6E9)

/**
 * The ankh brand mark. dark symbol on dark theme, light on light (handoff:
 * "Assets"). Falls back silently if the resource is missing (via kalivSymbolPainter,
 * som App.kt ogsaa bruger).
 */
/** Marker udelukkende til classloader-opslag af bundtede ressourcer. */
private object KalivRes

/**
 * Compose forbyder composable-kald baade inde i runCatching's lambda OG inde i
 * try/catch, saa det gamle vaern om painterResource kan ikke overleve en nyere
 * compiler. Loesningen er ikke at fjerne faldbacken, men at flytte den fejlbare
 * del ud af kompositionen: om classpath-ressourcen findes er et almindeligt
 * opslag. Er den der, kaldes painterResource uden vaern.
 */
@Composable
internal fun kalivSymbolPainter(dark: Boolean): Painter? {
    val name = if (dark) "kaliv_symbol_dark.png" else "kaliv_symbol_light.png"
    val present = remember(name) {
        KalivRes::class.java.classLoader?.getResource(name) != null
    }
    return if (present) painterResource(name) else null
}

@Composable
internal fun KalivAnkh(size: Int, modifier: Modifier = Modifier) {
    kalivSymbolPainter(KalivTheme.colors.isDark)?.let {
        Image(painter = it, contentDescription = null, modifier = modifier.size(size.dp))
    }
}

/** UPPERCASE section label: 10.5sp, letter-spacing .08em, TextMuted (handoff typography). */
@Composable
internal fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(),
        color = KalivTheme.colors.TextMuted,
        fontSize = 10.5.sp,
        fontWeight = FontWeight.Medium,
        letterSpacing = 0.8.sp,
        modifier = modifier,
    )
}

/**
 * A titled card (radius 12, Surface, 1dp subtle border) -- the panel/card shell
 * used by the right-hand panels (1a) and the log (1b). Matches the handoff's
 * "kort/paneler 12dp" radius and rgba(120,90,55,.3) subtle border.
 */
@Composable
internal fun KalivCard(
    modifier: Modifier = Modifier,
    padding: Int = 14,
    content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(12.dp)
    Column(
        modifier
            .clip(shape)
            .background(KalivTheme.colors.Surface)
            .border(1.dp, Color(0x4D785A37), shape) // rgba(120,90,55,.3)
            .padding(padding.dp),
        content = content,
    )
}

/**
 * A risk badge (READ / WRITE / DESTRUCTIVE) -- monospace 9.5sp, uppercase,
 * radius 5, pill-tinted per the handoff's risk table. Read=success family,
 * write=warning family, destructive=danger family.
 */
enum class RiskLevel { READ, WRITE, DESTRUCTIVE }

@Composable
internal fun RiskBadge(risk: RiskLevel, modifier: Modifier = Modifier) {
    // Handoff exact rgba values for the badge bg/fg per level.
    val (bg, fg, label) = when (risk) {
        RiskLevel.READ -> Triple(Color(0x33785A37), Color(0xFFB8AC9C), "READ")
        RiskLevel.WRITE -> Triple(Color(0x38B9823F), Color(0xFFD09A55), "WRITE")
        RiskLevel.DESTRUCTIVE -> Triple(Color(0x339C564C), Color(0xFFC47B70), "DESTRUCTIVE")
    }
    Box(
        modifier
            .clip(RoundedCornerShape(5.dp))
            .background(bg)
            .padding(horizontal = 6.dp, vertical = 2.dp),
    ) {
        Text(
            label,
            color = fg,
            fontSize = 9.5.sp,
            fontFamily = FontFamily.Monospace,
            fontWeight = FontWeight.Medium,
            letterSpacing = 0.5.sp,
        )
    }
}

/**
 * A slim horizontal meter (VRAM bar / any progress) -- the handoff "metabar":
 * dark trough, bronze→highlight fill.
 */
@Composable
internal fun MetaBar(fraction: Float, modifier: Modifier = Modifier, height: Int = 6) {
    val trough = Color(0xFF100C09)
    Box(
        modifier
            .fillMaxWidth()
            .height(height.dp)
            .clip(RoundedCornerShape(999.dp))
            .background(trough),
    ) {
        Box(
            Modifier
                .fillMaxHeight()
                .fillMaxWidth(fraction.coerceIn(0f, 1f))
                .clip(RoundedCornerShape(999.dp))
                .background(Brush.horizontalGradient(listOf(KalivTheme.colors.Signal, KalivTheme.colors.Highlight))),
        )
    }
}

// ---------------------------------------------------------------------------
// Left nav-rail (1a) -- 246dp, six items + active-model card + privacy seal
// ---------------------------------------------------------------------------

/**
 * The 40dp custom title bar from the mockup -- present on ALL three
 * directions and the single strongest visual signature of the design.
 * Layout: 24dp ankh, KALIV wordmark at 14sp, a per-screen subtitle, an
 * optional live status (1c while running), then the window caps.
 *
 * The earlier build kept App.kt's tall Header instead of this, which put the
 * KALIV wordmark on screen twice and made every direction read wrong.
 */
@Composable
fun KalivTitleBar(
    subtitle: String,
    live: String? = null,
    onClose: (() -> Unit)? = null,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .height(40.dp)
            .background(KalivTheme.colors.ShellTitleBar)
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
            color = KalivTheme.colors.ShellTitleText,
        )
        Spacer(Modifier.width(10.dp))
        Text(subtitle, fontSize = 11.5.sp, color = KalivTheme.colors.ShellSubtitleText)
        if (live != null) {
            Spacer(Modifier.width(14.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.size(7.dp).clip(CircleShape)
                        .background(KalivTheme.colors.Warning),
                )
                Spacer(Modifier.width(6.dp))
                Text(live, fontSize = 11.sp, color = KalivTheme.colors.ShellLiveText)
            }
        }
        Spacer(Modifier.weight(1f))
        // No window controls here: the OS titlebar already owns minimise/
        // maximise/close, and drawing a second (mostly dead) set doubled the
        // chrome (#779 item 2).
    }
}


/**
 * The 70dp icon-only rail the mockup uses for 1b (and, as a small documented
 * deviation, 1c -- the mockup drops the rail entirely there, which would trap
 * the user with no way back). Items are 44x44 with the same bronze active
 * treatment as the wide rail.
 */
@Composable
fun KalivIconRail(active: KalivScreen, onSelect: (KalivScreen) -> Unit) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .width(70.dp)
            .fillMaxHeight()
            .background(KalivTheme.colors.ShellRail)
            .padding(vertical = 16.dp),
    ) {
        kalivIconRailDestinations
            .filter { it.screen != KalivScreen.SETTINGS }
            .forEach { destination ->
                IconRailItem(
                    destination = destination,
                    on = destination.isSelected(active),
                    onClick = { onSelect(destination.screen) },
                )
                Spacer(Modifier.height(8.dp))
            }
        Spacer(Modifier.weight(1f))
        val settings = kalivIconRailDestinations.single { it.screen == KalivScreen.SETTINGS }
        IconRailItem(
            destination = settings,
            on = settings.isSelected(active),
            onClick = { onSelect(settings.screen) },
        )
    }
}

@Composable
private fun IconRailItem(destination: KalivNavDestination, on: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    Box(
        contentAlignment = Alignment.Center,
        modifier = Modifier
            .size(44.dp)
            .clip(shape)
            .then(
                if (on) Modifier
                    .background(
                        Brush.verticalGradient(
                            listOf(Color(0x479A7136), Color(0x149A7136)),
                        ),
                    )
                    .border(1.dp, Color(0x669A7136), shape)
                else Modifier,
            )
            .semantics {
                contentDescription = destination.label
                selected = on
            }
            .clickable(onClickLabel = destination.label, role = Role.Tab, onClick = onClick),
    ) {
        Text(
            destination.iconGlyph,
            fontSize = 18.sp,
            color = if (on) KalivTheme.colors.TextHigh else KalivTheme.colors.ShellInactiveText,
            modifier = Modifier.clearAndSetSemantics { },
        )
    }
}

/**
 * The 246dp left navigation rail shared by 1a/1b/1c. Active item gets the
 * bronze gradient + border (handoff: linear-gradient(90°, rgba(154,113,54,.22)
 * → .06) + 1dp rgba(154,113,54,.35)). Bottom holds the active-model card
 * (VRAM meter) and the privacy seal.
 */
@Composable
fun KalivNavRail(
    active: KalivScreen,
    onSelect: (KalivScreen) -> Unit,
    status: KalivSidebarStatus,
    vram: KalivVramTelemetry,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier
            .width(246.dp)
            .fillMaxHeight()
            .background(KalivTheme.colors.ShellRail)
            .padding(horizontal = 14.dp, vertical = 16.dp),
    ) {
        // No brand row here: the 40dp KalivTitleBar above owns the ankh and
        // the KALIV wordmark. The mockup's rail starts straight at the nav
        // items -- having both is what put the wordmark on screen twice.
        kalivNavDestinations.forEach { destination ->
            NavRow(
                destination = destination,
                active = destination.isSelected(active),
                onClick = { onSelect(destination.screen) },
            )
            Spacer(Modifier.height(4.dp))
        }

        Spacer(Modifier.weight(1f))

        // Model/routing authority comes from explicit configured state.
        ActiveModelCard(status = status, vram = vram)
        Spacer(Modifier.height(12.dp))
        PrivacySeal(status)
    }
}

@Composable
private fun NavRow(destination: KalivNavDestination, active: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(9.dp)
    val base = Modifier
        .fillMaxWidth()
        .clip(shape)
        .semantics { selected = active }
        .clickable(onClickLabel = destination.label, role = Role.Tab, onClick = onClick)
    val bg = if (active) {
        base.background(
            Brush.horizontalGradient(listOf(Color(0x389A7136), Color(0x0F9A7136))), // .22 → .06
        ).border(1.dp, Color(0x599A7136), shape) // .35
    } else {
        base
    }
    Row(
        bg.padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            destination.wideGlyph,
            color = if (active) KalivTheme.colors.Highlight else KalivTheme.colors.TextMuted,
            fontSize = 15.sp,
            modifier = Modifier.width(24.dp).clearAndSetSemantics { },
        )
        Spacer(Modifier.width(6.dp))
        Text(
            destination.label,
            color = if (active) KalivTheme.colors.TextHigh else KalivTheme.colors.ShellInactiveText,
            fontSize = 13.5.sp,
            fontWeight = if (active) FontWeight.Medium else FontWeight.Normal,
        )
    }
}

@Composable
private fun ActiveModelCard(status: KalivSidebarStatus, vram: KalivVramTelemetry) {
    val shape = RoundedCornerShape(11.dp)
    val vramPresentation = presentVram(vram)
    Column(
        Modifier.fillMaxWidth().clip(shape)
            .background(KalivTheme.colors.SurfaceHigh)
            .border(1.dp, Color(0x33785A37), shape)
            .padding(horizontal = 13.dp, vertical = 11.dp),
    ) {
        SectionLabel("Primær model")
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(7.dp).clip(RoundedCornerShape(999.dp))
                    .background(if (status.localOnly) KalivTheme.colors.Success else KalivTheme.colors.Amber),
            )
            Spacer(Modifier.width(7.dp))
            Text(status.modelName, color = KalivTheme.colors.TextHigh, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
        }
        Spacer(Modifier.height(3.dp))
        Text(status.modelAuthority, color = KalivTheme.colors.TextMuted, fontSize = 11.5.sp)
        vramPresentation.fraction?.let { fraction ->
            Spacer(Modifier.height(9.dp))
            MetaBar(fraction)
        }
        Spacer(Modifier.height(5.dp))
        Text(
            vramPresentation.label,
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.5.sp,
            fontFamily = FontFamily.Monospace,
        )
    }
}

@Composable
private fun PrivacySeal(status: KalivSidebarStatus) {
    val shape = RoundedCornerShape(11.dp)
    Row(
        Modifier.fillMaxWidth().clip(shape)
            .background(Color(0x1A9A7136)) // rgba(154,113,54,.1)
            .border(1.dp, Color(0x339A7136), shape)
            .padding(horizontal = 13.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(if (status.localOnly) "🔒" else "↗", color = KalivTheme.colors.Highlight, fontSize = 15.sp)
        Spacer(Modifier.width(9.dp))
        Column {
            Text(status.privacyTitle, color = KalivTheme.colors.ShellTitleText, fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
            Text(status.privacyDetail, color = KalivTheme.colors.TextMuted, fontSize = 10.5.sp)
        }
    }
}

// ---------------------------------------------------------------------------
// Right-hand context panel (1a) -- 300dp: Context&RAG, Active docs, Performance
// ---------------------------------------------------------------------------

data class RagDocRow(val kind: String, val name: String, val size: String)

/**
 * The 300dp right panel of 1a. RAG state and source rows reflect live product
 * state. Performance is rendered only from explicit measurement authority;
 * missing measurement stays visibly unavailable rather than using demo data.
 */
@Composable
fun KalivContextPanel(
    ragOn: Boolean,
    onToggleRag: () -> Unit,
    docs: List<RagDocRow>,
    onAddDocument: () -> Unit,
    performance: KalivPerformanceTelemetry,
    modifier: Modifier = Modifier,
) {
    val performancePresentation = presentPerformance(performance)
    Column(
        modifier
            .width(300.dp)
            .fillMaxHeight()
            .background(KalivTheme.colors.ShellPanel)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        // Context & RAG card with a real toggle
        KalivCard {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("Kontekst & RAG", color = KalivTheme.colors.TextHigh, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                PillToggle(on = ragOn, label = "Kontekst & RAG", onToggle = onToggleRag)
            }
            Spacer(Modifier.height(8.dp))
            Text(
                if (ragOn) "Dokumenter indgår i svar. Kun lokalt \u2014 intet sendes til sky uden dit samtykke."
                else "RAG er slået fra. Slå til for at lade Kaliv svare ud fra dine dokumenter.",
                color = KalivTheme.colors.TextMuted,
                fontSize = 12.sp,
                lineHeight = 18.sp,
            )
        }

        // Active documents card
        KalivCard {
            SectionLabel("Aktive dokumenter")
            Spacer(Modifier.height(10.dp))
            if (docs.isEmpty()) {
                Text("(ingen dokumenter ingesteret endnu)", color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
            } else {
                docs.take(6).forEach { d ->
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 4.dp)) {
                        Box(
                            Modifier.size(26.dp).clip(RoundedCornerShape(7.dp))
                                .background(Color(0xFF2A211A)),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(d.kind, color = KalivTheme.colors.Highlight, fontSize = 8.5.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
                        }
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(d.name, color = KalivTheme.colors.TextHigh, fontSize = 12.5.sp, maxLines = 1)
                            if (d.size.isNotBlank()) Text(d.size, color = KalivTheme.colors.TextMuted, fontSize = 10.5.sp)
                        }
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            OutlineChip("+ Tilf\u00f8j dokument", onClick = onAddDocument, modifier = Modifier.fillMaxWidth())
        }

        // Performance card: measured evidence or an explicit neutral state.
        KalivCard {
            SectionLabel("Ydelse")
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                Column(Modifier.weight(1f)) {
                    Text("Tokens / sek.", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                    Text(
                        performancePresentation.tokensPerSecondText,
                        color = if (performancePresentation.measured) KalivTheme.colors.Highlight else KalivTheme.colors.TextMuted,
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
                Text("Svartid", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                Spacer(Modifier.weight(1f))
                Text(
                    performancePresentation.responseTimeText,
                    color = if (performancePresentation.measured) KalivTheme.colors.TextHigh else KalivTheme.colors.TextMuted,
                    fontSize = 12.5.sp,
                    fontFamily = FontFamily.Monospace,
                )
            }
            if (!performancePresentation.measured) {
                Spacer(Modifier.height(6.dp))
                Text(
                    "Vises først, når en rigtig svartur er målt.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 10.5.sp,
                )
            }
        }
    }
}

/** A 38×21 pill switch (handoff: on = #8A6530 track, white knob). */
@Composable
internal fun PillToggle(on: Boolean, label: String, onToggle: () -> Unit) {
    val track = if (on) Color(0xFF8A6530) else KalivTheme.colors.SurfaceHigh
    Box(
        Modifier.size(width = 38.dp, height = 21.dp)
            .clip(RoundedCornerShape(999.dp))
            .background(track)
            .border(1.dp, if (on) Color(0xFF8A6530) else KalivTheme.colors.Border, RoundedCornerShape(999.dp))
            .clickable(onClickLabel = label, role = Role.Switch, onClick = onToggle)
            .padding(horizontal = 3.dp),
        contentAlignment = if (on) Alignment.CenterEnd else Alignment.CenterStart,
    ) {
        Box(Modifier.size(15.dp).clip(RoundedCornerShape(999.dp)).background(Color(0xFFF3EFE6)))
    }
}

/** An outlined chip button (used for "+ Tilføj dokument" etc.). */
@Composable
internal fun OutlineChip(label: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(9.dp)
    Box(
        modifier.clip(shape)
            .background(KalivTheme.colors.SurfaceHigh)
            .border(1.dp, Color(0x4D785A37), shape)
            .clickable(onClick = onClick)
            .padding(vertical = 9.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = KalivTheme.colors.Signal, fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
    }
}

/** Sparkline via Canvas (handoff: same pattern as SendGlyphDesktop/DesktopThinking). */
@Composable
internal fun Sparkline(points: List<Float>, modifier: Modifier = Modifier) {
    val stroke = KalivTheme.colors.Signal
    Canvas(modifier) {
        if (points.size < 2) return@Canvas
        val maxV = (points.max()).coerceAtLeast(0.0001f)
        val minV = points.min()
        val range = (maxV - minV).coerceAtLeast(0.0001f)
        val stepX = size.width / (points.size - 1)
        var prev = Offset(0f, size.height - ((points[0] - minV) / range) * size.height)
        for (i in 1 until points.size) {
            val x = stepX * i
            val y = size.height - ((points[i] - minV) / range) * size.height
            val cur = Offset(x, y)
            drawLine(color = stroke, start = prev, end = cur, strokeWidth = 2f)
            prev = cur
        }
    }
}

// ===========================================================================
// 1b -- Agent-cockpit: plan timeline + inline approval + action log
// ===========================================================================

/** One step in the agent plan (handoff: {tool, risk, status, resultSummary}). */
data class PlanStep(
    val tool: String,
    val risk: RiskLevel,
    val status: StepStatus,
    val resultSummary: String = "",
)

enum class StepStatus { DONE, ACTIVE, PENDING, CANCELLED }

/** Map a worker risk string / tool name to the badge level. */
/**
 * Classify a tool call for the badge.
 *
 * The worker now states `impact` on the confirmation card and in the audit log
 * (write / destructive / admin), which is the finer question the badge is
 * actually asking -- `risk` alone makes note_append, delete_model and
 * pull_model identical. Prefer what the server said.
 *
 * The tool-name fallback below is only for entries that predate the field, and
 * it is deliberately last: a name table is a second copy of a risk
 * classification, and a stale copy fails toward "probably harmless".
 */
internal fun riskOf(risk: String, tool: String, impact: String = ""): RiskLevel {
    val i = impact.lowercase()
    when {
        i == "destructive" -> return RiskLevel.DESTRUCTIVE
        i == "admin" -> return RiskLevel.DESTRUCTIVE
        i == "write" || i == "desktop" -> return RiskLevel.WRITE
        i == "read" -> return RiskLevel.READ
    }
    val r = risk.lowercase()
    val t = tool.lowercase()
    return when {
        "destruct" in r || t.startsWith("delete") || t.startsWith("remove") || t.startsWith("drop") -> RiskLevel.DESTRUCTIVE
        "write" in r || t.startsWith("note") || t.startsWith("append") || t.startsWith("create") || t.startsWith("write") || t.startsWith("pull") -> RiskLevel.WRITE
        else -> RiskLevel.READ
    }
}

/**
 * The 1b agent-cockpit. Four columns: slim icon-rail (provided by the shared
 * KalivNavRail on the left of App), chat column (360dp), plan panel (flex),
 * action log (264dp).
 *
 * This composable renders the plan/chat/log columns; the nav-rail is drawn by
 * App() as with 1a. Task lifecycle (idle -> running -> done) is driven by
 * ToolsClient.toolsChat + toolsConfirm, exactly like the chat tools loop.
 */
@Composable
fun KalivAgentCockpit(
    baseUrl: String,
    bearer: String?,
    model: String,
    system: String?,
    modifier: Modifier = Modifier,
) {
    val scope = rememberCoroutineScope()
    // Conversation for the agent task (its own, separate from chat).
    val turns = remember { mutableStateListOf<Pair<String, String>>() } // role to text
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var taskStarted by remember { mutableStateOf(false) }
    val plan = remember { mutableStateListOf<PlanStep>() }
    var pending by remember { mutableStateOf<ToolTurn?>(null) }
    val log = remember { mutableStateListOf<AuditEntry>() }
    var errorText by remember { mutableStateOf<String?>(null) }

    fun refreshLog() {
        scope.launch {
            val res = withContext(Dispatchers.IO) { runCatching { ToolsClient(baseUrl, bearer).toolsAudit(50) } }
            res.onSuccess { log.clear(); log.addAll(it) }
        }
    }

    fun applyTurn(turn: ToolTurn) {
        when (turn.status) {
            "confirmation_required" -> {
                // The active write step waits for approval; mark it ACTIVE.
                val lvl = riskOf(turn.risk, turn.tool, turn.impact)
                // Replace any existing ACTIVE with this, else append.
                val idx = plan.indexOfFirst { it.status == StepStatus.ACTIVE }
                val step = PlanStep(turn.tool, lvl, StepStatus.ACTIVE, turn.summary)
                if (idx >= 0) plan[idx] = step else plan.add(step)
                pending = turn
            }
            else -> {
                // Terminal: the last active step becomes DONE, answer added to chat.
                val idx = plan.indexOfFirst { it.status == StepStatus.ACTIVE }
                if (idx >= 0) plan[idx] = plan[idx].copy(status = StepStatus.DONE, resultSummary = turn.answer.take(80))
                val ans = turn.answer.ifBlank { "Opgave afsluttet." }
                turns.add("assistant" to ans)
                pending = null
            }
        }
        refreshLog()
    }

    fun startTask() {
        val text = input.trim()
        if (text.isEmpty() || busy || pending != null) return
        errorText = null
        turns.add("user" to text)
        input = ""
        busy = true
        taskStarted = true
        plan.clear()
        scope.launch {
            val res = withContext(Dispatchers.IO) {
                runCatching { ToolsClient(baseUrl, bearer).toolsChat(text, model, turns.dropLast(1), system) }
            }
            res.onSuccess { applyTurn(it) }.onFailure { errorText = it.message }
            busy = false
        }
    }

    fun decide(approve: Boolean) {
        val card = pending ?: return
        if (busy) return
        errorText = null
        busy = true
        scope.launch {
            val res = withContext(Dispatchers.IO) {
                runCatching { ToolsClient(baseUrl, bearer).toolsConfirm(card.confirmation_id, approve) }
            }
            res.onSuccess { turn ->
                // Only the worker response may clear/replace the pending card.
                applyTurn(turn)
                if (!approve && turn.status != "confirmation_required") {
                    // Acknowledged rejection stops the remaining local plan.
                    for (i in plan.indices) {
                        if (plan[i].status == StepStatus.PENDING) {
                            plan[i] = plan[i].copy(
                                status = StepStatus.CANCELLED,
                                resultSummary = "Ikke udf\u00f8rt \u2014 kørslen blev stoppet",
                            )
                        }
                    }
                }
            }.onFailure { errorText = it.message }
            busy = false
        }
    }

    fun clearCompletedTask() {
        // There is no worker cancellation contract. A local clear is only
        // safe after the current turn is terminal and authority is known.
        if (busy || pending != null || errorText != null) return
        taskStarted = false
        plan.clear()
        turns.clear()
    }

    val confirmationPresentation = presentAgentConfirmation(
        hasPendingConfirmation = pending != null,
        busy = busy,
    )

    Row(modifier.fillMaxSize()) {
        // --- Chat column (360dp) ---
        Column(
            Modifier.width(360.dp).fillMaxHeight()
                .background(KalivTheme.colors.Graphite)
                .border(1.dp, Color(0x33785A37), RoundedCornerShape(0.dp))
                .padding(18.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("Opgave", color = KalivTheme.colors.TextHigh, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                val clearPresentation = presentAgentClear(
                    taskStarted = taskStarted,
                    busy = busy,
                    hasPendingConfirmation = pending != null,
                    hasError = errorText != null,
                )
                if (clearPresentation.visible) {
                    OutlineChip(clearPresentation.label.orEmpty(), onClick = { clearCompletedTask() })
                }
            }
            Spacer(Modifier.height(14.dp))
            Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState())) {
                if (!taskStarted) {
                    AgentIdlePrompt()
                } else {
                    turns.forEach { (role, text) -> AgentBubble(role, text) }
                }
            }
            Spacer(Modifier.height(10.dp))
            AgentComposer(
                value = input,
                onValue = { input = it },
                enabled = confirmationPresentation.newTurnEnabled,
                placeholder = if (taskStarted) "F\u00f8lg op \u2026" else "Ny opgave \u2026",
                onSend = { startTask() },
            )
        }

        // --- Plan panel (flex) ---
        Column(
            Modifier.weight(1f).fillMaxHeight()
                .background(KalivTheme.colors.Graphite)
                .padding(horizontal = 22.dp, vertical = 18.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text(
                    "Agent-plan",
                    color = KalivTheme.colors.TextHigh,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    // Never let a squeezed panel break this one letter per
                    // line, which is what happened at the old 1000dp window.
                    softWrap = false,
                    maxLines = 1,
                )
                Spacer(Modifier.width(10.dp))
                val done = plan.count { it.status == StepStatus.DONE }
                if (plan.isNotEmpty()) {
                    Text("$done af ${plan.size} trin", color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                }
                Spacer(Modifier.weight(1f))
                Text(
                    "\uD83D\uDD12 Menneske godkender hver skrivning",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 11.5.sp,
                    softWrap = false,
                    maxLines = 1,
                )
            }
            Spacer(Modifier.height(16.dp))
            errorText?.let { Text("Fejl: $it", color = KalivTheme.colors.Danger, fontSize = 12.sp) }
            if (plan.isEmpty() && !taskStarted) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        "Start en opgave til venstre.\nKaliv l\u00e6gger en plan, k\u00f8rer l\u00e6setrin selv,\nog stopper ved hver skrivning for din godkendelse.",
                        color = KalivTheme.colors.TextMuted, fontSize = 13.sp, lineHeight = 21.sp,
                    )
                }
            } else {
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                    plan.forEachIndexed { i, step ->
                        PlanRow(
                            index = i + 1,
                            step = step,
                            isLast = i == plan.lastIndex,
                            card = if (step.status == StepStatus.ACTIVE && confirmationPresentation.showCard) pending else null,
                            decisionEnabled = confirmationPresentation.decisionEnabled,
                            onApprove = { decide(true) },
                            onDeny = { decide(false) },
                        )
                    }
                }
            }
        }

        // --- Action log (264dp) ---
        Column(
            Modifier.width(264.dp).fillMaxHeight()
                .background(KalivTheme.colors.ShellPanel)
                .padding(16.dp),
        ) {
            SectionLabel("Handlingslog")
            Spacer(Modifier.height(12.dp))
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                if (log.isEmpty()) {
                    Text("(ingen handlinger endnu)", color = KalivTheme.colors.TextMuted, fontSize = 11.5.sp)
                } else {
                    log.forEach { e -> LogEntry(e) }
                }
            }
            Spacer(Modifier.height(10.dp))
            Box(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(9.dp))
                    .background(Color(0x1A9A7136))
                    .border(1.dp, Color(0x339A7136), RoundedCornerShape(9.dp))
                    .padding(11.dp),
            ) {
                Text(
                    "Porten ligger i workeren. En \u00e6ndret klient kan ikke springe den over.",
                    color = KalivTheme.colors.TextMuted, fontSize = 10.5.sp, lineHeight = 15.sp,
                )
            }
        }
    }
}

@Composable
private fun AgentIdlePrompt() {
    Column {
        Text(
            "Beskriv en opgave, s\u00e5 l\u00e6gger Kaliv en plan.",
            color = KalivTheme.colors.TextMuted, fontSize = 13.sp, lineHeight = 20.sp,
        )
        Spacer(Modifier.height(12.dp))
        SectionLabel("Forslag")
        Spacer(Modifier.height(8.dp))
        listOf(
            "Ryd op i mine downloads og skriv en kort note",
            "Tjek riggens status og list de indl\u00e6ste modeller",
            "Find dubletter i mine dokumenter",
        ).forEach {
            Box(Modifier.padding(vertical = 3.dp)) {
                Text("\u2022 $it", color = KalivTheme.colors.ShellInactiveText, fontSize = 12.5.sp)
            }
        }
    }
}

@Composable
private fun AgentBubble(role: String, text: String) {
    val isUser = role == "user"
    Column(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
        if (!isUser) {
            Text("Kaliv", color = KalivTheme.colors.TextMuted, fontSize = 11.sp, fontWeight = FontWeight.Medium)
            Spacer(Modifier.height(3.dp))
        }
        Box(
            Modifier.clip(RoundedCornerShape(13.dp))
                .background(if (isUser) KalivTheme.colors.Signal else KalivTheme.colors.Surface)
                .border(1.dp, if (isUser) KalivTheme.colors.Signal else Color(0x4D785A37), RoundedCornerShape(13.dp))
                .padding(horizontal = 13.dp, vertical = 10.dp),
        ) {
            Text(text, color = if (isUser) kalivPrimaryInk else KalivTheme.colors.TextHigh, fontSize = 13.sp, lineHeight = 20.sp)
        }
    }
}

@Composable
internal fun AgentComposer(value: String, onValue: (String) -> Unit, enabled: Boolean, placeholder: String, onSend: () -> Unit) {
    Row(verticalAlignment = Alignment.Bottom, modifier = Modifier.fillMaxWidth()) {
        OutlinedTextField(
            value = value,
            onValueChange = onValue,
            modifier = Modifier.weight(1f).heightIn(min = 52.dp)
                // Prototype: Enter runs the task, Shift+Enter inserts a
                // newline (onCTaskKey / onTaskKey). Without this the composer
                // could only be sent by hitting the 44dp button, which is a
                // poor fit for a text-first surface -- and it is exactly how
                // I failed to start a task while capturing screenshots.
                .onPreviewKeyEvent { ev ->
                    if (ev.type == KeyEventType.KeyDown &&
                        ev.key == Key.Enter &&
                        !ev.isShiftPressed &&
                        enabled && value.isNotBlank()
                    ) {
                        onSend()
                        true
                    } else {
                        false
                    }
                },
            placeholder = { Text(placeholder, color = KalivTheme.colors.TextMuted, fontSize = 13.sp) },
            enabled = enabled,
            maxLines = 4,
            shape = RoundedCornerShape(14.dp),
        )
        Spacer(Modifier.width(8.dp))
        val canSend = enabled && value.isNotBlank()
        Box(
            Modifier.size(44.dp).clip(RoundedCornerShape(14.dp))
                .background(if (canSend) KalivTheme.colors.Signal else KalivTheme.colors.SurfaceHigh)
                .border(1.dp, if (canSend) KalivTheme.colors.Signal else KalivTheme.colors.Border, RoundedCornerShape(14.dp))
                .clickable(
                    enabled = canSend, onClickLabel = "Send", role = Role.Button,
                    onClick = onSend,
                ),
            contentAlignment = Alignment.Center,
        ) {
            Text("\u2794", color = if (canSend) kalivPrimaryInk else KalivTheme.colors.TextMuted, fontSize = 16.sp)
        }
    }
}

/**
 * One row of the plan timeline: status circle + connector line in the gutter,
 * then tool name + risk badge + result, and (if this is the active write step)
 * the inline approval card.
 */
@Composable
private fun PlanRow(
    index: Int,
    step: PlanStep,
    isLast: Boolean,
    card: ToolTurn?,
    decisionEnabled: Boolean,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
) {
    Row(Modifier.fillMaxWidth()) {
        // Gutter: status circle + connector.
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(26.dp)) {
            StatusCircle(index, step.status)
            if (!isLast) {
                Box(Modifier.width(2.dp).height(40.dp).background(Color(0x4D785A37)))
            }
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f).padding(bottom = 14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    step.tool,
                    color = if (step.status == StepStatus.PENDING || step.status == StepStatus.CANCELLED) {
                        KalivTheme.colors.TextMuted
                    } else {
                        KalivTheme.colors.TextHigh
                    },
                    fontSize = 13.5.sp,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Medium,
                )
                Spacer(Modifier.width(8.dp))
                RiskBadge(step.risk)
            }
            if (step.resultSummary.isNotBlank()) {
                Spacer(Modifier.height(3.dp))
                Text(step.resultSummary, color = KalivTheme.colors.TextMuted, fontSize = 12.sp, lineHeight = 17.sp)
            }
            // Inline approval card for the active write step.
            if (card != null) {
                Spacer(Modifier.height(10.dp))
                ApprovalCard(card = card, enabled = decisionEnabled, onApprove = onApprove, onDeny = onDeny)
            }
        }
    }
}

@Composable
internal fun StatusCircle(index: Int, status: StepStatus) {
    val size = 26
    when (status) {
        StepStatus.DONE -> Box(
            Modifier.size(size.dp).clip(RoundedCornerShape(999.dp))
                .background(Color(0x336F8A63))
                .border(1.dp, KalivTheme.colors.Success, RoundedCornerShape(999.dp)),
            contentAlignment = Alignment.Center,
        ) { Text("\u2713", color = KalivTheme.colors.Success, fontSize = 13.sp) }
        StepStatus.ACTIVE -> Box(
            Modifier.size(size.dp).clip(RoundedCornerShape(999.dp))
                .background(Color(0xFF8A6530))
                .border(4.dp, Color(0x2E9A7136), RoundedCornerShape(999.dp)),
            contentAlignment = Alignment.Center,
        ) { Text("$index", color = kalivPrimaryInk, fontSize = 12.sp, fontWeight = FontWeight.Bold) }
        StepStatus.PENDING -> Box(
            Modifier.size(size.dp).clip(RoundedCornerShape(999.dp))
                .background(KalivTheme.colors.SurfaceHigh)
                .border(1.dp, Color(0x4D785A37), RoundedCornerShape(999.dp)),
            contentAlignment = Alignment.Center,
        ) { Text("$index", color = KalivTheme.colors.TextMuted, fontSize = 12.sp) }
        // A run halted by a rejection: the step will not happen, so it must
        // not keep looking like it is merely waiting its turn.
        StepStatus.CANCELLED -> Box(
            Modifier.size(size.dp).clip(RoundedCornerShape(999.dp))
                .background(Color(0x22000000))
                .border(1.dp, Color(0x4D9C564C), RoundedCornerShape(999.dp)),
            contentAlignment = Alignment.Center,
        ) { Text("\u2715", color = Color(0xFFC47B70), fontSize = 12.sp) }
    }
}

/**
 * The inline approval card (handoff: radius 14, gradient #241A10→#1B140D, 1dp
 * rgba(198,154,75,.45)). Ankh + title + WRITE badge, arg-preview box, and the
 * 50/50 Godkend/Afvis buttons. The gate is in the worker; this only renders.
 */
@Composable
internal fun ApprovalCard(card: ToolTurn, enabled: Boolean = true, onApprove: () -> Unit, onDeny: () -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    Column(
        Modifier.fillMaxWidth().clip(shape)
            .background(Brush.verticalGradient(listOf(Color(0xFF241A10), Color(0xFF1B140D))))
            .border(1.dp, Color(0x73C69A4B), shape)
            .padding(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            KalivAnkh(16)
            Spacer(Modifier.width(8.dp))
            Text("Kaliv vil bruge et v\u00e6rkt\u00f8j", color = KalivTheme.colors.TextHigh, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.weight(1f))
            RiskBadge(riskOf(card.risk, card.tool, card.impact))
        }
        Spacer(Modifier.height(8.dp))
        Text(
            card.summary.ifBlank { "${card.tool} \u2014 afventer din godkendelse" },
            color = KalivTheme.colors.TextMuted, fontSize = 12.sp, lineHeight = 17.sp,
        )
        Spacer(Modifier.height(10.dp))
        // Arg-preview box (monospace on CodeSurface).
        Box(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                .background(Color(0xFF100C09))
                .padding(horizontal = 11.dp, vertical = 9.dp),
        ) {
            Text(
                "tool: ${card.tool}",
                color = KalivTheme.colors.Highlight, fontSize = 11.5.sp, fontFamily = FontFamily.Monospace, lineHeight = 17.sp,
            )
        }
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth()) {
            // Godkend (primary gradient)
            Box(
                Modifier.weight(1f).clip(RoundedCornerShape(10.dp))
                    .background(kalivPrimaryGradient)
                    .clickable(enabled = enabled, onClick = onApprove)
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) { Text("Godkend", color = kalivPrimaryInk, fontSize = 13.sp, fontWeight = FontWeight.SemiBold) }
            Spacer(Modifier.width(10.dp))
            // Afvis (outline)
            Box(
                Modifier.weight(1f).clip(RoundedCornerShape(10.dp))
                    .background(KalivTheme.colors.SurfaceHigh)
                    .border(1.dp, Color(0x4D785A37), RoundedCornerShape(10.dp))
                    .clickable(enabled = enabled, onClick = onDeny)
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) { Text("Afvis", color = KalivTheme.colors.TextHigh, fontSize = 13.sp, fontWeight = FontWeight.Medium) }
        }
    }
}

@Composable
private fun LogEntry(e: AuditEntry) {
    val time = e.ts.take(19).replace('T', ' ').takeLast(8).dropLast(3) // HH:mm
    val dot = when {
        "read" in e.risk.lowercase() || "read" in e.outcome.lowercase() -> KalivTheme.colors.Success
        "pend" in e.outcome.lowercase() || "await" in e.outcome.lowercase() -> KalivTheme.colors.Warning
        else -> KalivTheme.colors.Signal
    }
    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
        Column(Modifier.weight(1f)) {
            Text(
                "${if (time.isNotBlank()) "$time \u00b7 " else ""}${e.tool}",
                color = KalivTheme.colors.TextHigh, fontSize = 11.5.sp, fontFamily = FontFamily.Monospace,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(6.dp).clip(RoundedCornerShape(999.dp)).background(dot))
                Spacer(Modifier.width(6.dp))
                Text(
                    e.outcome + (if (e.origin != "local") " \u00b7 ${e.origin}" else ""),
                    color = KalivTheme.colors.TextMuted, fontSize = 10.5.sp,
                )
            }
        }
    }
}


// ===========================================================================
// 1c -- Computer-use: fail-closed until live desktop execution exists
// ===========================================================================

/**
 * Desktop computer-use deliberately fails closed until this client has a real
 * worker-backed run/viewport contract. The previous prototype seeded completed
 * steps, a mock browser page and a local-only approval result, which made an
 * illustrative mock look like product execution (#925).
 */
@Composable
fun KalivComputerUse(
    modifier: Modifier = Modifier,
    onRunningChange: (Boolean) -> Unit = {},
) {
    val presentation = presentComputerUse()

    // This surface cannot own remote execution yet. Keep the shell's live badge
    // authoritatively off even if a future caller reuses stale local state.
    LaunchedEffect(Unit) { onRunningChange(false) }

    Box(
        modifier
            .fillMaxSize()
            .background(KalivTheme.colors.Graphite)
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        KalivCard(modifier = Modifier.widthIn(max = 620.dp), padding = 24) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                KalivAnkh(24)
                Spacer(Modifier.width(10.dp))
                SectionLabel("Computer-use")
                Spacer(Modifier.weight(1f))
                Box(
                    Modifier.clip(RoundedCornerShape(999.dp))
                        .background(KalivTheme.colors.SurfaceHigh)
                        .border(1.dp, KalivTheme.colors.Border, RoundedCornerShape(999.dp))
                        .padding(horizontal = 10.dp, vertical = 4.dp),
                ) {
                    Text("Ikke aktiv", color = KalivTheme.colors.TextMuted, fontSize = 10.5.sp)
                }
            }
            Spacer(Modifier.height(16.dp))
            Text(
                presentation.title,
                color = KalivTheme.colors.TextHigh,
                fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                presentation.detail,
                color = KalivTheme.colors.TextMuted,
                fontSize = 13.sp,
                lineHeight = 20.sp,
            )
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
