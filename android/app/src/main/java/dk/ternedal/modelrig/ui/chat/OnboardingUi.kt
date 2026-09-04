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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Velkomsten — første gang appen åbnes uden hverken rig eller cloud.
 *
 * Den forklarer ÉN ting, som ellers først går op for folk bagefter: Kaliv er
 * klienten, og modellerne kører på din egen maskine. Uden en rig kan man
 * stadig chatte via cloud, men Viden og stemme bor på riggen — det siges her
 * frem for at blive opdaget som en manglende knap senere.
 *
 * Den kan altid springes over. En velkomst der spærrer for appen er en
 * forhindring, ikke en introduktion.
 */
@Composable
fun OnboardingCard(
    onScanQr: (() -> Unit)?,
    onEnterCode: () -> Unit,
    onSkip: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth()) {
        Text(
            "Velkommen til Kaliv",
            style = TextStyle(fontFamily = KalivType.EbGaramond, fontWeight = FontWeight.Medium, fontSize = 27.sp),
            color = KalivTheme.colors.textHigh,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            "Kaliv er telefonen. Modellerne kører på din egen maskine — riggen.",
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 15.sp, lineHeight = 22.sp),
            color = KalivTheme.colors.textMuted,
        )
        Spacer(Modifier.height(20.dp))
        OnboardingStep(
            n = "1",
            title = "Start riggen på din maskine",
            body = "Kaliv taler med den over dit eget netværk. Intet går forbi andre.",
        )
        OnboardingStep(
            n = "2",
            title = "Par telefonen",
            body = "Riggen viser en kode. Skan den, eller tast den ind.",
        )
        OnboardingStep(
            n = "3",
            title = "Så er du i gang",
            body = "Uden rig kan du stadig chatte via cloud — men Viden og stemme bor på riggen.",
            last = true,
        )
        Spacer(Modifier.height(20.dp))
        onScanQr?.let { scan ->
            Box(
                Modifier
                    .fillMaxWidth()
                    .background(KalivTheme.colors.signal, RoundedCornerShape(11.dp))
                    .clickable(onClickLabel = "Skan QR fra riggen") { scan() }
                    .padding(vertical = 12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "Skan QR fra riggen",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 15.sp),
                    color = KalivTheme.colors.onSignal,
                )
            }
            Spacer(Modifier.height(9.dp))
        }
        Box(
            Modifier
                .fillMaxWidth()
                .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(11.dp))
                .clickable(onClickLabel = "Indtast koden") { onEnterCode() }
                .padding(vertical = 12.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                "Indtast koden i hånden",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 15.sp),
                color = KalivTheme.colors.textHigh,
            )
        }
        Spacer(Modifier.height(13.dp))
        Text(
            "Spring over",
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.sp),
            color = KalivTheme.colors.textMuted,
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClickLabel = "Spring over") { onSkip() }
                .padding(vertical = 6.dp),
        )
    }
}

@Composable
private fun OnboardingStep(n: String, title: String, body: String, last: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(bottom = if (last) 0.dp else 15.dp)) {
        Box(
            Modifier
                .size(26.dp)
                .background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(13.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                n,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Bold, fontSize = 12.5.sp),
                color = KalivTheme.colors.accent,
            )
        }
        Spacer(Modifier.width(13.dp))
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 15.sp),
                color = KalivTheme.colors.textHigh,
            )
            Spacer(Modifier.height(2.dp))
            Text(
                body,
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp, lineHeight = 19.sp),
                color = KalivTheme.colors.textMuted,
            )
        }
    }
}
