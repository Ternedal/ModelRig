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
    val Signal: Color,       // brand.bronze — actions/links
    val Amber: Color,        // brand.gold — accents
    val Highlight: Color,    // brand.highlight
    val TextHigh: Color,
    val TextMuted: Color,
    val Success: Color,
    val Warning: Color,
    val Danger: Color,
    val isDark: Boolean,
)

// Values sourced from the approved design guide (kaliv-ui-tokens.json v1.0,
// assets/design/kaliv-ui-guide/) -- 12/7-2026. Do not tweak by eye; change the
// tokens file and re-apply.
val KalivDark = KalivColors(
    Graphite = Color(0xFF0B0A09),
    Surface = Color(0xFF171411),
    SurfaceHigh = Color(0xFF211B16),
    CodeSurface = Color(0xFF14100C),
    Border = Color(0xFF4B3925),
    Signal = Color(0xFF9A7136),
    Amber = Color(0xFFC69A4B),
    Highlight = Color(0xFFD8B66B),
    TextHigh = Color(0xFFF3EFE6),
    TextMuted = Color(0xFFA89D90),
    Success = Color(0xFF6F8A63),
    Warning = Color(0xFFB9823F),
    Danger = Color(0xFF9C564C),
    isDark = true,
)

val KalivLight = KalivColors(
    Graphite = Color(0xFFF7F3EC),
    Surface = Color(0xFFEDE5D8),
    SurfaceHigh = Color(0xFFFFFDF9),
    CodeSurface = Color(0xFFEDE7DA),
    Border = Color(0xFFD7C9B4),
    Signal = Color(0xFF9A7136),
    Amber = Color(0xFFC69A4B),
    Highlight = Color(0xFFD8B66B),
    TextHigh = Color(0xFF231E19),
    TextMuted = Color(0xFF776D62),
    Success = Color(0xFF6F8A63),
    Warning = Color(0xFFB9823F),
    Danger = Color(0xFF9C564C),
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
        surface = c.Surface, onSurface = c.TextHigh, error = c.Danger,
        surfaceContainer = c.SurfaceHigh, surfaceContainerHigh = c.SurfaceHigh,
        surfaceContainerHighest = c.SurfaceHigh, surfaceContainerLow = c.Surface,
    )
    CompositionLocalProvider(LocalKalivColors provides c) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
