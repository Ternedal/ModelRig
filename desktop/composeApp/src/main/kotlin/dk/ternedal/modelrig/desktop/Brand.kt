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
    val Graphite: Color,     // window background
    val Surface: Color,      // cards/panels
    val SurfaceHigh: Color,  // raised surfaces (menus, code)
    val CodeSurface: Color,
    val Signal: Color,       // bronze — actions/links
    val Amber: Color,        // gold — accents
    val TextHigh: Color,
    val TextMuted: Color,
    val Danger: Color,
    val isDark: Boolean,
)

val KalivDark = KalivColors(
    Graphite = Color(0xFF0B0A09),
    Surface = Color(0xFF1B1612),
    SurfaceHigh = Color(0xFF2A1E14),
    CodeSurface = Color(0xFF14100C),
    Signal = Color(0xFF8B6B3D),
    Amber = Color(0xFFC8A864),
    TextHigh = Color(0xFFF3EFE6),
    TextMuted = Color(0xFF9C917F),
    Danger = Color(0xFFE5534B),
    isDark = true,
)

val KalivLight = KalivColors(
    Graphite = Color(0xFFF7F4EF),
    Surface = Color(0xFFEFEAE0),
    SurfaceHigh = Color(0xFFE6DFD2),   // parchment
    CodeSurface = Color(0xFFEDE7DA),
    Signal = Color(0xFF8B6B3D),
    Amber = Color(0xFF8B6B3D),         // gold reads poorly on light; bronze carries accents
    TextHigh = Color(0xFF221B12),      // dark ink, not white — contrast measured on Android
    TextMuted = Color(0xFF6B6053),
    Danger = Color(0xFFB3372F),
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
