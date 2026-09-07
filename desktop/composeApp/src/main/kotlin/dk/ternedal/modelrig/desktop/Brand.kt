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
    val Signal: Color,       // primary accent used for actions/links
    val Amber: Color,        // secondary accent
    val Highlight: Color,    // softer accent/highlight
    val TextHigh: Color,
    val TextMuted: Color,
    val Success: Color,
    val Warning: Color,
    val Danger: Color,
    // Desktop shell/chrome roles. Dark keeps the existing handoff values
    // byte-for-byte; light resolves from the light token family instead of
    // leaving title bars/rails/side panels as hard-coded dark islands (#910).
    val ShellTitleBar: Color,
    val ShellRail: Color,
    val ShellPanel: Color,
    val ShellTitleText: Color,
    val ShellSubtitleText: Color,
    val ShellInactiveText: Color,
    val ShellLiveText: Color,
    val isDark: Boolean,
)

// De to paletter LAESER nu KalivTokens, som scripts/design_tokens.py genererer
// fra assets/design/kaliv-ui-guide/kaliv-ui-tokens.json. Foer 27/7-2026 stod
// vaerdierne som literaler her, med en kommentar om at "change the tokens file
// and re-apply" -- men re-apply var manuelt, og et haandtastet hex kan drive
// fra sin kilde uden at nogen opdager det.
//
// CodeSurface og light onPrimary staar stadig som literaler: de findes ikke i
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
    ShellTitleBar = Color(0x990B0A09),
    ShellRail = Color(0x8C14110E),
    ShellPanel = Color(0x8014110E),
    ShellTitleText = Color(0xFFE9DFCE),
    // Preserve the old dark subtitle bytes (#6F665C) without duplicating a
    // token literal in Brand.kt; Light.muted is the generated owner of them.
    ShellSubtitleText = KalivTokens.Light.muted,
    ShellInactiveText = Color(0xFFC3B8A8),
    ShellLiveText = Color(0xFFD09A55),
    isDark = true,
)

// Light mode must use the light-specific contrast roles. The old mapping reused
// brand.bronze/gold/highlight and global semantic colours; those are explicitly
// deprecated by the token source and, for example, brand.gold is only ~2.3:1
// against the light canvas. Light.accent is deliberately darker and clears the
// normal-text contrast boundary while preserving the same warm Kaliv hue.
val KalivLight = KalivColors(
    Graphite = KalivTokens.Light.canvas,
    Surface = KalivTokens.Light.surface,
    SurfaceHigh = KalivTokens.Light.elevated,
    CodeSurface = Color(0xFFEDE7DA),
    Border = KalivTokens.Light.border,
    Signal = KalivTokens.Light.accent,
    Amber = KalivTokens.Light.accent,
    Highlight = KalivTokens.Light.accentSoft,
    TextHigh = KalivTokens.Light.text,
    TextMuted = KalivTokens.Light.muted,
    Success = KalivTokens.Light.ok,
    Warning = KalivTokens.Light.warn,
    Danger = KalivTokens.Light.danger,
    ShellTitleBar = KalivTokens.Light.surfaceDim,
    ShellRail = KalivTokens.Light.surface,
    ShellPanel = KalivTokens.Light.surface,
    ShellTitleText = KalivTokens.Light.text,
    ShellSubtitleText = KalivTokens.Light.muted,
    ShellInactiveText = KalivTokens.Light.muted,
    ShellLiveText = KalivTokens.Light.warn,
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
        primary = c.Signal, onPrimary = Color(0xFFF7F4EF),
        secondary = c.Amber, background = c.Graphite, onBackground = c.TextHigh,
        surface = c.Surface, onSurface = c.TextHigh,
        surfaceVariant = c.SurfaceHigh, onSurfaceVariant = c.TextMuted,
        outline = c.Border, error = c.Danger,
        // Keep every Material container in the same warm parchment family.
        // Leaving these at M3 defaults introduces a lavender cast in light mode.
        surfaceContainerLowest = c.Graphite,
        surfaceContainer = c.SurfaceHigh, surfaceContainerHigh = c.SurfaceHigh,
        surfaceContainerHighest = c.SurfaceHigh, surfaceContainerLow = c.Surface,
    )
    CompositionLocalProvider(LocalKalivColors provides c) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
