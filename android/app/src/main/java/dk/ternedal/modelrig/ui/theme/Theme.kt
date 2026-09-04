package dk.ternedal.modelrig.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Kaliv-paletten -- fra og med DDR-001 (13/08-2026) er kilden de genererede
// KalivTokens, ikke laengere haandskrevne literaler fra brandpakken. Aendr
// JSON'en og koer generatoren; denne fil holder kun rolle-navnene og
// M3-mappingen. Historik: 06_COLOR_SYSTEM-paletten baar appen indtil
// redesignet; dens ink-paa-accent-regel lever videre i tokens (gold.on).
//
// Rollerne mapper ikke rent til Material3's navne (ingen M3-slot for hairline,
// sheet-flade eller brugerboble), saa navnene bor i KalivColors og naas som
// KalivTheme.colors.X. Material faar stadig et afledt scheme nedenunder til de
// komponenter (dialoger, switches) der laeser MaterialTheme direkte.
//
// KONTRAST, maalt ikke antaget (DDR-001): lys tekst paa guldfyldet #B08A3E
// maalte 2,80:1 -- derfor er tekst PAA guld altid moerk ink (gold.on #2B1C05,
// 5,15:1). Den lyse daempede tekst fulgte tidligere en AAA-pin (#5A4831,
// Anders 30/07); pinnen er afloest af DDR-001 og vaerdien er nu tokenets --
// se tests/workflow_android_palette_divergence.py for mekanikkens historik.

/** Every colour the UI names, so a palette is one object and a mode is one instance. */
data class KalivColors(
    val background: Color,
    val surface: Color,
    val surfaceHigh: Color,
    val codeSurface: Color,
    val signal: Color,         // filled button fill (guld, jf. DDR-001)
    val accent: Color,         // guld tekst/links/fokus (paa background)
    val amber: Color,
    val textHigh: Color,
    val textMuted: Color,
    val onSignal: Color,       // ink paa guldfyld
    val success: Color,
    val danger: Color,
    val hairline: Color,
    val surfaceDim: Color,     // bannere, info-kort
    val sheet: Color,          // bottom-sheet-flade
    val divider: Color,        // listedelere (svagere end hairline)
    val userBubble: Color,
    val userBubbleBorder: Color,
    val faint: Color,          // svag tekst (tidsstempler, sub)
    val textSoft: Color,       // bloed primaertekst (forslagskort, wordmark moerk)
    val textBody: Color,       // assistentsvarenes broedtekst
    val userBubbleText: Color, // tekst i brugerboblen
    val accentSoft: Color,     // aktiv-chips og markdown-emfase
    val selectedTint: Color,   // valgt kilde-/raekke-flade (sheets)
    val caps: Color,           // caps-sektionslabels
    val goldTint: Color,       // 16 % guld-tint-baggrund
    val warn: Color,
    val scrim: Color,
    val isDark: Boolean,
)

// -- Moerk palette (tokens "dark") -------------------------------------------
val KalivDarkColors = KalivColors(
    background = KalivTokens.Dark.canvas,
    surface = KalivTokens.Dark.surface,
    surfaceHigh = KalivTokens.Dark.elevated,
    // Uden for tokensaettet: Markdown-kodefladen. Migreres naar Markdown-fladen
    // redesignes (fase 2); indtil da er literalen bevidst.
    codeSurface = Color(0xFF080706),
    signal = KalivTokens.Gold.fill,
    accent = KalivTokens.Dark.accent,
    // amber var brandpakkens sekundaere guld; redesignet har EN guld-accent.
    // Midlertidigt = accent; konsolideres naar komponentbiblioteket lander.
    amber = KalivTokens.Dark.accent,
    textHigh = KalivTokens.Dark.text,
    textMuted = KalivTokens.Dark.muted,
    onSignal = KalivTokens.Gold.on,
    success = KalivTokens.Dark.ok,
    danger = KalivTokens.Dark.danger,
    hairline = KalivTokens.Dark.border,
    surfaceDim = KalivTokens.Dark.surfaceDim,
    sheet = KalivTokens.Dark.sheet,
    divider = KalivTokens.Dark.divider,
    userBubble = KalivTokens.Dark.userBubble,
    userBubbleBorder = KalivTokens.Dark.userBubbleBorder,
    faint = KalivTokens.Dark.faint,
    textSoft = KalivTokens.Dark.textSoft,
    textBody = KalivTokens.Dark.textBody,
    userBubbleText = KalivTokens.Dark.userBubbleText,
    accentSoft = KalivTokens.Dark.accentSoft,
    selectedTint = KalivTokens.Dark.selectedTint,
    caps = KalivTokens.Dark.caps,
    goldTint = KalivTokens.Gold.tint,
    warn = KalivTokens.Dark.warn,
    scrim = KalivTokens.Dark.scrim,
    isDark = true,
)

// -- Lys palette (tokens "light") --------------------------------------------
val KalivLightColors = KalivColors(
    background = KalivTokens.Light.canvas,
    surface = KalivTokens.Light.surface,
    surfaceHigh = KalivTokens.Light.elevated,
    codeSurface = Color(0xFFEAE3D5), // uden for tokensaettet, se noten ovenfor
    signal = KalivTokens.Gold.fill,
    accent = KalivTokens.Light.accent,
    amber = KalivTokens.Light.accent,
    textHigh = KalivTokens.Light.text,
    textMuted = KalivTokens.Light.muted,
    onSignal = KalivTokens.Gold.on,
    success = KalivTokens.Light.ok,
    danger = KalivTokens.Light.danger,
    hairline = KalivTokens.Light.border,
    surfaceDim = KalivTokens.Light.surfaceDim,
    sheet = KalivTokens.Light.sheet,
    divider = KalivTokens.Light.divider,
    userBubble = KalivTokens.Light.userBubble,
    userBubbleBorder = KalivTokens.Light.userBubbleBorder,
    faint = KalivTokens.Light.faint,
    textSoft = KalivTokens.Light.textSoft,
    textBody = KalivTokens.Light.textBody,
    userBubbleText = KalivTokens.Light.userBubbleText,
    accentSoft = KalivTokens.Light.accentSoft,
    selectedTint = KalivTokens.Light.selectedTint,
    caps = KalivTokens.Light.caps,
    goldTint = KalivTokens.Gold.tint,
    warn = KalivTokens.Light.warn,
    scrim = KalivTokens.Light.scrim,
    isDark = false,
)

/** Reach the active palette anywhere: KalivTheme.colors.signal etc. */
val LocalKalivColors = staticCompositionLocalOf { KalivDarkColors }

object KalivTheme {
    val colors: KalivColors
        @Composable get() = LocalKalivColors.current
}

private fun materialFrom(c: KalivColors) =
    if (c.isDark) {
        darkColorScheme(
            primary = c.signal, onPrimary = c.onSignal,
            secondary = c.amber, onSecondary = c.onSignal,
            background = c.background, onBackground = c.textHigh,
            surface = c.surface, onSurface = c.textHigh,
            surfaceVariant = c.surfaceHigh, onSurfaceVariant = c.textMuted,
            // Menus, dialogs and sheets read from the surfaceContainer family in
            // M3. Left unset, they fall back to Material's PURPLE-tinted default
            // -- the cold cast Anders saw on the pop-up menu. Point them at the
            // warm brand surfaces instead.
            surfaceContainerLowest = c.background,
            surfaceContainerLow = c.surface,
            surfaceContainer = c.surface,
            surfaceContainerHigh = c.surfaceHigh,
            surfaceContainerHighest = c.surfaceHigh,
            error = c.danger, outline = c.hairline,
        )
    } else {
        lightColorScheme(
            primary = c.signal, onPrimary = c.onSignal,
            secondary = c.amber, onSecondary = c.onSignal,
            background = c.background, onBackground = c.textHigh,
            surface = c.surface, onSurface = c.textHigh,
            surfaceVariant = c.surfaceHigh, onSurfaceVariant = c.textMuted,
            // Same fix on the light side, where the purple default was most
            // visible: warm parchment containers, not lavender.
            surfaceContainerLowest = c.background,
            surfaceContainerLow = c.background,
            surfaceContainer = c.surface,
            surfaceContainerHigh = c.surfaceHigh,
            surfaceContainerHighest = c.surfaceHigh,
            error = c.danger, outline = c.hairline,
        )
    }

private val KalivM3Typography = Typography(
    // Titler i EB Garamond 500 -- den bundlede instans (DDR-001, PR #523).
    // Vaegten er Medium med vilje: Bold ville blive syntetisk.
    titleLarge = TextStyle(
        fontFamily = KalivType.EbGaramond,
        fontSize = 20.sp, fontWeight = FontWeight.Medium, lineHeight = 26.sp,
    ),
    bodyLarge = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.sp, lineHeight = 24.sp),
    bodyMedium = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.sp, lineHeight = 22.sp),
    labelSmall = TextStyle(fontFamily = KalivType.Inter, fontSize = 11.sp, fontWeight = FontWeight.Medium),
)

/**
 * @param dark which palette to use. Driven by a persisted, user-chosen setting
 * (a manual toggle), not the system theme, so the choice is stable across an OS
 * auto-switch. Defaults to dark to match every build before light mode existed.
 */
@Composable
fun ModelRigTheme(dark: Boolean = true, content: @Composable () -> Unit) {
    val colors = if (dark) KalivDarkColors else KalivLightColors
    CompositionLocalProvider(LocalKalivColors provides colors) {
        MaterialTheme(
            colorScheme = materialFrom(colors),
            typography = KalivM3Typography,
            content = content,
        )
    }
}
