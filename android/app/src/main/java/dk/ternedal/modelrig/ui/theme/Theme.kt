package dk.ternedal.modelrig.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Brand palette — shared with the desktop client for a consistent look across
// clients. Dark-first (matches how the app is actually used).
val Graphite = Color(0xFF0E1116)
val GraphiteSurface = Color(0xFF171B22)
val GraphiteSurfaceHigh = Color(0xFF1F242D)
val CodeSurface = Color(0xFF0B0E13)
val Signal = Color(0xFF4C8DFF)
val Amber = Color(0xFFF5A524)
val TextHigh = Color(0xFFE6E9EF)
val TextMuted = Color(0xFF9AA4B2)
val Danger = Color(0xFFF2555A)
val Hairline = Color(0xFF262C36)

private val ModelRigColors = darkColorScheme(
    primary = Signal,
    onPrimary = Graphite,
    secondary = Amber,
    background = Graphite,
    onBackground = TextHigh,
    surface = GraphiteSurface,
    onSurface = TextHigh,
    surfaceVariant = GraphiteSurfaceHigh,
    onSurfaceVariant = TextMuted,
    error = Danger,
    outline = Hairline,
)

private val ModelRigTypography = Typography(
    titleLarge = TextStyle(fontSize = 20.sp, fontWeight = FontWeight.Bold, lineHeight = 26.sp),
    bodyLarge = TextStyle(fontSize = 15.sp, lineHeight = 22.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
    labelSmall = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Medium),
)

@Composable
fun ModelRigTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = ModelRigColors,
        typography = ModelRigTypography,
        content = content,
    )
}
