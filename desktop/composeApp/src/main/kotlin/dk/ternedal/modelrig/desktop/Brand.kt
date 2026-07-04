package dk.ternedal.modelrig.desktop

import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.graphics.Color

/**
 * ModelRig brand tokens — handoff v3, VERIFIED (sampled from the brand board,
 * same values as Android's ui/theme/Theme.kt). This replaces an earlier
 * invented palette that was never corrected here — see ROADMAP.md §4 pt. 5.
 */
object Brand {
    val Graphite = Color(0xFF060810)
    val Surface = Color(0xFF0F1520)
    val SurfaceHigh = Color(0xFF19212E)
    val Signal = Color(0xFF306CFC)   // sapphire — actions/focus
    val Amber = Color(0xFFDEC08A)    // champagne — accent
    val TextHigh = Color(0xFFEEF1F6)
    val TextMuted = Color(0xFF8A94A6)
    val Danger = Color(0xFFE5534B)

    val Colors = darkColorScheme(
        primary = Signal,
        onPrimary = Color.White,
        secondary = Amber,
        onSecondary = Graphite,
        background = Graphite,
        onBackground = TextHigh,
        surface = Surface,
        onSurface = TextHigh,
        surfaceVariant = SurfaceHigh,
        error = Danger,
    )
}
