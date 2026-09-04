package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType
import androidx.compose.foundation.clickable

/**
 * Skaerm 5 (Opsaetning/parring) — statsloese byggesten, 1:1 mod HTML-
 * referencen x393/322 jf. DDR-001/B2. SetupScreen/RigCard/CloudCard ejer al
 * logik (claim-flowet, reconnect-uden-kode, reachability-ping, profiler).
 * Input-fladen #0F0C09 (moerk) ligger mellem canvas og surface i referencen
 * og er bevidst uden for tokensaettet indtil flere skaerme kraever den;
 * lys tilstand bruger surface.
 */
@Composable
fun PairingHeader(subtitle: String, modifier: Modifier = Modifier) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .size(46.dp)
                .background(KalivTheme.colors.surface, RoundedCornerShape(13.dp))
                .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(13.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Image(
                painter = painterResource(R.drawable.kaliv_ankh_gold),
                contentDescription = null,
                modifier = Modifier.height(27.dp),
            )
        }
        Spacer(Modifier.width(13.dp))
        Column {
            Text(
                "KALIV",
                style = TextStyle(
                    fontFamily = KalivType.EbGaramond,
                    fontWeight = FontWeight(KalivTokens.Typography.Wordmarkmobile.weight),
                    fontSize = KalivTokens.Typography.Wordmarkmobile.size,
                    letterSpacing = KalivTokens.Typography.Wordmarkmobile.trackingEm.em,
                ),
                color = if (KalivTheme.colors.isDark) KalivTheme.colors.textSoft else KalivTheme.colors.textHigh,
            )
            Spacer(Modifier.height(1.dp))
            Text(
                subtitle,
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                color = KalivTheme.colors.textMuted,
            )
        }
    }
}

/** Feltets input-flade: moerkere end kortet, hairline, redesignets radius. */
@Composable
fun PairingField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    letterSpacingEm: Float = 0f,
    placeholder: String = "",
    visualTransformation: VisualTransformation = VisualTransformation.None,
    enabled: Boolean = true,
) {
    Column(modifier.fillMaxWidth().padding(bottom = 12.dp)) {
        Text(
            label.uppercase(),
            style = TextStyle(
                fontFamily = KalivType.Inter,
                fontWeight = FontWeight.SemiBold,
                fontSize = 12.sp,
                letterSpacing = 0.08.em,
            ),
            color = KalivTheme.colors.faint,
        )
        Spacer(Modifier.height(6.dp))
        val inputBg = if (KalivTheme.colors.isDark) Color(0xFF0F0C09) else KalivTheme.colors.surface
        Box(
            Modifier
                .fillMaxWidth()
                .background(inputBg, RoundedCornerShape(KalivTokens.Radius.card))
                .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(KalivTokens.Radius.card))
                .padding(horizontal = 16.dp, vertical = 12.dp),
        ) {
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                singleLine = true,
                enabled = enabled,
                visualTransformation = visualTransformation,
                modifier = Modifier.fillMaxWidth(),
                textStyle = TextStyle(
                    fontFamily = KalivType.Inter,
                    fontWeight = FontWeight.Medium,
                    fontSize = 16.sp,
                    letterSpacing = letterSpacingEm.em,
                    color = KalivTheme.colors.textSoft,
                ),
                cursorBrush = SolidColor(KalivTheme.colors.accent),
                decorationBox = { inner ->
                    if (value.isEmpty() && placeholder.isNotEmpty()) {
                        Text(
                            placeholder,
                            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.sp),
                            color = KalivTheme.colors.faint,
                        )
                    }
                    inner()
                },
            )
        }
    }
}

/** Advarselsnoten m. info-ikon i warn og fremhaevet 0.0.0.0. */
@Composable
fun PairingBindNote(modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth().padding(bottom = 16.dp), verticalAlignment = Alignment.Top) {
        Icon(
            painterResource(R.drawable.ic_kaliv_info),
            contentDescription = null,
            tint = KalivTheme.colors.warn,
            modifier = Modifier.size(16.dp).padding(top = 1.dp),
        )
        Spacer(Modifier.width(7.dp))
        Text(
            buildAnnotatedString {
                append("Serveren skal binde ")
                withStyle(SpanStyle(color = KalivTheme.colors.textSoft, fontWeight = FontWeight.SemiBold)) {
                    append("0.0.0.0")
                }
                append(" / Tailscale-IP \u2014 ikke 127.0.0.1. Brug LAN-IP.")
            },
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.sp, lineHeight = 18.sp),
            color = KalivTheme.colors.textMuted,
        )
    }
}

/** Kilde-kortets hoved: ikon-brik + titel + undertekst (rig/cloud). */
@Composable
fun PairingCardHeader(
    icon: Int,
    iconTint: Color,
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
    trailing: (@Composable () -> Unit)? = null,
) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier.size(41.dp).background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(12.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(painterResource(icon), contentDescription = null, tint = iconTint, modifier = Modifier.size(22.dp))
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 18.sp),
                color = KalivTheme.colors.textHigh,
            )
            Text(
                subtitle,
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                color = KalivTheme.colors.textMuted,
            )
        }
        trailing?.invoke()
    }
}

/**
 * Kortet et parringslink lander i.
 *
 * Linket har udfyldt felterne — men det er MENNESKET der parrer. Derfor står
 * værten skrevet ud med store bogstaver i sin egen linje: det er den ene ting
 * man skal genkende, før koden bruges. En QR kan man ikke læse med øjnene, og
 * et link kan pege hvor som helst; uden dette skridt kunne en fremmed kode
 * binde telefonen til en fremmed rig.
 */
@Composable
fun PairingLinkNotice(
    host: String,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 15.dp, vertical = 13.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                painterResource(R.drawable.ic_kaliv_shield),
                contentDescription = null,
                tint = KalivTheme.colors.accent,
                modifier = Modifier.size(15.dp),
            )
            Spacer(Modifier.width(9.dp))
            Text(
                "Felterne er udfyldt fra et link",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                color = KalivTheme.colors.textHigh,
                modifier = Modifier.weight(1f),
            )
            Text(
                "Ryd",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 13.5.sp),
                color = KalivTheme.colors.textMuted,
                modifier = Modifier.clickable(onClickLabel = "Ryd") { onDismiss() },
            )
        }
        Spacer(Modifier.height(6.dp))
        Text(
            host,
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
            color = KalivTheme.colors.accent,
        )
        Spacer(Modifier.height(3.dp))
        Text(
            "Tjek at det er din egen rig, og tryk så Forbind. Intet er parret endnu.",
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
            color = KalivTheme.colors.textMuted,
        )
    }
}
