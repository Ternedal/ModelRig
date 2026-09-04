package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.BorderStroke
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
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.components.KalivSheet
import dk.ternedal.modelrig.ui.components.KalivSwitch
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Skaerm 4 (Kapaciteter, smertepunkt 2) — 1:1 mod HTML-referencen, x393/322.
 * Statsloest indhold + KalivSheet-wrapper. Agent-raekken vises som info uden
 * kontakt indtil en reel agent-tilstand findes i chatten (doede kontakter er
 * vaerre end manglende — samme princip som thumbs i #533); kontakten kommer
 * med skaerm 12-arbejdet. Stemme-raekkens "Aabn" venter paa skaerm 6 — indtil
 * da baerer raekken den REELLE kontakt der findes: svar-via-cloud.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CapabilitiesSheet(
    ragOn: Boolean,
    ragSubtitle: String,
    ragSourceLabel: String,
    onToggleRag: (Boolean) -> Unit,
    onSources: () -> Unit,
    toolsOn: Boolean,
    onToggleTools: (Boolean) -> Unit,
    voiceCloudAvailable: Boolean,
    voiceViaCloud: Boolean,
    onToggleVoiceCloud: (Boolean) -> Unit,
    onOpenVoice: () -> Unit,
    onRunAsAgent: (() -> Unit)? = null,
    onDismiss: () -> Unit,
) {
    KalivSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        CapabilitiesSheetContent(
            ragOn, ragSubtitle, ragSourceLabel, onToggleRag, onSources,
            toolsOn, onToggleTools, voiceCloudAvailable, voiceViaCloud, onToggleVoiceCloud,
            onOpenVoice,
            onRunAsAgent,
        )
    }
}

@Composable
fun CapabilitiesSheetContent(
    ragOn: Boolean,
    ragSubtitle: String,
    ragSourceLabel: String,
    onToggleRag: (Boolean) -> Unit,
    onSources: () -> Unit,
    toolsOn: Boolean,
    onToggleTools: (Boolean) -> Unit,
    voiceCloudAvailable: Boolean,
    voiceViaCloud: Boolean,
    onToggleVoiceCloud: (Boolean) -> Unit,
    onOpenVoice: () -> Unit = {},
    onRunAsAgent: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    Column(modifier.padding(start = 22.dp, end = 22.dp, bottom = 18.dp)) {
        Text("Kapaciteter", style = KalivType.Title, color = KalivTheme.colors.textHigh)
        Spacer(Modifier.height(4.dp))
        Text(
            "Hvad Kaliv m\u00e5 bruge i denne samtale",
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.sp),
            color = KalivTheme.colors.textMuted,
        )
        Spacer(Modifier.height(17.dp))
        HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)

        CapRow(
            icon = R.drawable.ic_kaliv_book,
            iconTint = KalivTheme.colors.accent,
            title = "Viden (RAG)",
            subtitle = ragSubtitle,
            extra = {
                Row(
                    Modifier.padding(top = 10.dp).clickable(onClickLabel = "V\u00e6lg kilder") { onSources() },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        ragSourceLabel,
                        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 13.5.sp),
                        color = KalivTheme.colors.accent,
                    )
                    Spacer(Modifier.width(5.dp))
                    Icon(
                        painterResource(R.drawable.ic_kaliv_chevron_right),
                        contentDescription = null,
                        tint = KalivTheme.colors.accent,
                        modifier = Modifier.size(15.dp),
                    )
                }
            },
            trailing = { KalivSwitch(checked = ragOn, onCheckedChange = onToggleRag) },
        )
        HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)

        CapRow(
            icon = R.drawable.ic_kaliv_tools,
            iconTint = KalivTheme.colors.textMuted,
            title = "V\u00e6rkt\u00f8jer",
            subtitle = "Lad Kaliv udf\u00f8re handlinger p\u00e5 din maskine",
            extra = {
                Row(Modifier.padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        painterResource(R.drawable.ic_kaliv_shield),
                        contentDescription = null,
                        tint = KalivTheme.colors.warn,
                        modifier = Modifier.size(15.dp),
                    )
                    Spacer(Modifier.width(6.dp))
                    Text(
                        "Kr\u00e6ver din godkendelse hver gang",
                        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                        color = KalivTheme.colors.warn,
                    )
                }
            },
            trailing = { KalivSwitch(checked = toolsOn, onCheckedChange = onToggleTools) },
        )
        HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)

        CapRow(
            icon = R.drawable.ic_kaliv_agent,
            iconTint = KalivTheme.colors.textMuted,
            title = "Agent",
            // Raekken er KUN en indgang, naar der staar noget i composeren:
            // agenten planlaegger for en besked, ikke for ingenting.
            onClick = onRunAsAgent,
            // Utilgaengelig: sig HVORFOR, ellers ligner raekken en doed knap --
            // operatoeren trykkede paa den i tre dage med tom composer.
            subtitle = if (onRunAsAgent != null) "Laeg en plan for det, du har skrevet"
                       else "Skriv en besked f\u00f8rst \u2014 agenten planl\u00e6gger for det, du skriver",
            trailing = null,
        )
        HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)

        CapRow(
            icon = R.drawable.ic_kaliv_mic,
            iconTint = KalivTheme.colors.textMuted,
            title = "Stemme",
            onClick = onOpenVoice,
            subtitle = if (voiceViaCloud && voiceCloudAvailable) "Tal med Kaliv \u00b7 svar via cloud"
                       else "Tal med Kaliv \u00b7 ASR/TTS lokalt",
            trailing = if (voiceCloudAvailable) ({
                KalivSwitch(checked = voiceViaCloud, onCheckedChange = onToggleVoiceCloud)
            }) else null,
        )
        HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)

        Spacer(Modifier.height(17.dp))
        Row(
            Modifier
                .fillMaxWidth()
                .background(KalivTheme.colors.surface, RoundedCornerShape(KalivTokens.Radius.card))
                .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(KalivTokens.Radius.card))
                .padding(horizontal = 15.dp, vertical = 13.dp),
        ) {
            Icon(
                painterResource(R.drawable.ic_kaliv_shield),
                contentDescription = null,
                tint = KalivTokens.Gold.fill,
                modifier = Modifier.size(20.dp).padding(top = 1.dp),
            )
            Spacer(Modifier.width(10.dp))
            Text(
                androidx.compose.ui.text.buildAnnotatedString {
                    append("V\u00e6rkt\u00f8jer og agent k\u00f8rer kun p\u00e5 din rig og logges i ")
                    withStyle(androidx.compose.ui.text.SpanStyle(color = KalivTheme.colors.accent)) {
                        append("Handlingslog")
                    }
                    append(".")
                },
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp, lineHeight = 20.sp),
                color = KalivTheme.colors.textMuted,
            )
        }
    }
}

@Composable
private fun CapRow(
    icon: Int,
    iconTint: androidx.compose.ui.graphics.Color,
    title: String,
    subtitle: String,
    trailing: (@Composable () -> Unit)?,
    extra: (@Composable () -> Unit)? = null,
    onClick: (() -> Unit)? = null,
) {
    val base = if (onClick != null) Modifier.fillMaxWidth().clickable(onClickLabel = title) { onClick() } else Modifier.fillMaxWidth()
    Row(base.padding(vertical = 16.dp)) {
        Box(
            Modifier
                .size(46.dp)
                .background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(13.dp))
                .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(13.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(painterResource(icon), contentDescription = null, tint = iconTint, modifier = Modifier.size(23.dp))
        }
        Spacer(Modifier.width(15.dp))
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 17.sp),
                color = KalivTheme.colors.textHigh,
            )
            Spacer(Modifier.height(3.dp))
            Text(
                subtitle,
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.sp, lineHeight = 20.sp),
                color = KalivTheme.colors.textMuted,
            )
            extra?.invoke()
        }
        if (trailing != null) {
            Spacer(Modifier.width(12.dp))
            trailing()
        }
    }
}
