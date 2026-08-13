package dk.ternedal.modelrig.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SheetState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Kaliv-komponentbiblioteket (DDR-001, fase 1). Byggesten til skaerm-slicerne
 * i fase 2-4: alt farve/typografi/geometri kommer fra KalivTheme/KalivTokens/
 * KalivType — ingen literaler her. B5-linjen: M3-komponenter med tokens hvor
 * afvigelsen er <= 3dp (Switch, knapper, sheet); custom kun hvor M3 ikke kan
 * (chip-raekkens fade, caps-labels, cursor/equalizer i KalivAnimations.kt).
 */

/** Fyldt primaerknap: guldfyld med moerk ink (gold.on), 48dp, popover-radius. */
@Composable
fun KalivPrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        modifier = modifier.defaultMinSize(minHeight = KalivTokens.Layout.minTouch),
        enabled = enabled,
        shape = RoundedCornerShape(KalivTokens.Radius.popover),
        colors = ButtonDefaults.buttonColors(
            containerColor = KalivTheme.colors.signal,
            contentColor = KalivTheme.colors.onSignal,
            disabledContainerColor = KalivTheme.colors.surfaceHigh,
            disabledContentColor = KalivTheme.colors.faint,
        ),
    ) {
        Text(text, style = KalivType.RowTitle)
    }
}

/** Sekundaerknap: transparent flade, hairline-kant, primaer tekst. */
@Composable
fun KalivSecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier.defaultMinSize(minHeight = KalivTokens.Layout.minTouch),
        enabled = enabled,
        shape = RoundedCornerShape(KalivTokens.Radius.popover),
        border = BorderStroke(KalivTokens.Layout.hairline, KalivTheme.colors.hairline),
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = KalivTheme.colors.textHigh,
            disabledContentColor = KalivTheme.colors.faint,
        ),
    ) {
        Text(text, style = KalivType.RowTitle)
    }
}

/**
 * Kontekst-chip (topbarens raekke, kilde-chips): pille med hairline-kant.
 * Valgt tilstand = guld-tint-baggrund + accent-kant/-tekst (mockup: "RAG · Til").
 */
@Composable
fun KontekstChip(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    selected: Boolean = false,
    leading: (@Composable RowScope.() -> Unit)? = null,
) {
    val border = if (selected) KalivTheme.colors.accent else KalivTheme.colors.hairline
    val content = if (selected) KalivTheme.colors.accent else KalivTheme.colors.textMuted
    val fill = if (selected) KalivTheme.colors.goldTint else Color.Transparent
    Surface(
        onClick = onClick,
        modifier = modifier.height(KalivTokens.Spacing.s8),
        shape = RoundedCornerShape(KalivTokens.Radius.round),
        color = fill,
        contentColor = content,
        border = BorderStroke(KalivTokens.Layout.hairline, border),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = KalivTokens.Spacing.s3),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(KalivTokens.Spacing.s1),
        ) {
            if (leading != null) leading()
            Text(text, style = KalivType.Secondary)
        }
    }
}

/**
 * Horisontalt scrollende chip-raekke med fade-maske i hoejre kant, saa
 * afklippede chips laeses som "der er mere". [background] SKAL matche fladen
 * raekken ligger paa (typisk canvas) — fade er en gradient til netop den farve.
 */
@Composable
fun ChipRow(
    background: Color,
    modifier: Modifier = Modifier,
    content: @Composable RowScope.() -> Unit,
) {
    Box(modifier = modifier.height(IntrinsicSize.Min)) {
        Row(
            modifier = Modifier
                .horizontalScroll(rememberScrollState())
                .padding(end = KalivTokens.Spacing.s6),
            horizontalArrangement = Arrangement.spacedBy(KalivTokens.Spacing.s2),
            verticalAlignment = Alignment.CenterVertically,
            content = content,
        )
        Box(
            Modifier
                .align(Alignment.CenterEnd)
                .width(KalivTokens.Spacing.s6)
                .fillMaxHeight()
                .background(
                    Brush.horizontalGradient(
                        listOf(background.copy(alpha = 0f), background),
                    ),
                ),
        )
    }
}

/** Caps-sektionslabel ("I DAG", "KILDE"): 11,5sp Inter 700, 0,18em, caps-farven. */
@Composable
fun CapsLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(),
        modifier = modifier,
        style = KalivType.CapsLabel,
        color = KalivTheme.colors.caps,
    )
}

/** Statusprik (8dp): forbundet/advarsel/fejl — farven baerer aldrig alene, saet tekst ved siden af. */
@Composable
fun StatusDot(color: Color, modifier: Modifier = Modifier) {
    Box(
        modifier
            .size(KalivTokens.Spacing.s2)
            .background(color, CircleShape),
    )
}

/** Lille badge-pille med guld-tint og accent-tekst ("STANDARD", "Åbn"). */
@Composable
fun KalivBadge(text: String, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(KalivTokens.Radius.round),
        color = KalivTheme.colors.goldTint,
        contentColor = KalivTheme.colors.accent,
    ) {
        Text(
            text,
            modifier = Modifier.padding(
                horizontal = KalivTokens.Spacing.s2,
                vertical = KalivTokens.Spacing.s1,
            ),
            style = KalivType.CapsLabel,
        )
    }
}

/** Kaliv-switch: M3 Switch med tokens (B5 — afvigelsen fra mockup-maalet er <= 3dp). */
@Composable
fun KalivSwitch(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Switch(
        checked = checked,
        onCheckedChange = onCheckedChange,
        modifier = modifier,
        enabled = enabled,
        colors = SwitchDefaults.colors(
            checkedTrackColor = KalivTheme.colors.signal,
            // Knoppen er altid lys (mockup #FFFDF9 = tokenet light.surface).
            checkedThumbColor = KalivTokens.Light.surface,
            uncheckedTrackColor = KalivTheme.colors.surfaceHigh,
            uncheckedThumbColor = KalivTheme.colors.textMuted,
            uncheckedBorderColor = KalivTheme.colors.hairline,
        ),
    )
}

/**
 * Bottom-sheet-wrapper: sheet-fladen, redesignets scrim og drag-handle
 * (46x5dp, jf. B2-tabellen). Indhold faar sheet-radius i toppen.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KalivSheet(
    onDismissRequest: () -> Unit,
    sheetState: SheetState,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    ModalBottomSheet(
        onDismissRequest = onDismissRequest,
        sheetState = sheetState,
        modifier = modifier,
        shape = RoundedCornerShape(
            topStart = KalivTokens.Radius.sheet,
            topEnd = KalivTokens.Radius.sheet,
        ),
        containerColor = KalivTheme.colors.sheet,
        scrimColor = KalivTheme.colors.scrim,
        dragHandle = { KalivDragHandle() },
        content = content,
    )
}

/** Drag-handle til sheets: 46x5dp afrundet, hairline-tonen. */
@Composable
fun KalivDragHandle(modifier: Modifier = Modifier) {
    Box(
        modifier
            .padding(vertical = KalivTokens.Spacing.s2)
            .width(KalivTokens.Layout.dragHandleWidth)
            .height(KalivTokens.Layout.dragHandleHeight)
            .background(KalivTheme.colors.hairline, RoundedCornerShape(KalivTokens.Radius.round)),
    )
}
