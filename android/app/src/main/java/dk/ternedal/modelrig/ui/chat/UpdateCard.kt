package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * In-app-opdateringskortet. Ingen mockup findes (skaermen er ikke i
 * kontaktarket) — tegnet i redesignets sprog som OfflineBanner-tvillingen:
 * surfaceDim + hairline + ikon-brik (accent i stedet for warn), guldknap +
 * outline-knap, Gold.on-ink jf. DDR-001.
 */
@Composable
fun UpdateCard(
    newVersion: String,
    currentVersion: String,
    downloading: Boolean,
    progressPct: Int,
    onInstall: () -> Unit,
    onLater: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(15.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(39.dp).background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(11.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    painterResource(R.drawable.ic_kaliv_download),
                    contentDescription = null,
                    tint = KalivTheme.colors.accent,
                    modifier = Modifier.size(20.dp),
                )
            }
            Spacer(Modifier.width(13.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    "Kaliv $newVersion er klar",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
                    color = KalivTheme.colors.textHigh,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    "Du k\u00f8rer $currentVersion \u00b7 hentes fra GitHub-releasen",
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                    color = KalivTheme.colors.textMuted,
                )
            }
        }
        Spacer(Modifier.height(13.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(
                Modifier
                    .weight(1f)
                    .background(KalivTokens.Gold.fill, RoundedCornerShape(12.dp))
                    .clickable(enabled = !downloading, onClickLabel = "Hent og install\u00e9r") { onInstall() }
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (downloading) "Henter \u2026 $progressPct %" else "Hent og install\u00e9r",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTokens.Gold.on,
                )
            }
            if (!downloading) {
                Box(
                    Modifier
                        .weight(1f)
                        .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(12.dp))
                        .clickable(onClickLabel = "Senere") { onLater() }
                        .padding(vertical = 11.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        "Senere",
                        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                        color = KalivTheme.colors.textSoft,
                    )
                }
            }
        }
    }
}
