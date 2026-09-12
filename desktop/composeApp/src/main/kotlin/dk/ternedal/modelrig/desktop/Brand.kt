package dk.ternedal.modelrig.desktop

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/**
 * Kaliv brand — the SAME warm palette as the Android client (ui/theme), ported
 * verbatim so the two clients finally look like the same product. Everything
 * user-facing is Kaliv; only the backend keeps the ModelRig name (Anders,
 * 12/7-2026). This replaces the old sapphire/champagne ModelRig palette that
 * predated the 9/7 rebrand.
 *
 * Property names are kept identical to the old `Brand` object (Graphite,
 * Surface, Signal, ...) so every existing call site could be migrated
 * mechanically to `KalivTheme.colors.X` — same trick as Android's
 * LocalKalivColors migration in v1.32.0.
 */
data class KalivColors(
    val Graphite: Color,     // canvas (window background)
    val Surface: Color,      // surface (bubbles/panels)
    val SurfaceHigh: Color,  // elevated (menus, chips, composer)
    val CodeSurface: Color,
    val Border: Color,       // 1dp borders on chips/bubbles/composer
    val Signal: Color,       // primary action/link color
    val Amber: Color,        // secondary accent
    val Highlight: Color,    // highlighted accent
    val TextHigh: Color,
    val TextMuted: Color,
    val Success: Color,
    val Warning: Color,
    val Danger: Color,
    val isDark: Boolean,
)

// De to paletter LAESER nu KalivTokens, som scripts/design_tokens.py genererer
// fra assets/design/kaliv-ui-guide/kaliv-ui-tokens.json. Foer 27/7-2026 stod
// vaerdierne som literaler her, med en kommentar om at "change the tokens file
// and re-apply" -- men re-apply var manuelt, og et haandtastet hex kan drive
// fra sin kilde uden at nogen opdager det.
//
// CodeSurface og onPrimary staar stadig som literaler: de findes ikke i
// tokensaettet. Det er ikke en forglemmelse, det er graensen for hvad guiden
// definerer.
val KalivDark = KalivColors(
    Graphite = KalivTokens.Dark.canvas,
    Surface = KalivTokens.Dark.surface,
    SurfaceHigh = KalivTokens.Dark.elevated,
    CodeSurface = Color(0xFF14100C),
    Border = KalivTokens.Dark.border,
    Signal = KalivTokens.Brand.bronze,
    Amber = KalivTokens.Brand.gold,
    Highlight = KalivTokens.Brand.highlight,
    TextHigh = KalivTokens.Dark.text,
    TextMuted = KalivTokens.Dark.muted,
    Success = KalivTokens.Semantic.success,
    Warning = KalivTokens.Semantic.warning,
    Danger = KalivTokens.Semantic.danger,
    isDark = true,
)

// #779 pkt. 5 / #1270: light mode maa ikke arve de deprecated, tema-uafhaengige
// brand/semantic-farver. Light.accent er bevidst moerkere end brand.bronze og
// holder almindelig action/link-tekst over AA paa baade canvas og surface.
// Statusfarverne kommer tilsvarende fra light-paletten, som er designet og
// kontrast-gatet mod de lyse flader.
val KalivLight = KalivColors(
    Graphite = KalivTokens.Light.canvas,
    Surface = KalivTokens.Light.surface,
    SurfaceHigh = KalivTokens.Light.elevated,
    CodeSurface = Color(0xFFEDE7DA),
    Border = KalivTokens.Light.border,
    Signal = KalivTokens.Light.accent,
    Amber = KalivTokens.Light.accentSoft,
    Highlight = KalivTokens.Light.accentSoft,
    TextHigh = KalivTokens.Light.text,
    TextMuted = KalivTokens.Light.muted,
    Success = KalivTokens.Light.ok,
    Warning = KalivTokens.Light.warn,
    Danger = KalivTokens.Light.danger,
    isDark = false,
)

val LocalKalivColors = staticCompositionLocalOf { KalivDark }

object KalivTheme {
    val colors: KalivColors
        @Composable get() = LocalKalivColors.current
}

@Composable
fun KalivTheme(dark: Boolean, content: @Composable () -> Unit) {
    val c = if (dark) KalivDark else KalivLight
    val scheme = if (dark) darkColorScheme(
        primary = c.Signal, onPrimary = c.TextHigh,
        secondary = c.Amber, background = c.Graphite, onBackground = c.TextHigh,
        surface = c.Surface, onSurface = c.TextHigh, error = c.Danger,
        // Material3 defaults these to a cold lavender family; the Android
        // client hit exactly that (v1.34.3: purple menus). Pin them warm.
        surfaceContainer = c.SurfaceHigh, surfaceContainerHigh = c.SurfaceHigh,
        surfaceContainerHighest = c.SurfaceHigh, surfaceContainerLow = c.Surface,
    ) else lightColorScheme(
        // The old light branch used deprecated brand.bronze as primary. Ivory
        // text on that background was only ~4.0:1; Light.accent brings the
        // normal-text pair above AA while keeping Kaliv's warm hue.
        primary = c.Signal, onPrimary = Color(0xFFF7F4EF),
        secondary = c.Amber, onSecondary = Color(0xFFF7F4EF),
        background = c.Graphite, onBackground = c.TextHigh,
        surface = c.Surface, onSurface = c.TextHigh,
        surfaceVariant = c.SurfaceHigh, onSurfaceVariant = c.TextMuted,
        outline = c.Border, outlineVariant = c.Border,
        error = c.Danger, onError = Color(0xFFF7F4EF),
        // Bind fields/cards/menus to Kaliv's own light hierarchy instead of
        // Material's default grey/lavender container ladder (#779 pkt. 5).
        surfaceContainer = c.Surface,
        surfaceContainerHigh = c.SurfaceHigh,
        surfaceContainerHighest = c.SurfaceHigh,
        surfaceContainerLow = c.Graphite,
    )
    CompositionLocalProvider(LocalKalivColors provides c) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
