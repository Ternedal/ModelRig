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
 * Skaerm 13 (rig offline) — banner-kortet, 1:1 mod HTML-referencen x393/322
 * jf. DDR-001/B2. Statsloest; ChatScreen ejer liveness-driveren (ping-loekke
 * m. auto-retry) og valgene. Designprincip fra referencen: klar besked,
 * auto-retry, cloud som EKSPLICIT valg — aldrig stille fallback.
 * Knap-ink paa guld er Gold.on jf. DDR-001 (referencen viser creme).
 */
@Composable
fun RigOfflineBanner(
    lastSeenLabel: String?,
    showCloudSwitch: Boolean,
    retryBusy: Boolean,
    onRetry: () -> Unit,
    onSwitchCloud: () -> Unit,
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
                    painterResource(R.drawable.ic_kaliv_rig_off),
                    contentDescription = null,
                    tint = KalivTheme.colors.warn,
                    modifier = Modifier.size(20.dp),
                )
            }
            Spacer(Modifier.width(13.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    "Din rig svarer ikke",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
                    color = KalivTheme.colors.textHigh,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    buildString {
                        lastSeenLabel?.let { append("Sidst set $it \u00b7 ") }
                        append("skifter aldrig selv til cloud")
                    },
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
                    .clickable(enabled = !retryBusy, onClickLabel = "Pr\u00f8v nu") { onRetry() }
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (retryBusy) "Pr\u00f8ver \u2026" else "Pr\u00f8v nu",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTokens.Gold.on,
                )
            }
            if (showCloudSwitch) {
                Box(
                    Modifier
                        .weight(1f)
                        .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(12.dp))
                        .clickable(onClickLabel = "Skift til cloud") { onSwitchCloud() }
                        .padding(vertical = 11.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        "Skift til cloud",
                        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                        color = KalivTheme.colors.textSoft,
                    )
                }
            }
        }
    }
}
