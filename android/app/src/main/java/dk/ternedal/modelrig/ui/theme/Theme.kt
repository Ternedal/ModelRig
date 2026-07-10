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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Kaliv brand colours -- from the QA-approved brand package
// (06_COLOR_SYSTEM/kaliv_design_tokens.json). Two full palettes now: dark and
// light. The app carried only a hardcoded dark scheme before; this makes the
// palette a theme lookup so both modes are real, not a tint.
//
// The eight semantic slots below do NOT map cleanly onto Material3's role names
// (no Material slot for "hairline", or for a distinct assistant-bubble surface),
// so rather than flatten the brand into Material's vocabulary and lose meaning,
// the names live in KalivColors and reach call sites as KalivTheme.colors.X.
// Material still gets a derived scheme underneath, for the components (dialogs,
// switches) that read MaterialTheme directly.
//
// CONTRAST, measured not assumed. Ember bronze #8B6B3D is the one accent shared
// by both modes. White on it is ~3.0:1 -- below WCAG AA for body text -- so text
// ON bronze is the mode's deep ink (dark: deep black; light: charcoal), never
// white. That is why the user bubble reads dark-on-bronze.

/** Every colour the UI names, so a palette is one object and a mode is one instance. */
data class KalivColors(
    val background: Color,
    val surface: Color,
    val surfaceHigh: Color,
    val codeSurface: Color,
    val signal: Color,
    val signalPressed: Color,
    val amber: Color,
    val textHigh: Color,
    val textMuted: Color,
    val onSignal: Color,
    val success: Color,
    val danger: Color,
    val hairline: Color,
    val isDark: Boolean,
)

// -- Dark palette (tokens "dark") --------------------------------------------
val KalivDarkColors = KalivColors(
    background = Color(0xFF0B0A09),
    surface = Color(0xFF1B1612),
    surfaceHigh = Color(0xFF2A1E14),
    codeSurface = Color(0xFF080706),
    signal = Color(0xFF8B6B3D),
    signalPressed = Color(0xFF6E5330),
    amber = Color(0xFFC8A864),
    textHigh = Color(0xFFF3EFE6),
    textMuted = Color(0xFFA89A82),
    onSignal = Color(0xFF0B0A09),
    success = Color(0xFF6E9E5E),
    danger = Color(0xFFCF6A5C),
    hairline = Color(0xFF3A2A1F),
    isDark = true,
)

// -- Light palette (tokens "light") ------------------------------------------
val KalivLightColors = KalivColors(
    background = Color(0xFFF7F4EF),
    surface = Color(0xFFEFEAE0),
    surfaceHigh = Color(0xFFE6DFD2),
    codeSurface = Color(0xFFEAE3D5),
    signal = Color(0xFF8B6B3D),
    signalPressed = Color(0xFF6E5330),
    amber = Color(0xFFB69B73),
    textHigh = Color(0xFF2A2118),
    textMuted = Color(0xFF5A4831),
    onSignal = Color(0xFF2A2118),
    success = Color(0xFF4F7A41),
    danger = Color(0xFFA33529),
    hairline = Color(0xFFCDBFA6),
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
            error = c.danger, outline = c.hairline,
        )
    } else {
        lightColorScheme(
            primary = c.signal, onPrimary = c.onSignal,
            secondary = c.amber, onSecondary = c.onSignal,
            background = c.background, onBackground = c.textHigh,
            surface = c.surface, onSurface = c.textHigh,
            surfaceVariant = c.surfaceHigh, onSurfaceVariant = c.textMuted,
            error = c.danger, outline = c.hairline,
        )
    }

private val Display = FontFamily.Serif

private val KalivTypography = Typography(
    titleLarge = TextStyle(
        fontFamily = Display,
        fontSize = 20.sp, fontWeight = FontWeight.Bold, lineHeight = 26.sp,
    ),
    bodyLarge = TextStyle(fontSize = 15.sp, lineHeight = 22.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
    labelSmall = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Medium),
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
            typography = KalivTypography,
            content = content,
        )
    }
}
