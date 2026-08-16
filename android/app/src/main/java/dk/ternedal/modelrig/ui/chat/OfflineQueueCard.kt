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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.OfflineQueue
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Køen af beskeder skrevet mens riggen var væk.
 *
 * KORTET ER ET TILBUD, IKKE EN AFSENDELSE. Kaliv sender aldrig en kø-besked af
 * sig selv, når riggen kommer tilbage — måske skrev du den for tre timer siden
 * om noget du siden har løst. Derfor står tidspunktet på hver besked, og der
 * skal trykkes for hver enkelt.
 */
@Composable
fun OfflineQueueCard(
    items: List<OfflineQueue.Item>,
    nowMillis: Long,
    rigBack: Boolean,
    onSend: (OfflineQueue.Item) -> Unit,
    onEdit: (OfflineQueue.Item) -> Unit,
    onDiscard: (OfflineQueue.Item) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (items.isEmpty()) return
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 15.dp, vertical = 13.dp),
    ) {
        Text(
            if (items.size == 1) "1 besked i kø" else "${items.size} beskeder i kø",
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 15.sp),
            color = KalivTheme.colors.textHigh,
        )
        Spacer(Modifier.height(3.dp))
        Text(
            if (rigBack) {
                "Riggen er tilbage. Kaliv sender dem ikke af sig selv — tjek om de stadig gælder."
            } else {
                "De venter, til riggen er tilbage. Intet sendes af sig selv."
            },
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.sp, lineHeight = 19.sp),
            color = KalivTheme.colors.textMuted,
        )
        Spacer(Modifier.height(11.dp))
        items.forEach { item ->
            Column(Modifier.fillMaxWidth().padding(bottom = 11.dp)) {
                Text(
                    item.text,
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.5.sp, lineHeight = 21.sp),
                    color = KalivTheme.colors.textHigh,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(3.dp))
                Text(
                    OfflineQueue.writtenLabel(item.atMillis, nowMillis),
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 12.5.sp),
                    color = KalivTheme.colors.textMuted,
                )
                Spacer(Modifier.height(9.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                    QueueAction(
                        label = "Send nu",
                        enabled = rigBack,
                        primary = true,
                        modifier = Modifier.weight(1f),
                    ) { onSend(item) }
                    QueueAction(label = "Rediger", enabled = true, primary = false, modifier = Modifier.weight(1f)) {
                        onEdit(item)
                    }
                    QueueAction(label = "Kassér", enabled = true, primary = false, modifier = Modifier.weight(1f)) {
                        onDiscard(item)
                    }
                }
            }
        }
    }
}

@Composable
private fun QueueAction(
    label: String,
    enabled: Boolean,
    primary: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(11.dp)
    Box(
        modifier
            .then(
                if (primary && enabled) {
                    Modifier.background(KalivTheme.colors.signal, shape)
                } else {
                    Modifier.border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
                },
            )
            .clickable(enabled = enabled, onClickLabel = label) { onClick() }
            .padding(vertical = 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 13.5.sp),
            color = when {
                primary && enabled -> KalivTheme.colors.onSignal
                enabled -> KalivTheme.colors.textHigh
                else -> KalivTheme.colors.textMuted
            },
        )
    }
}
