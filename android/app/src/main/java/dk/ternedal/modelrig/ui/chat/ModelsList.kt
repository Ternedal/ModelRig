package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Skaerm 10 (Modeller) — 1:1 mod HTML-referencen, x393/322 jf. DDR-001/B2.
 * Statsloest; ModelsScreen ejer tilstand, pull-stroem og slet-dialog.
 * Aerlige afvigelser: VRAM-linjen viser "i brug" (sum af /models/running) —
 * "fri" kraever total-VRAM fra B3a-endpointet (fase 4). STANDARD-badgen er
 * chat-modellens valg (store.model) og kan saettes via langtryks-menuen.
 */
data class InstalledModelUi(
    val name: String,
    val standard: Boolean,
    val loaded: Boolean,
    val metaLabel: String,
)

@Composable
fun ModelsVramLine(text: String, onReload: () -> Unit, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth().padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(
            painterResource(R.drawable.ic_kaliv_rig),
            contentDescription = null,
            tint = KalivTheme.colors.textMuted,
            modifier = Modifier.size(18.dp),
        )
        Spacer(Modifier.width(9.dp))
        Text(
            text,
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.sp),
            color = KalivTheme.colors.textMuted,
            modifier = Modifier.weight(1f),
        )
        Row(
            Modifier.combinedClickable(onClick = onReload),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                painterResource(R.drawable.ic_kaliv_retry),
                contentDescription = "Genindl\u00e6s",
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
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun InstalledModelCard(m: InstalledModelUi, onLongPress: () -> Unit, modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Row(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .combinedClickable(onClick = {}, onLongClick = onLongPress)
            .padding(15.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    m.name,
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.5.sp),
                    color = KalivTheme.colors.textHigh,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (m.standard) {
                    Spacer(Modifier.width(9.dp))
                    Text(
                        "STANDARD",
                        style = TextStyle(
                            fontFamily = KalivType.Inter,
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 11.5.sp,
                            letterSpacing = 0.06.em,
                        ),
                        color = KalivTheme.colors.accent,
                        modifier = Modifier
                            .background(KalivTheme.colors.goldTint, RoundedCornerShape(KalivTokens.Radius.round))
                            .padding(horizontal = 10.dp, vertical = 3.dp),
                    )
                }
            }
            Spacer(Modifier.height(4.dp))
            Text(
                m.metaLabel,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                color = KalivTheme.colors.faint,
            )
        }
        Spacer(Modifier.width(13.dp))
        if (m.loaded) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(7.dp).background(KalivTheme.colors.success, CircleShape))
                Spacer(Modifier.width(6.dp))
                Text(
                    "Indl\u00e6st",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                    color = KalivTheme.colors.success,
                )
            }
        } else {
            Text(
                "Klar",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                color = KalivTheme.colors.faint,
            )
        }
    }
}

/** Aktiv hentning som mockuppens gemma2-raekke: navn, fremdriftstekst, pct og guldbar. */
@Composable
fun PullProgressCard(name: String, progressText: String, fraction: Float, modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(15.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    name,
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.5.sp),
                    color = KalivTheme.colors.textHigh,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    progressText,
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                    color = KalivTheme.colors.faint,
                )
            }
            Text(
                "${(fraction * 100).toInt()} %",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.sp),
                color = KalivTheme.colors.accent,
            )
        }
        Spacer(Modifier.height(13.dp))
        Box(
            Modifier.fillMaxWidth().height(5.dp)
                .background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(3.dp)),
        ) {
            Box(
                Modifier.fillMaxWidth(fraction.coerceIn(0f, 1f)).height(5.dp)
                    .background(KalivTokens.Gold.fill, RoundedCornerShape(3.dp)),
            )
        }
    }
}
