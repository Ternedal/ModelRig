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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
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
 * "Assets"). Falls back silently if the resource is missing (same runCatching
 * pattern App.kt uses for the header chip).
 */
@Composable
internal fun KalivAnkh(size: Int, modifier: Modifier = Modifier) {
    runCatching {
        painterResource(if (KalivTheme.colors.isDark) "kaliv_symbol_dark.png" else "kaliv_symbol_light.png")
    }.getOrNull()?.let {
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

private data class NavItem(val screen: KalivScreen, val label: String, val glyph: String)

private val navItems = listOf(
    NavItem(KalivScreen.CHAT, "Chat", "\u25AC"),          // ▬ chat
    NavItem(KalivScreen.AGENT, "Agent", "\u25C8"),        // ◈ agent
    NavItem(KalivScreen.COMPUTER, "Computer-use", "\u25A6"), // ▦ computer
    NavItem(KalivScreen.MODELS, "Modeller", "\u25F0"),    // ◰ models
    NavItem(KalivScreen.DOCS, "Dokumenter", "\u25A4"),    // ▤ docs
    NavItem(KalivScreen.SETTINGS, "Indstillinger", "\u2699"), // ⚙ settings
)

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
    modelName: String,
    vramUsedGb: Double,
    vramTotalGb: Double,
    modelBackend: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier
            .width(246.dp)
            .fillMaxHeight()
            .background(Color(0x8C14110E)) // rgba(20,17,14,.55)
            .padding(horizontal = 14.dp, vertical = 16.dp),
    ) {
        // Brand row (ankh + KALIV wordmark), same as the App header.
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 4.dp, bottom = 18.dp)) {
            Box(
                Modifier.size(34.dp).clip(RoundedCornerShape(11.dp))
                    .background(KalivTheme.colors.SurfaceHigh)
                    .border(1.dp, Color(0x80C69A4B), RoundedCornerShape(11.dp)),
                contentAlignment = Alignment.Center,
            ) { KalivAnkh(20) }
            Spacer(Modifier.width(10.dp))
            Text(
                "KALIV",
                color = KalivTheme.colors.TextHigh,
                fontSize = 20.sp,
                fontFamily = FontFamily.Serif,
                fontWeight = FontWeight.Medium,
                letterSpacing = 4.sp,
            )
        }

        navItems.forEach { item ->
            NavRow(item = item, active = item.screen == active, onClick = { onSelect(item.screen) })
            Spacer(Modifier.height(4.dp))
        }

        Spacer(Modifier.weight(1f))

        // Active-model card
        ActiveModelCard(modelName, vramUsedGb, vramTotalGb, modelBackend)
        Spacer(Modifier.height(12.dp))
        PrivacySeal()
    }
}

@Composable
private fun NavRow(item: NavItem, active: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(9.dp)
    val base = Modifier
        .fillMaxWidth()
        .clip(shape)
        .clickable(onClick = onClick)
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
            item.glyph,
            color = if (active) KalivTheme.colors.Highlight else KalivTheme.colors.TextMuted,
            fontSize = 15.sp,
            modifier = Modifier.width(24.dp),
        )
        Spacer(Modifier.width(6.dp))
        Text(
            item.label,
            color = if (active) KalivTheme.colors.TextHigh else Color(0xFFC3B8A8),
            fontSize = 13.5.sp,
            fontWeight = if (active) FontWeight.Medium else FontWeight.Normal,
        )
    }
}

@Composable
private fun ActiveModelCard(modelName: String, usedGb: Double, totalGb: Double, backend: String) {
    val shape = RoundedCornerShape(11.dp)
    Column(
        Modifier.fillMaxWidth().clip(shape)
            .background(KalivTheme.colors.SurfaceHigh)
            .border(1.dp, Color(0x33785A37), shape)
            .padding(horizontal = 13.dp, vertical = 11.dp),
    ) {
        SectionLabel("Aktiv model")
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(7.dp).clip(RoundedCornerShape(999.dp)).background(KalivTheme.colors.Success))
            Spacer(Modifier.width(7.dp))
            Text(modelName, color = KalivTheme.colors.TextHigh, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
        }
        Spacer(Modifier.height(3.dp))
        Text("Lokal \u00b7 $backend", color = KalivTheme.colors.TextMuted, fontSize = 11.5.sp)
        Spacer(Modifier.height(9.dp))
        val frac = if (totalGb > 0) (usedGb / totalGb).toFloat() else 0f
        MetaBar(frac)
        Spacer(Modifier.height(5.dp))
        Text(
            "VRAM ${fmtGb(usedGb)} / ${fmtGb(totalGb)} GB",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.5.sp,
            fontFamily = FontFamily.Monospace,
        )
    }
}

@Composable
private fun PrivacySeal() {
    val shape = RoundedCornerShape(11.dp)
    Row(
        Modifier.fillMaxWidth().clip(shape)
            .background(Color(0x1A9A7136)) // rgba(154,113,54,.1)
            .border(1.dp, Color(0x339A7136), shape)
            .padding(horizontal = 13.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("\uD83D\uDD12", color = KalivTheme.colors.Highlight, fontSize = 15.sp) // 🔒
        Spacer(Modifier.width(9.dp))
        Column {
            Text("100 % lokal", color = Color(0xFFE9DFCE), fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
            Text("Intet forlader maskinen", color = KalivTheme.colors.TextMuted, fontSize = 10.5.sp)
        }
    }
}

private fun fmtGb(v: Double): String {
    // Danish decimal comma, one decimal (handoff copy: "6,2 / 12 GB").
    val s = String.format(java.util.Locale.US, "%.1f", v)
    return (if (s.endsWith(".0")) s.dropLast(2) else s).replace('.', ',')
}

// ---------------------------------------------------------------------------
// Right-hand context panel (1a) -- 300dp: Context&RAG, Active docs, Performance
// ---------------------------------------------------------------------------

data class RagDocRow(val kind: String, val name: String, val size: String)

/**
 * The 300dp right panel of 1a. Reflects the LIVE state passed in (RAG on/off,
 * ingested sources, tokens/sec) rather than mock copy -- the toggle and the
 * source list are driven by App()'s ragMode / ragSources.
 */
@Composable
fun KalivContextPanel(
    ragOn: Boolean,
    onToggleRag: () -> Unit,
    docs: List<RagDocRow>,
    onAddDocument: () -> Unit,
    tokensPerSec: Int,
    responseSeconds: Double,
    sparkline: List<Float>,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier
            .width(300.dp)
            .fillMaxHeight()
            .background(Color(0x8014110E)) // rgba(20,17,14,.5)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        // Context & RAG card with a real toggle
        KalivCard {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("Kontekst & RAG", color = KalivTheme.colors.TextHigh, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                PillToggle(on = ragOn, onToggle = onToggleRag)
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

        // Performance card with sparkline
        KalivCard {
            SectionLabel("Ydelse")
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                Column(Modifier.weight(1f)) {
                    Text("Tokens / sek.", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                    Text("$tokensPerSec", color = KalivTheme.colors.Highlight, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
                }
                Sparkline(sparkline, Modifier.width(120.dp).height(34.dp))
            }
            Spacer(Modifier.height(10.dp))
            Row {
                Text("Svartid", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                Spacer(Modifier.weight(1f))
                Text(
                    (if (String.format(java.util.Locale.US, "%.2f", responseSeconds).endsWith("0"))
                        String.format(java.util.Locale.US, "%.2f", responseSeconds) else
                        String.format(java.util.Locale.US, "%.2f", responseSeconds)).replace('.', ',') + " s",
                    color = KalivTheme.colors.TextHigh, fontSize = 12.5.sp, fontFamily = FontFamily.Monospace,
                )
            }
        }
    }
}

/** A 38×21 pill switch (handoff: on = #8A6530 track, white knob). */
@Composable
internal fun PillToggle(on: Boolean, onToggle: () -> Unit) {
    val track = if (on) Color(0xFF8A6530) else KalivTheme.colors.SurfaceHigh
    Box(
        Modifier.size(width = 38.dp, height = 21.dp)
            .clip(RoundedCornerShape(999.dp))
            .background(track)
            .border(1.dp, if (on) Color(0xFF8A6530) else KalivTheme.colors.Border, RoundedCornerShape(999.dp))
            .clickable(onClick = onToggle)
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

enum class StepStatus { DONE, ACTIVE, PENDING }

/** Map a worker risk string / tool name to the badge level. */
internal fun riskOf(risk: String, tool: String): RiskLevel {
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
                val lvl = riskOf("", turn.tool)
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
        if (text.isEmpty() || busy) return
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
        pending = null
        busy = true
        // Mark the active step's outcome.
        val idx = plan.indexOfFirst { it.status == StepStatus.ACTIVE }
        if (idx >= 0 && !approve) plan[idx] = plan[idx].copy(status = StepStatus.DONE, resultSummary = "Afvist \u2014 intet \u00e6ndret")
        scope.launch {
            val res = withContext(Dispatchers.IO) {
                runCatching { ToolsClient(baseUrl, bearer).toolsConfirm(card.confirmation_id, approve) }
            }
            res.onSuccess { applyTurn(it) }.onFailure { errorText = it.message }
            busy = false
        }
    }

    fun abortTask() {
        taskStarted = false
        plan.clear()
        turns.clear()
        pending = null
        busy = false
    }

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
                if (taskStarted) {
                    OutlineChip("\u2715 Afbryd", onClick = { abortTask() })
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
                enabled = !busy,
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
                Text("Agent-plan", color = KalivTheme.colors.TextHigh, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.width(10.dp))
                val done = plan.count { it.status == StepStatus.DONE }
                if (plan.isNotEmpty()) {
                    Text("$done af ${plan.size} trin", color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                }
                Spacer(Modifier.weight(1f))
                Text("\uD83D\uDD12 Menneske godkender hver skrivning", color = KalivTheme.colors.TextMuted, fontSize = 11.5.sp)
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
                            card = if (step.status == StepStatus.ACTIVE) pending else null,
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
                .background(Color(0x8014110E))
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
                Text("\u2022 $it", color = Color(0xFFC3B8A8), fontSize = 12.5.sp)
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
private fun AgentComposer(value: String, onValue: (String) -> Unit, enabled: Boolean, placeholder: String, onSend: () -> Unit) {
    Row(verticalAlignment = Alignment.Bottom, modifier = Modifier.fillMaxWidth()) {
        OutlinedTextField(
            value = value,
            onValueChange = onValue,
            modifier = Modifier.weight(1f).heightIn(min = 52.dp),
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
                .clickable(enabled = canSend, onClick = onSend),
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
                    color = if (step.status == StepStatus.PENDING) KalivTheme.colors.TextMuted else KalivTheme.colors.TextHigh,
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
                ApprovalCard(card = card, onApprove = onApprove, onDeny = onDeny)
            }
        }
    }
}

@Composable
private fun StatusCircle(index: Int, status: StepStatus) {
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
    }
}

/**
 * The inline approval card (handoff: radius 14, gradient #241A10→#1B140D, 1dp
 * rgba(198,154,75,.45)). Ankh + title + WRITE badge, arg-preview box, and the
 * 50/50 Godkend/Afvis buttons. The gate is in the worker; this only renders.
 */
@Composable
internal fun ApprovalCard(card: ToolTurn, onApprove: () -> Unit, onDeny: () -> Unit) {
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
            RiskBadge(riskOf("", card.tool))
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
                    .clickable(onClick = onApprove)
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) { Text("Godkend", color = kalivPrimaryInk, fontSize = 13.sp, fontWeight = FontWeight.SemiBold) }
            Spacer(Modifier.width(10.dp))
            // Afvis (outline)
            Box(
                Modifier.weight(1f).clip(RoundedCornerShape(10.dp))
                    .background(KalivTheme.colors.SurfaceHigh)
                    .border(1.dp, Color(0x4D785A37), RoundedCornerShape(10.dp))
                    .clickable(onClick = onDeny)
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
// 1c -- Computer-use split: task/step list + live viewport + pause/stop
// ===========================================================================

enum class RunState { IDLE, RUNNING, PAUSED, STOPPED, DONE }

/** A computer-use step (mirrors the plan step but with a plain label). */
data class UseStep(val label: String, val detail: String, val status: StepStatus)

/**
 * The 1c computer-use screen. Two columns: left (340dp) task + step timeline +
 * pause/stop control bar; right live viewport (mock browser + light page +
 * work overlay) with an approval bar before each write.
 *
 * Per the handoff: the viewport is HIDDEN until a task runs (no fake page
 * behind a scrim). The "Kaliv styrer skærmen" status only shows while running.
 *
 * NOTE (honest scope): live browser frames come from the worker's browser_use
 * adapter in production. This client renders the viewport chrome, the step
 * timeline, and the approval gate; the sample page is illustrative of the
 * annotation layer (focus ring + cursor + overlay) until wired to real frames.
 */
@Composable
fun KalivComputerUse(
    baseUrl: String,
    bearer: String?,
    model: String,
    system: String?,
    modifier: Modifier = Modifier,
) {
    var input by remember { mutableStateOf("") }
    var runState by remember { mutableStateOf(RunState.IDLE) }
    var taskText by remember { mutableStateOf("") }
    val steps = remember { mutableStateListOf<UseStep>() }
    var pendingAction by remember { mutableStateOf<String?>(null) }

    fun startTask() {
        val t = input.trim()
        if (t.isEmpty()) return
        taskText = t
        input = ""
        runState = RunState.RUNNING
        // Seed an illustrative plan; in production these arrive from the worker.
        steps.clear()
        steps.addAll(
            listOf(
                UseStep("\u00c5bnede browser", "lokal \u00b7 browser_use", StepStatus.DONE),
                UseStep("S\u00f8gte & fandt \u00e5bningstider", "l\u00f8: 10\u201317", StepStatus.DONE),
                UseStep("Opretter kalenderbegivenhed", "afventer din godkendelse", StepStatus.ACTIVE),
                UseStep("Bekr\u00e6fter & lukker", "", StepStatus.PENDING),
            ),
        )
        pendingAction = "Genbrugsplads \u00b7 l\u00f8r 26. jul \u00b7 10:00\u201317:00 \u00b7 kalender: Privat"
    }

    fun stopTask() {
        runState = RunState.STOPPED
        pendingAction = null
    }

    fun resetTask() {
        runState = RunState.IDLE
        steps.clear()
        taskText = ""
        pendingAction = null
    }

    Row(modifier.fillMaxSize()) {
        // --- Left column (340dp) ---
        Column(
            Modifier.width(340.dp).fillMaxHeight()
                .background(Color(0x8014110E))
                .padding(18.dp),
        ) {
            // "Kaliv styrer skærmen" status only while running.
            if (runState == RunState.RUNNING) {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 12.dp)) {
                    Box(Modifier.size(7.dp).clip(RoundedCornerShape(999.dp)).background(KalivTheme.colors.Warning))
                    Spacer(Modifier.width(7.dp))
                    Text("Kaliv styrer sk\u00e6rmen", color = KalivTheme.colors.Warning, fontSize = 11.5.sp, fontWeight = FontWeight.Medium)
                }
            }
            Text("Opgave", color = KalivTheme.colors.TextHigh, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            if (runState == RunState.IDLE) {
                Text(
                    "Beskriv en computer-opgave. Kaliv styrer en browser og stopper ved hver skrivning for din godkendelse.",
                    color = KalivTheme.colors.TextMuted, fontSize = 12.5.sp, lineHeight = 19.sp,
                )
                Spacer(Modifier.height(14.dp))
                AgentComposer(
                    value = input, onValue = { input = it }, enabled = true,
                    placeholder = "Ny computer-opgave \u2026", onSend = { startTask() },
                )
            } else {
                Text(taskText, color = KalivTheme.colors.TextMuted, fontSize = 12.5.sp, lineHeight = 19.sp)
                Spacer(Modifier.height(16.dp))
                SectionLabel("Trin")
                Spacer(Modifier.height(10.dp))
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                    steps.forEachIndexed { i, s ->
                        UseStepRow(index = i + 1, step = s, isLast = i == steps.lastIndex)
                    }
                }
                // Control bar (Pause / Stop) or a finished/stopped result.
                when (runState) {
                    RunState.STOPPED -> ResultBar(false, "Stoppet \u2014 intet \u00e6ndret", onReset = { resetTask() })
                    RunState.DONE -> ResultBar(true, "Fuldf\u00f8rt", onReset = { resetTask() })
                    else -> {
                        Row(Modifier.fillMaxWidth().padding(top = 8.dp)) {
                            OutlineChip(
                                if (runState == RunState.PAUSED) "\u25B6 Forts\u00e6t" else "\u23F8 Pause",
                                onClick = { runState = if (runState == RunState.PAUSED) RunState.RUNNING else RunState.PAUSED },
                                modifier = Modifier.weight(1f),
                            )
                            Spacer(Modifier.width(10.dp))
                            Box(
                                Modifier.weight(1f).clip(RoundedCornerShape(9.dp))
                                    .background(Color(0x269C564C))
                                    .border(1.dp, Color(0x809C564C), RoundedCornerShape(9.dp))
                                    .clickable { stopTask() }
                                    .padding(vertical = 9.dp),
                                contentAlignment = Alignment.Center,
                            ) { Text("\u25A0 Stop", color = Color(0xFFE0B3AB), fontSize = 12.5.sp, fontWeight = FontWeight.Medium) }
                        }
                    }
                }
            }
        }

        // --- Right column: live viewport (flex) ---
        Column(
            Modifier.weight(1f).fillMaxHeight()
                .background(KalivTheme.colors.Graphite)
                .padding(horizontal = 18.dp, vertical = 16.dp),
        ) {
            if (runState == RunState.IDLE) {
                // Clean waiting state -- viewport hidden until a task runs.
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        KalivAnkh(40)
                        Spacer(Modifier.height(14.dp))
                        Text("Ingen aktiv computer-opgave", color = KalivTheme.colors.TextMuted, fontSize = 13.sp)
                        Text("Start en opgave for at se Kaliv arbejde live.", color = KalivTheme.colors.TextMuted, fontSize = 11.5.sp)
                    }
                }
            } else {
                LiveViewport(Modifier.weight(1f))
                pendingAction?.let { detail ->
                    Spacer(Modifier.height(14.dp))
                    ComputerApprovalBar(
                        detail = detail,
                        onApprove = {
                            // Approve -> mark active step done, advance to finish.
                            val idx = steps.indexOfFirst { it.status == StepStatus.ACTIVE }
                            if (idx >= 0) steps[idx] = steps[idx].copy(status = StepStatus.DONE, detail = "oprettet")
                            if (idx + 1 <= steps.lastIndex) steps[idx + 1] = steps[idx + 1].copy(status = StepStatus.DONE, detail = "lukket")
                            pendingAction = null
                            runState = RunState.DONE
                        },
                        onDeny = {
                            val idx = steps.indexOfFirst { it.status == StepStatus.ACTIVE }
                            if (idx >= 0) steps[idx] = steps[idx].copy(status = StepStatus.DONE, detail = "afvist \u2014 intet \u00e6ndret")
                            pendingAction = null
                            runState = RunState.STOPPED
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun UseStepRow(index: Int, step: UseStep, isLast: Boolean) {
    Row(Modifier.fillMaxWidth()) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(22.dp)) {
            StatusCircleSmall(index, step.status)
            if (!isLast) Box(Modifier.width(2.dp).height(34.dp).background(Color(0x4D785A37)))
        }
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f).padding(bottom = 12.dp)) {
            Text(
                step.label,
                color = if (step.status == StepStatus.PENDING) KalivTheme.colors.TextMuted else KalivTheme.colors.TextHigh,
                fontSize = 13.sp, fontWeight = FontWeight.Medium,
            )
            if (step.detail.isNotBlank()) {
                Text(step.detail, color = KalivTheme.colors.TextMuted, fontSize = 11.5.sp)
            }
        }
    }
}

@Composable
private fun StatusCircleSmall(index: Int, status: StepStatus) {
    when (status) {
        StepStatus.DONE -> Box(
            Modifier.size(22.dp).clip(RoundedCornerShape(999.dp)).background(Color(0x336F8A63))
                .border(1.dp, KalivTheme.colors.Success, RoundedCornerShape(999.dp)),
            contentAlignment = Alignment.Center,
        ) { Text("\u2713", color = KalivTheme.colors.Success, fontSize = 11.sp) }
        StepStatus.ACTIVE -> Box(
            Modifier.size(22.dp).clip(RoundedCornerShape(999.dp)).background(Color(0xFF8A6530))
                .border(3.dp, Color(0x2E9A7136), RoundedCornerShape(999.dp)),
            contentAlignment = Alignment.Center,
        ) { Box(Modifier.size(6.dp).clip(RoundedCornerShape(999.dp)).background(kalivPrimaryInk)) }
        StepStatus.PENDING -> Box(
            Modifier.size(22.dp).clip(RoundedCornerShape(999.dp)).background(KalivTheme.colors.SurfaceHigh)
                .border(1.dp, Color(0x4D785A37), RoundedCornerShape(999.dp)),
            contentAlignment = Alignment.Center,
        ) { Text("$index", color = KalivTheme.colors.TextMuted, fontSize = 11.sp) }
    }
}

/**
 * The live viewport: a mock browser (light chrome + traffic lights + URL pill)
 * over a light page, with the Saturday row highlighted (bronze focus ring),
 * a Kaliv cursor, and a bottom work-overlay. Illustrates the annotation layer.
 */
@Composable
private fun LiveViewport(modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(13.dp)
    Box(
        modifier.fillMaxWidth().clip(shape)
            .background(Color(0xFFFBF9F5))
            .border(1.dp, Color(0x66C69A4B), shape),
    ) {
        Column(Modifier.fillMaxSize()) {
            // Browser chrome (light)
            Row(
                Modifier.fillMaxWidth().height(44.dp).background(Color(0xFFEDE8E0)).padding(horizontal = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.size(11.dp).clip(RoundedCornerShape(999.dp)).background(Color(0xFFE06C5A)))
                Spacer(Modifier.width(7.dp))
                Box(Modifier.size(11.dp).clip(RoundedCornerShape(999.dp)).background(Color(0xFFE0B33A)))
                Spacer(Modifier.width(7.dp))
                Box(Modifier.size(11.dp).clip(RoundedCornerShape(999.dp)).background(Color(0xFF6FA05A)))
                Spacer(Modifier.width(16.dp))
                Box(
                    Modifier.weight(1f).clip(RoundedCornerShape(999.dp)).background(Color(0xFFFFFFFF))
                        .border(1.dp, Color(0xFFD7CFC2), RoundedCornerShape(999.dp))
                        .padding(horizontal = 12.dp, vertical = 6.dp),
                ) {
                    Text("\uD83D\uDD12 kommune.dk/genbrugsplads/aabningstider", color = Color(0xFF6B6257), fontSize = 11.sp, maxLines = 1)
                }
            }
            // Light page content
            Column(Modifier.fillMaxSize().padding(22.dp)) {
                Text("\u00c5bningstider \u2014 Genbrugsplads Nord", color = Color(0xFF231E19), fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(16.dp))
                HoursRow("Mandag\u2013fredag", "07\u201318", highlighted = false)
                HoursRow("L\u00f8rdag", "10\u201317", highlighted = true)
                HoursRow("S\u00f8ndag", "Lukket", highlighted = false)
            }
        }
        // Work overlay (bottom gradient fade)
        Box(
            Modifier.fillMaxWidth().height(52.dp).align(Alignment.BottomCenter)
                .background(Brush.verticalGradient(listOf(Color(0x00000000), Color(0xCC0B0A09))))
                .padding(horizontal = 16.dp, vertical = 10.dp),
            contentAlignment = Alignment.CenterStart,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(7.dp).clip(RoundedCornerShape(999.dp)).background(KalivTheme.colors.Warning))
                Spacer(Modifier.width(8.dp))
                Text("Kaliv l\u00e6ser siden \u2014 udtr\u00e6kker l\u00f8rdagens \u00e5bningstid", color = Color(0xFFF3EFE6), fontSize = 11.5.sp)
                Spacer(Modifier.weight(1f))
                Text("trin 2/4", color = Color(0xFFA89D90), fontSize = 10.5.sp, fontFamily = FontFamily.Monospace)
            }
        }
    }
}

@Composable
private fun HoursRow(day: String, hours: String, highlighted: Boolean) {
    val mod = if (highlighted) {
        Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
            .border(2.dp, Color(0xFFC69A4B), RoundedCornerShape(8.dp))
            .background(Color(0x14C69A4B))
            .padding(horizontal = 12.dp, vertical = 9.dp)
    } else {
        Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 9.dp)
    }
    Row(mod, verticalAlignment = Alignment.CenterVertically) {
        Text(day, color = Color(0xFF3A342C), fontSize = 13.sp, modifier = Modifier.weight(1f))
        Text(hours, color = Color(0xFF231E19), fontSize = 13.sp, fontWeight = if (highlighted) FontWeight.SemiBold else FontWeight.Normal)
    }
}

/** Approval bar for computer-use (same gradient/border as the 1b card). */
@Composable
private fun ComputerApprovalBar(detail: String, onApprove: () -> Unit, onDeny: () -> Unit) {
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
            Text("Kaliv vil oprette en kalenderbegivenhed", color = KalivTheme.colors.TextHigh, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.weight(1f))
            RiskBadge(RiskLevel.WRITE)
        }
        Spacer(Modifier.height(8.dp))
        Text(detail, color = KalivTheme.colors.TextMuted, fontSize = 12.sp, lineHeight = 17.sp)
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth()) {
            Box(
                Modifier.weight(1f).clip(RoundedCornerShape(10.dp)).background(kalivPrimaryGradient)
                    .clickable(onClick = onApprove).padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) { Text("Godkend", color = kalivPrimaryInk, fontSize = 13.sp, fontWeight = FontWeight.SemiBold) }
            Spacer(Modifier.width(10.dp))
            Box(
                Modifier.weight(1f).clip(RoundedCornerShape(10.dp)).background(KalivTheme.colors.SurfaceHigh)
                    .border(1.dp, Color(0x4D785A37), RoundedCornerShape(10.dp))
                    .clickable(onClick = onDeny).padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) { Text("Afvis", color = KalivTheme.colors.TextHigh, fontSize = 13.sp, fontWeight = FontWeight.Medium) }
        }
    }
}

@Composable
private fun ResultBar(success: Boolean, label: String, onReset: () -> Unit) {
    val shape = RoundedCornerShape(11.dp)
    val (bg, border, fg) = if (success)
        Triple(Color(0x266F8A63), Color(0x806F8A63), KalivTheme.colors.Success)
    else
        Triple(Color(0x269C564C), Color(0x809C564C), Color(0xFFE0B3AB))
    Column(Modifier.fillMaxWidth().padding(top = 8.dp)) {
        Row(
            Modifier.fillMaxWidth().clip(shape).background(bg).border(1.dp, border, shape).padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(if (success) "\u2713" else "\u25A0", color = fg, fontSize = 14.sp)
            Spacer(Modifier.width(9.dp))
            Text(label, color = fg, fontSize = 13.sp, fontWeight = FontWeight.Medium)
        }
        Spacer(Modifier.height(8.dp))
        OutlineChip("Ny opgave", onClick = onReset, modifier = Modifier.fillMaxWidth())
    }
}
