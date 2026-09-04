package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.components.ChipRow
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Skaerm 1 (Tom-tilstand) — 1:1 mod HTML-referencen i
 * assets/design/kaliv-ui-guide/redesign-2026-08/ (kilde-sandhed for eksakte
 * vaerdier), skaleret x393/322 jf. DDR-001/B2. Dokumenterede afvigelser fra
 * mockup-pixels er DDR-001's kontrastjusteringer (svag tekst, ink paa guld) og
 * M3-komponenters indre geometri (B5). Alle composables her er statslose;
 * ChatScreen ejer tilstand og kobler callbacks (naeste slice).
 */

/** Topbarens identitetsraekke: ankh-brik 40dp, KALIV-wordmark, tema-toggle + overflow. */
@Composable
fun ChatTopBar(
    dark: Boolean,
    onToggleDark: () -> Unit,
    onOverflow: () -> Unit,
    modifier: Modifier = Modifier,
    overflowContent: (@Composable () -> Unit)? = null,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(start = 20.dp, end = 20.dp, top = 2.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(KalivTokens.Layout.ankhTopbar)
                .background(KalivTheme.colors.surface, RoundedCornerShape(11.dp))
                .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(11.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Image(
                painter = painterResource(R.drawable.kaliv_ankh_gold),
                contentDescription = null,
                modifier = Modifier.height(22.dp),
            )
        }
        Spacer(Modifier.width(11.dp))
        Text(
            "KALIV",
            style = TextStyle(
                fontFamily = KalivType.EbGaramond,
                fontWeight = FontWeight(KalivTokens.Typography.Wordmarkmobile.weight),
                fontSize = KalivTokens.Typography.Wordmarkmobile.size,
                letterSpacing = KalivTokens.Typography.Wordmarkmobile.trackingEm.em,
            ),
            color = if (dark) KalivTheme.colors.textSoft else KalivTheme.colors.textHigh,
        )
        Spacer(Modifier.weight(1f))
        IconButton(onClick = onToggleDark) {
            Icon(
                painterResource(if (dark) R.drawable.ic_kaliv_sun else R.drawable.ic_kaliv_moon),
                contentDescription = if (dark) "Skift til lyst tema" else "Skift til m\u00f8rkt tema",
                tint = KalivTheme.colors.textMuted,
                modifier = Modifier.size(22.dp),
            )
        }
        Box {
            IconButton(onClick = onOverflow) {
                Icon(
                    painterResource(R.drawable.ic_kaliv_more_vert),
                    contentDescription = "Mere",
                    tint = KalivTheme.colors.textMuted,
                    modifier = Modifier.size(24.dp),
                )
            }
            overflowContent?.invoke()
        }
    }
}

/** En chip i kontekst-raekken: 41dp pille paa surface m. hairline, ikon 16dp. */
@Composable
fun ChatContextChip(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    emphasized: Boolean = false,
    active: Boolean = false,
    leadingIcon: Painter? = null,
    leadingTint: androidx.compose.ui.graphics.Color? = null,
    trailingIcon: Painter? = null,
) {
    Surface(
        onClick = onClick,
        modifier = modifier.height(41.dp),
        shape = RoundedCornerShape(KalivTokens.Radius.round),
        color = if (active) KalivTheme.colors.goldTint else KalivTheme.colors.surface,
        contentColor = when {
            active -> KalivTheme.colors.accentSoft
            emphasized -> KalivTheme.colors.textHigh
            else -> KalivTheme.colors.textMuted
        },
        border = androidx.compose.foundation.BorderStroke(
            KalivTokens.Layout.hairline,
            if (active) KalivTokens.Gold.fill else KalivTheme.colors.hairline,
        ),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 15.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(7.dp),
        ) {
            if (leadingIcon != null) {
                Icon(
                    leadingIcon,
                    contentDescription = null,
                    tint = leadingTint ?: if (active) KalivTheme.colors.accentSoft else KalivTheme.colors.textMuted,
                    modifier = Modifier.size(16.dp),
                )
            }
            Text(
                text,
                style = TextStyle(
                    fontFamily = KalivType.Inter,
                    fontWeight = if (active) FontWeight.SemiBold else FontWeight(KalivTokens.Typography.Chip.weight),
                    fontSize = if (active) 14.5.sp else KalivTokens.Typography.Chip.size,
                ),
            )
            if (trailingIcon != null) {
                Icon(
                    trailingIcon,
                    contentDescription = null,
                    tint = KalivTheme.colors.textMuted,
                    modifier = Modifier.size(15.dp),
                )
            }
        }
    }
}

/** Skaerm 1's chip-raekke: model (gulddiamant + chevron), RAG, Tools. */
@Composable
fun ChatChipRow(
    modelLabel: String,
    onModel: () -> Unit,
    onRag: () -> Unit,
    onTools: () -> Unit,
    modifier: Modifier = Modifier,
    ragActive: Boolean = false,
    toolsActive: Boolean = false,
) {
    ChipRow(
        background = KalivTheme.colors.background,
        modifier = modifier
            .fillMaxWidth()
            .padding(start = 20.dp, bottom = 15.dp),
    ) {
        ChatContextChip(
            text = modelLabel,
            onClick = onModel,
            emphasized = true,
            leadingIcon = painterResource(R.drawable.ic_kaliv_model),
            leadingTint = KalivTheme.colors.accent,
            trailingIcon = painterResource(R.drawable.ic_kaliv_chevron_down),
        )
        ChatContextChip(
            text = if (ragActive) "RAG \u00b7 Til" else "RAG",
            onClick = onRag,
            active = ragActive,
            leadingIcon = painterResource(R.drawable.ic_kaliv_search),
        )
        ChatContextChip(
            text = "Tools",
            onClick = onTools,
            active = toolsActive,
            leadingIcon = painterResource(R.drawable.ic_kaliv_tools),
        )
    }
}

/** Tom-tilstandens midte: ankh 78dp (.85), titel, undertekst, tre forslagskort. */
@Composable
fun ChatEmptyState(
    suggestions: List<String>,
    onSuggestion: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.padding(horizontal = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Image(
            painter = painterResource(R.drawable.kaliv_ankh_gold),
            contentDescription = null,
            modifier = Modifier.height(KalivTokens.Layout.ankhEmpty),
            alpha = 0.85f,
        )
        Spacer(Modifier.height(37.dp))
        Text(
            "Hvad kan jeg hj\u00e6lpe med?",
            style = TextStyle(
                fontFamily = KalivType.EbGaramond,
                fontWeight = FontWeight(KalivTokens.Typography.Emptytitle.weight),
                fontSize = KalivTokens.Typography.Emptytitle.size,
                lineHeight = KalivTokens.Typography.Emptytitle.lineHeightSp.sp,
            ),
            color = KalivTheme.colors.textHigh,
            textAlign = TextAlign.Center,
            modifier = Modifier.widthIn(max = 281.dp),
        )
        Spacer(Modifier.height(10.dp))
        Text(
            "Alt k\u00f8rer p\u00e5 din rig",
            style = KalivType.Secondary.copy(fontSize = 15.sp),
            color = KalivTheme.colors.faint,
        )
        Spacer(Modifier.height(34.dp))
        Column(
            modifier = Modifier.widthIn(max = 308.dp).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(11.dp),
        ) {
            suggestions.forEach { s ->
                Surface(
                    onClick = { onSuggestion(s) },
                    shape = RoundedCornerShape(KalivTokens.Radius.card),
                    color = KalivTheme.colors.surfaceDim,
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 17.dp, vertical = 15.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Text(
                            s,
                            modifier = Modifier.weight(1f),
                            style = TextStyle(
                                fontFamily = KalivType.Inter,
                                fontWeight = FontWeight.Medium,
                                fontSize = 16.sp,
                            ),
                            color = KalivTheme.colors.textSoft,
                        )
                        Icon(
                            painterResource(R.drawable.ic_kaliv_chevron_right),
                            contentDescription = null,
                            tint = KalivTheme.colors.faint,
                            modifier = Modifier.size(16.dp),
                        )
                    }
                }
            }
        }
    }
}

/** Komposeren: felt paa surface m. hairline, vedhaeft/mic + guld send-FAB 46dp. */
@Composable
fun ChatComposer(
    text: String,
    placeholder: String,
    onAttach: (() -> Unit)?,
    onMic: (() -> Unit)?,
    onSend: () -> Unit,
    sendEnabled: Boolean,
    modifier: Modifier = Modifier,
    busy: Boolean = false,
    onStop: (() -> Unit)? = null,
    micSlot: (@Composable () -> Unit)? = null,
    inputField: (@Composable () -> Unit)? = null,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(start = 15.dp, end = 15.dp, top = 7.dp, bottom = 5.dp)
            .background(
                // Ejerbeslutning (Anders, 14/08): composer-fladen skal vaere sort
                // som canvas i moerkt tema — mockuppen viste surface (brun-varm).
                // Lys tilstand beholder surface.
                if (KalivTheme.colors.isDark) KalivTheme.colors.background else KalivTheme.colors.surface,
                RoundedCornerShape(KalivTokens.Radius.composer),
            )
            .border(
                KalivTokens.Layout.hairline,
                KalivTheme.colors.hairline,
                RoundedCornerShape(KalivTokens.Radius.composer),
            )
            .padding(horizontal = 15.dp, vertical = 12.dp),
    ) {
        if (inputField != null) {
            inputField()
        } else {
            Text(
                text.ifEmpty { placeholder },
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 17.sp),
                color = if (text.isEmpty()) KalivTheme.colors.faint else KalivTheme.colors.textHigh,
            )
        }
        Spacer(Modifier.height(11.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (onAttach != null) {
                IconButton(onClick = onAttach, modifier = Modifier.size(37.dp)) {
                    Icon(
                        painterResource(R.drawable.ic_kaliv_attach),
                        contentDescription = "Vedh\u00e6ft",
                        tint = KalivTheme.colors.textMuted,
                        modifier = Modifier.size(23.dp),
                    )
                }
            }
            Spacer(Modifier.weight(1f))
            if (micSlot != null) {
                micSlot()
                Spacer(Modifier.width(7.dp))
            } else if (onMic != null) {
                IconButton(onClick = onMic, modifier = Modifier.size(37.dp)) {
                    Icon(
                        painterResource(R.drawable.ic_kaliv_mic),
                        contentDescription = "Stemme",
                        tint = KalivTheme.colors.textMuted,
                        modifier = Modifier.size(22.dp),
                    )
                }
                Spacer(Modifier.width(7.dp))
            }
            Surface(
                onClick = { if (busy) onStop?.invoke() else onSend() },
                enabled = sendEnabled || busy,
                modifier = Modifier.size(KalivTokens.Layout.fabSend),
                shape = CircleShape,
                // Mockup: FAB'en er guld ogsaa i hvilende tom-tilstand; enabled
                // gater kun interaktionen, ikke udtrykket (skaerm 13 daemper).
                color = KalivTheme.colors.signal,
                contentColor = KalivTheme.colors.onSignal,
            ) {
                Box(contentAlignment = Alignment.Center) {
                    if (busy) {
                        // Stop-tilstand: kvadrat i ink paa guldet (afbryder svaret).
                        Box(
                            Modifier
                                .size(15.dp)
                                .background(KalivTheme.colors.onSignal, RoundedCornerShape(3.dp)),
                        )
                    } else {
                        Icon(
                            painterResource(R.drawable.ic_kaliv_send),
                            contentDescription = "Send",
                            modifier = Modifier.size(21.dp),
                        )
                    }
                }
            }
        }
    }
}
