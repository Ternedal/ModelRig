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
import androidx.compose.material3.HorizontalDivider
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
 * Rig-status (skærm 18) — 1:1 mod referencen, ×1,2205 fra 322px-frames.
 * Statsløst; RigStatusScreen ejer indlæsning og fejlhåndtering.
 *
 * Dokumenterede afvigelser (kravspec-huller, ikke designfrihed):
 *  - Mockuppens "oppetid 6 t 12 m" udelades: riggen rapporterer ingen
 *    oppetid (/api/v1/status har version, device og upstream — intet
 *    starttidspunkt). Linjen viser forbindelsestilstanden alene.
 *  - Mockuppens "Genstart model-server" og "Frigør VRAM" er UDELADT:
 *    der findes ingen API'er til nogen af delene. Døde knapper lyver.
 *  - Målerens spor bruger hairline-tokenet (referencens #2a2119 ligger
 *    to kanaltrin fra #2a2521 — intet nyt token for den forskel).
 */
/**
 * Formaterer oppetid som referencen ("6 t 12 m"). Sekunder vises kun under
 * et minut, så tallet ikke flimrer; over et døgn skifter den til "2 d 3 t".
 * Bemærk: dette er BACKEND-processens levetid — ikke maskinens.
 */
fun formatUptime(seconds: Long): String {
    if (seconds < 60) return "$seconds s"
    val minutes = seconds / 60
    val hours = minutes / 60
    val days = hours / 24
    return when {
        days > 0 -> "$days d ${hours % 24} t"
        hours > 0 -> "$hours t ${minutes % 60} m"
        else -> "$minutes m"
    }
}

@Composable
fun RigEndpointCard(
    host: String,
    stateText: String,
    online: Boolean?,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Row(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 16.dp, vertical = 15.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(49.dp).background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(13.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                painterResource(R.drawable.ic_kaliv_rack),
                contentDescription = null,
                tint = KalivTheme.colors.accent,
                modifier = Modifier.size(24.dp),
            )
        }
        Spacer(Modifier.width(15.dp))
        Column(Modifier.weight(1f)) {
            Text(
                host,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 17.sp),
                color = KalivTheme.colors.textHigh,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.size(8.5.dp).background(
                        when (online) {
                            true -> KalivTheme.colors.success
                            false -> KalivTheme.colors.danger
                            null -> KalivTheme.colors.faint
                        },
                        RoundedCornerShape(KalivTokens.Radius.round),
                    ),
                )
                Spacer(Modifier.width(7.dp))
                Text(
                    stateText,
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.5.sp),
                    color = KalivTheme.colors.textMuted,
                )
            }
        }
    }
}

/** Sektions-caps: 700/9,5px/.18em i referencen. */
@Composable
fun RigSectionCaps(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        style = TextStyle(
            fontFamily = KalivType.Inter,
            fontWeight = FontWeight.Bold,
            fontSize = 11.5.sp,
            letterSpacing = 0.18.em,
        ),
        color = KalivTheme.colors.caps,
        modifier = modifier,
    )
}

/**
 * Målerrække: etiket, værdi og et spor der kun fyldes når værdien FINDES.
 * [fraction] null ⇒ tomt spor + "ukendt" som værdi, aldrig et gættet tal.
 */
@Composable
fun RigMeterRow(
    label: String,
    value: String,
    fraction: Float?,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(
                label,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 14.5.sp),
                color = KalivTheme.colors.textMuted,
            )
            Text(
                value,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                color = if (fraction == null) KalivTheme.colors.faint else KalivTheme.colors.textSoft,
            )
        }
        Spacer(Modifier.height(7.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .height(6.dp)
                .background(KalivTheme.colors.hairline, RoundedCornerShape(KalivTokens.Radius.round)),
        ) {
            if (fraction != null) {
                Box(
                    Modifier
                        .fillMaxWidth(fraction.coerceIn(0f, 1f))
                        .height(6.dp)
                        .background(KalivTokens.Gold.fill, RoundedCornerShape(KalivTokens.Radius.round)),
                )
            }
        }
    }
}

/** Én indlæst model: liveness-prik, navn, VRAM-forbrug. */
@Composable
fun RigLoadedModelRow(
    name: String,
    sizeLabel: String,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().padding(vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier.size(7.dp).background(
                    KalivTheme.colors.success,
                    RoundedCornerShape(KalivTokens.Radius.round),
                ),
            )
            Spacer(Modifier.width(12.dp))
            Text(
                name,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
                color = KalivTheme.colors.textHigh,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Text(
                sizeLabel,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.5.sp),
                color = KalivTheme.colors.faint,
            )
        }
        HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)
    }
}

/** Ærlig note når målingerne ikke kan hentes (ældre rig, eller kaldet fejlede). */
@Composable
fun RigMeasurementNote(text: String, onRetry: (() -> Unit)? = null, modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Row(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 15.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text,
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
            color = KalivTheme.colors.textMuted,
            modifier = Modifier.weight(1f),
        )
        if (onRetry != null) {
            Spacer(Modifier.width(12.dp))
            Text(
                "Prøv igen",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 13.5.sp),
                color = KalivTheme.colors.accent,
                modifier = Modifier.clickable(onClickLabel = "Prøv igen") { onRetry() },
            )
        }
    }
}

/**
 * "Frigør VRAM" — den ene af mockuppens to handlingsknapper der KAN bygges
 * ærligt. Den beder riggen slippe modellerne fra hukommelsen (Ollamas eget
 * keep_alive=0); intet genstartes, og næste prompt indlæser modellen igen.
 *
 * Mockuppens anden knap, "Genstart model-server", er BEVIDST IKKE bygget:
 * at dræbe og starte model-serveren udefra kræver en supervisor-kontrakt på
 * riggen, og fejler genstarten står telefonen uden nogen vej til at rette op.
 * Unload giver samme VRAM-gevinst uden den fælde.
 */
@Composable
fun RigFreeVramAction(
    busy: Boolean,
    confirming: Boolean,
    resultLine: String?,
    onAsk: () -> Unit,
    onConfirm: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(modifier.fillMaxWidth()) {
        if (confirming) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .background(KalivTheme.colors.surfaceDim, shape)
                    .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
                    .padding(horizontal = 16.dp, vertical = 15.dp),
            ) {
                Text(
                    "Frigør VRAM nu?",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
                    color = KalivTheme.colors.textHigh,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "Modellerne slippes fra hukommelsen. Intet genstartes — men næste svar bliver langsommere, fordi modellen skal indlæses igen.",
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                    color = KalivTheme.colors.textMuted,
                )
                Spacer(Modifier.height(13.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Box(
                        Modifier
                            .weight(1f)
                            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(12.dp))
                            .clickable(enabled = !busy, onClickLabel = "Behold") { onCancel() }
                            .padding(vertical = 11.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            "Behold",
                            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                            color = KalivTheme.colors.textSoft,
                        )
                    }
                    Box(
                        Modifier
                            .weight(1f)
                            .background(KalivTokens.Gold.fill, RoundedCornerShape(12.dp))
                            .clickable(enabled = !busy, onClickLabel = "Frigør nu") { onConfirm() }
                            .padding(vertical = 11.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            if (busy) "Frigør …" else "Frigør nu",
                            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                            color = KalivTokens.Gold.on,
                        )
                    }
                }
            }
        } else {
            Box(
                Modifier
                    .fillMaxWidth()
                    .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
                    .clickable(enabled = !busy, onClickLabel = "Frigør VRAM") { onAsk() }
                    .padding(vertical = 12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "Frigør VRAM",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTheme.colors.textSoft,
                )
            }
        }
        resultLine?.let {
            Spacer(Modifier.height(8.dp))
            Text(
                it,
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                color = KalivTheme.colors.textMuted,
            )
        }
    }
}

/** "9,0 GB frigjort" / "0 modeller var indlæst" — rigens eget svar, aldrig et estimat. */
fun unloadResultLine(unloaded: Int, freedBytes: Long, failed: Int): String {
    val base = when {
        unloaded == 0 && failed == 0 -> "Ingen modeller var indlæst"
        else -> {
            val gb = freedBytes / 1_073_741_824.0
            val model = if (unloaded == 1) "1 model" else "$unloaded modeller"
            "$model sluppet \u00b7 " + String.format(java.util.Locale("da", "DK"), "%.1f GB", gb) + " frigjort"
        }
    }
    return if (failed > 0) "$base \u00b7 $failed kunne ikke slippes" else base
}
