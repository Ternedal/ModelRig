package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * "Del til Kaliv" — kortet en deling lander i.
 *
 * Delingen GØR ingenting af sig selv. Den viser hvad der kom ind, og lader
 * mennesket vælge: spørg om det, eller gem det i Viden. Automatisk
 * indeksering ville lægge en andens dokument i din viden, fordi du kom til
 * at trykke Del i en anden app.
 *
 * Er der ingen rig parret, kan kun chat-vejen bruges — og så siger kortet
 * hvorfor frem for at vise en knap der ikke virker.
 */
@Composable
fun ShareLandingCard(
    title: String,
    preview: String,
    isDocument: Boolean,
    truncated: Boolean,
    rigAvailable: Boolean,
    busy: Boolean,
    onAsk: () -> Unit,
    onSaveToKnowledge: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 15.dp, vertical = 13.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                painterResource(if (isDocument) R.drawable.ic_kaliv_doc else R.drawable.ic_kaliv_copy),
                contentDescription = null,
                tint = KalivTheme.colors.accent,
                modifier = Modifier.size(15.dp),
            )
            Spacer(Modifier.width(9.dp))
            Text(
                "Delt til Kaliv",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 15.sp),
                color = KalivTheme.colors.textHigh,
                modifier = Modifier.weight(1f),
            )
            Text(
                "Luk",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 13.sp),
                color = KalivTheme.colors.textMuted,
                modifier = Modifier.clickable(onClickLabel = "Luk") { onDismiss() },
            )
        }
        Spacer(Modifier.height(9.dp))
        Text(
            title,
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
            color = KalivTheme.colors.textHigh,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (preview.isNotEmpty()) {
            Spacer(Modifier.height(3.dp))
            Text(
                preview,
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp, lineHeight = 19.sp),
                color = KalivTheme.colors.textMuted,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (truncated) {
            Spacer(Modifier.height(6.dp))
            Text(
                "Teksten var for lang og er klippet.",
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 12.5.sp),
                color = KalivTheme.colors.textMuted,
            )
        }
        Spacer(Modifier.height(13.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .background(KalivTheme.colors.signal, RoundedCornerShape(11.dp))
                .clickable(enabled = !busy, onClickLabel = "Spørg om det") { onAsk() }
                .padding(vertical = 11.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                if (busy) "Arbejder …" else "Spørg om det",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                color = KalivTheme.colors.onSignal,
            )
        }
        Spacer(Modifier.height(9.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(11.dp))
                .clickable(enabled = rigAvailable && !busy, onClickLabel = "Gem i Viden") { onSaveToKnowledge() }
                .padding(vertical = 11.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                "Gem i Viden",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                color = if (rigAvailable) KalivTheme.colors.textHigh else KalivTheme.colors.textMuted,
            )
        }
        Spacer(Modifier.height(6.dp))
        Text(
            if (rigAvailable) {
                "Intet er gemt endnu — du bestemmer hvad der sker med det."
            } else {
                "Viden kræver en rig. Uden den kan du stadig spørge om teksten."
            },
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 12.sp),
            color = KalivTheme.colors.textMuted,
        )
    }
}
