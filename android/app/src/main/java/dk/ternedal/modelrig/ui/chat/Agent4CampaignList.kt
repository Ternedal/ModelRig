package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Agent 4 · kampagner (skærm 26) — 1:1 mod referencen, ×1,2205.
 * Statsløst; Agent4OperatorScreen ejer hentning, paging og navigation.
 *
 * Kortet er SKRIVEBESKYTTET som fladen selv: der findes kun read-ruter
 * (ADR-A4-007), så intet her kan starte, pause eller annullere noget.
 *
 * Dokumenterede afvigelser: mockuppens under-linjer fortæller HVORFOR en
 * kampagne venter ("optaget af kørende kampagne", "ressource-lease aktiv").
 * Den årsag rapporterer riggen ikke — vi viser i stedet det vi VED:
 * status, og for fejlede kampagner om retry-budgettet er brugt op
 * (attempt >= maxAttempts, begge målte tal) eller rigens egen last_error.
 */
/**
 * Afkorter en timeline-hash som referencen: fire foran, fire bagpå.
 * Formateringen bor HER hos kortet — ikke i Agent4OperatorScreen, hvis
 * paging-sti holdes fri for take/drop-konstruktioner af A4-gaten.
 */
fun shortCampaignHash(raw: String): String {
    val h = raw.substringAfter(':', raw).trim()
    if (h.length <= 12) return h
    return h.substring(0, 4) + "\u2026" + h.substring(h.length - 4)
}

enum class Agent4StatusKind { Running, Waiting, Failed, Done }

data class Agent4CampaignCardUi(
    val id: String,
    val name: String,
    val statusLabel: String,
    val statusKind: Agent4StatusKind,
    val subLine: String,
    val timelineCount: Int,
    val evidenceCount: Int,
    val attemptLabel: String,
)

@Composable
fun Agent4StatusBadge(label: String, kind: Agent4StatusKind, modifier: Modifier = Modifier) {
    val fg = when (kind) {
        Agent4StatusKind.Running -> KalivTheme.colors.accent
        Agent4StatusKind.Waiting -> KalivTheme.colors.textMuted
        Agent4StatusKind.Failed -> KalivTheme.colors.danger
        Agent4StatusKind.Done -> KalivTheme.colors.success
    }
    val bg = if (kind == Agent4StatusKind.Running) KalivTokens.Gold.tint else KalivTheme.colors.surfaceHigh
    Text(
        label,
        style = TextStyle(
            fontFamily = KalivType.Inter,
            fontWeight = FontWeight.SemiBold,
            fontSize = 11.sp,
            letterSpacing = 0.08.em,
        ),
        color = fg,
        modifier = modifier
            .background(bg, RoundedCornerShape(KalivTokens.Radius.round))
            .padding(horizontal = 10.dp, vertical = 4.dp),
    )
}

@Composable
fun Agent4CampaignCard(
    ui: Agent4CampaignCardUi,
    onOpen: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .clickable(onClickLabel = "Åbn kampagne") { onOpen() }
            .padding(horizontal = 16.dp, vertical = 15.dp),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                ui.name,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
                color = KalivTheme.colors.textHigh,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(10.dp))
            Agent4StatusBadge(ui.statusLabel, ui.statusKind)
        }
        Spacer(Modifier.height(5.dp))
        Text(
            ui.subLine,
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
            color = KalivTheme.colors.textMuted,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Spacer(Modifier.height(10.dp))
        HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(15.dp)) {
            Agent4Stat("Timeline", ui.timelineCount.toString())
            Agent4Stat("Evidens", ui.evidenceCount.toString())
            Agent4Stat("Forsøg", ui.attemptLabel)
        }
    }
}

@Composable
private fun Agent4Stat(label: String, value: String) {
    Text(
        buildAnnotatedString {
            withStyle(SpanStyle(color = KalivTheme.colors.caps)) { append("$label ") }
            withStyle(SpanStyle(color = KalivTheme.colors.textMuted, fontWeight = FontWeight.SemiBold)) { append(value) }
        },
        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 12.sp),
    )
}

/**
 * Fodnoten: seneste timeline-hash (afkortet som i referencen) og den
 * SANDE arkitektur-invariant fra ADR-A4-008 — efter en genstart antages
 * intet at køre; genoptagelse er caller-driven, aldrig automatisk.
 */
@Composable
fun Agent4FooterFacts(
    latestHashShort: String?,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 15.dp, vertical = 12.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(
                "Seneste timeline-hash",
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                color = KalivTheme.colors.textMuted,
            )
            Text(
                latestHashShort ?: "ingen endnu",
                style = TextStyle(fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                color = KalivTheme.colors.textSoft,
            )
        }
        Spacer(Modifier.height(6.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(
                "Efter genstart",
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                color = KalivTheme.colors.textMuted,
            )
            Text(
                "Intet antages kørende",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.5.sp),
                color = KalivTheme.colors.textSoft,
            )
        }
    }
}
