package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.components.EqualizerBars
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Skaerm 6 (Stemme, push-to-talk) — 1:1 mod HTML-referencen, x393/322 jf.
 * DDR-001/B2. Statsloest; ChatScreen ejer hele stemme-flowet (voiceCapture,
 * runVoiceTurn/stopVoiceTurn, barge-in) og driver overlayet med de REELLE
 * tilstande. Dokumenterede afvigelser: mic-glyffens ink er Gold.on (moerk)
 * jf. DDR-001-kontrasten — referencen viser croeme; sprogmaerket "da-DK" er
 * udeladt (ASR-sproget er ikke konfigurerbart/kendt i klienten — pillen
 * viser kun routing Lokalt/Via cloud); equalizer-guldet #8A6A38 er
 * referencens daempede dekorationstone, bevidst uden for tokensaettet.
 */
@Composable
fun VoiceOverlayContent(
    pillText: String,
    pillDot: Color,
    stateText: String,
    transcript: String,
    buttonLabel: String,
    onMainTap: () -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    barsColor: Color = Color(0xFF8A6A38),
) {
    Column(modifier.fillMaxSize().background(KalivTheme.colors.background)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 22.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(
                Modifier
                    .height(37.dp)
                    .background(KalivTheme.colors.surface.copy(alpha = 0.7f), CircleShape)
                    .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, CircleShape)
                    .padding(horizontal = 15.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.size(7.dp).background(pillDot, CircleShape))
                Spacer(Modifier.width(7.dp))
                Text(
                    pillText,
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 14.sp),
                    color = KalivTheme.colors.textMuted,
                )
            }
            Spacer(Modifier.weight(1f))
            Box(
                Modifier
                    .size(39.dp)
                    .background(KalivTheme.colors.surface.copy(alpha = 0.7f), CircleShape)
                    .clickable(onClickLabel = "Luk stemme") { onClose() },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    painterResource(R.drawable.ic_kaliv_close),
                    contentDescription = null,
                    tint = KalivTheme.colors.textMuted,
                    modifier = Modifier.size(18.dp),
                )
            }
        }

        Column(
            Modifier.weight(1f).fillMaxWidth().padding(horizontal = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Image(
                painter = painterResource(R.drawable.kaliv_ankh_gold),
                contentDescription = null,
                modifier = Modifier.height(73.dp),
                alpha = 0.9f,
            )
            Spacer(Modifier.height(41.dp))
            EqualizerBars(
                barCount = 15,
                color = barsColor,
                barHeight = 54.dp,
                // Referencens eksakte boelgeform (bar-hoejder / 44px-max).
                profile = listOf(0.20f, 0.34f, 0.55f, 0.77f, 1.00f, 0.73f, 0.45f, 0.30f, 0.59f, 0.91f, 0.68f, 0.41f, 0.25f, 0.50f, 0.32f),
            )
            Spacer(Modifier.height(41.dp))
            Text(
                stateText,
                style = TextStyle(fontFamily = KalivType.EbGaramond, fontWeight = FontWeight.SemiBold, fontSize = 29.sp),
                color = KalivTheme.colors.textSoft,
            )
            if (transcript.isNotEmpty()) {
                Spacer(Modifier.height(17.dp))
                Text(
                    "\u201c$transcript\u201d",
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 18.sp, lineHeight = 28.sp),
                    color = KalivTheme.colors.textMuted,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.widthIn(max = 293.dp),
                )
            }
        }

        Column(
            Modifier.fillMaxWidth().padding(bottom = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                Modifier.size(114.dp).background(KalivTheme.colors.goldTint, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    Modifier
                        .size(90.dp)
                        .background(KalivTokens.Gold.fill, CircleShape)
                        .clickable(onClickLabel = buttonLabel) { onMainTap() },
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        painterResource(R.drawable.ic_kaliv_mic),
                        contentDescription = null,
                        tint = KalivTokens.Gold.on,
                        modifier = Modifier.size(37.dp),
                    )
                }
            }
            Spacer(Modifier.height(15.dp))
            Text(
                buttonLabel,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 14.5.sp),
                color = KalivTheme.colors.faint,
            )
        }
    }
}
