package dk.ternedal.modelrig.desktop

import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.graphics.Color

/** ModelRig brand tokens: graphite base, electric "signal" accent, amber for cloud/warn. */
object Brand {
    val Graphite = Color(0xFF0E1116)
    val Surface = Color(0xFF171B22)
    val SurfaceHigh = Color(0xFF1F242D)
    val Signal = Color(0xFF4C8DFF)
    val Amber = Color(0xFFF5A524)
    val TextHigh = Color(0xFFE6E9EF)
    val TextMuted = Color(0xFF9AA4B2)
    val Danger = Color(0xFFF2555A)

    val Colors = darkColorScheme(
        primary = Signal,
        onPrimary = Graphite,
        secondary = Amber,
        background = Graphite,
        onBackground = TextHigh,
        surface = Surface,
        onSurface = TextHigh,
        surfaceVariant = SurfaceHigh,
        error = Danger,
    )
}
