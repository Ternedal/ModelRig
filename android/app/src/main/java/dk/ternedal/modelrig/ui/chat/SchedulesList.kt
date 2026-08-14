package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.components.KalivSwitch
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Scheduler-skaermen — 1:1 mod handoff v2's Scheduler-celle, x393/322 jf.
 * DDR-001/B2. Statsloest; ScheduleScreen ejer preview->godkendelse->koersel-
 * flowet uaendret. Dokumenterede afvigelser: korttitlen er tool-navnet
 * (planer har intet menneskenavn i API'et — kravspec-punkt); godkendt-linjen
 * er uden dato (feltet findes ikke); "Lad udloebe" er en LOKAL afvisning af
 * fremhaevningen (der findes bevidst ingen slet-API — udloeb sker af sig
 * selv); knap-ink paa guld er Gold.on jf. DDR-001.
 */
data class ScheduleCardUi(
    val id: String,
    val title: String,
    val sub: String,
    val nextLabel: String?,
    val pausedLine: String?,
    val runsLabel: String,
    val expiresLabel: String,
    val expiresBadge: String?,
    val approvedLine: String?,
    val blockedLine: String?,
    val enabled: Boolean,
)

/** Udloebs-varianten: fremhaevet kort m. badge, godkendt-linje og handlinger. */
@Composable
fun ExpiringScheduleCard(
    ui: ScheduleCardUi,
    busy: Boolean,
    onRenew: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 16.dp, vertical = 15.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                ui.title,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
                color = KalivTheme.colors.textHigh,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            ui.expiresBadge?.let {
                Spacer(Modifier.width(10.dp))
                Text(
                    it,
                    style = TextStyle(
                        fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold,
                        fontSize = 11.sp, letterSpacing = 0.08.em,
                    ),
                    color = KalivTheme.colors.warn,
                    modifier = Modifier
                        .background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(KalivTokens.Radius.round))
                        .padding(horizontal = 10.dp, vertical = 4.dp),
                )
            }
        }
        Spacer(Modifier.height(3.dp))
        Text(
            ui.sub,
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
            color = KalivTheme.colors.textMuted,
        )
        ui.approvedLine?.let {
            Spacer(Modifier.height(7.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    painterResource(R.drawable.ic_kaliv_check),
                    contentDescription = null,
                    tint = KalivTheme.colors.success,
                    modifier = Modifier.size(13.dp),
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    it,
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 12.sp),
                    color = KalivTheme.colors.faint,
                )
            }
        }
        ui.blockedLine?.let {
            Spacer(Modifier.height(6.dp))
            Text(it, style = TextStyle(fontFamily = KalivType.Inter, fontSize = 12.5.sp), color = KalivTheme.colors.danger)
        }
        Spacer(Modifier.height(13.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(
                Modifier
                    .weight(1f)
                    .background(KalivTokens.Gold.fill, RoundedCornerShape(12.dp))
                    .clickable(enabled = !busy, onClickLabel = "Forny (preview)") { onRenew() }
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "Forny (preview)",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTokens.Gold.on,
                )
            }
            Box(
                Modifier
                    .weight(1f)
                    .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(12.dp))
                    .clickable(onClickLabel = "Lad udl\u00f8be") { onDismiss() }
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "Lad udl\u00f8be",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTheme.colors.textMuted,
                )
            }
        }
    }
}

/** Normalkortet: klok-brik, kontakt (pause/genoptag), koersler/udloeb-raekken. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun NormalScheduleCard(
    ui: ScheduleCardUi,
    busy: Boolean,
    expanded: Boolean,
    onToggle: (Boolean) -> Unit,
    onClick: () -> Unit,
    onLongPress: () -> Unit,
    modifier: Modifier = Modifier,
    detailContent: (@Composable () -> Unit)? = null,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .combinedClickable(onClick = onClick, onLongClick = onLongPress)
            .padding(horizontal = 16.dp, vertical = 15.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(41.dp).background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(11.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    painterResource(R.drawable.ic_kaliv_clock),
                    contentDescription = null,
                    tint = if (ui.enabled) KalivTheme.colors.accent else KalivTheme.colors.textMuted,
                    modifier = Modifier.size(20.dp),
                )
            }
            Spacer(Modifier.width(13.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    ui.title,
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
                    color = KalivTheme.colors.textHigh,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    ui.sub,
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                    color = KalivTheme.colors.textMuted,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                val line = ui.pausedLine ?: ui.nextLabel
                line?.let {
                    Spacer(Modifier.height(3.dp))
                    Text(
                        it,
                        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                        color = if (ui.pausedLine != null) KalivTheme.colors.faint else KalivTheme.colors.accent,
                    )
                }
            }
            Spacer(Modifier.width(12.dp))
            KalivSwitch(checked = ui.enabled, onCheckedChange = { if (!busy) onToggle(it) })
        }
        ui.blockedLine?.let {
            Spacer(Modifier.height(6.dp))
            Text(it, style = TextStyle(fontFamily = KalivType.Inter, fontSize = 12.5.sp), color = KalivTheme.colors.danger)
        }
        Spacer(Modifier.height(10.dp))
        HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(15.dp)) {
            StatPair("K\u00f8rsler", ui.runsLabel)
            StatPair("Udl\u00f8ber", ui.expiresLabel)
        }
        if (expanded && detailContent != null) {
            Spacer(Modifier.height(10.dp))
            HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)
            Spacer(Modifier.height(9.dp))
            detailContent()
        }
    }
}

@Composable
private fun StatPair(label: String, value: String) {
    Text(
        buildAnnotatedString {
            withStyle(SpanStyle(color = KalivTheme.colors.caps)) { append("$label ") }
            withStyle(SpanStyle(color = KalivTheme.colors.textMuted, fontWeight = FontWeight.SemiBold)) { append(value) }
        },
        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 12.sp),
    )
}

/** Bundens driftskort: koerer/ikke + aktive + Genindlaes-link. */
@Composable
fun SchedulesFooterStatus(
    statusText: String,
    ok: Boolean,
    errorText: String?,
    onReload: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 16.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(8.dp).background(
                    if (ok) KalivTheme.colors.success else KalivTheme.colors.warn,
                    RoundedCornerShape(KalivTokens.Radius.round),
                ),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                statusText,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 14.sp),
                color = KalivTheme.colors.textMuted,
                modifier = Modifier.weight(1f),
            )
            Row(
                Modifier.clickable(onClickLabel = "Genindl\u00e6s") { onReload() },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    painterResource(R.drawable.ic_kaliv_retry),
                    contentDescription = null,
                    tint = KalivTheme.colors.accent,
                    modifier = Modifier.size(15.dp),
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    "Genindl\u00e6s",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 13.5.sp),
                    color = KalivTheme.colors.accent,
                )
            }
        }
        errorText?.let {
            Spacer(Modifier.height(5.dp))
            Text(it, style = TextStyle(fontFamily = KalivType.Inter, fontSize = 12.5.sp), color = KalivTheme.colors.danger)
        }
    }
}
