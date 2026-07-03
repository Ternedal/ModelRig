package dk.ternedal.modelrig.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// ModelRig brand tokens — handoff v3. Sapphire + champagne are the VERIFIED brand
// colours (sampled from the brand board). Var names kept for compatibility; the
// mapping to brand tokens:
//   Graphite            = color.bg.obsidian     (deepest background)
//   GraphiteSurface     = color.bg.graphite     (main surface / panels)
//   GraphiteSurfaceHigh = elevated surface      (cards, chips)
//   Signal              = color.primary.sapphire (actions / focus)  [verified #306CFC]
//   Amber               = color.accent.champagne (premium accent)   [verified #DEC08A]
//   TextHigh            = color.text.cloud
//   TextMuted           = muted text
//   Danger/Hairline/CodeSurface as named.
val Graphite = Color(0xFF060810)
val GraphiteSurface = Color(0xFF0F1520)
val GraphiteSurfaceHigh = Color(0xFF19212E)
val CodeSurface = Color(0xFF0A0E16)
val Signal = Color(0xFF306CFC)
val SapphireDeep = Color(0xFF1C3A80)
val Amber = Color(0xFFDEC08A)
val TextHigh = Color(0xFFEEF1F6)
val TextMuted = Color(0xFF8A94A6)
val Success = Color(0xFF3FAE66)
val Danger = Color(0xFFE5534B)
val Hairline = Color(0xFF212B3A)

private val ModelRigColors = darkColorScheme(
    primary = Signal,
    onPrimary = Color.White,
    secondary = Amber,
    onSecondary = Graphite,
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
    MaterialTheme(colorScheme = ModelRigColors, typography = ModelRigTypography, content = content)
}
