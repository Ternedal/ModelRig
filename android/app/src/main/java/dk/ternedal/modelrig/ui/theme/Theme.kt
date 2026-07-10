package dk.ternedal.modelrig.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Kaliv brand tokens -- from the delivered brand package
// (06_PALETTE_AND_TYPE/kaliv_palette.json). Replaces the old sapphire/champagne
// ModelRig palette: the app is Kaliv now, and the brand is charred, tactile,
// branded-seal -- not blue. Variable names kept so nothing downstream changes.
//
//   Graphite            = charred black   #0B0B0D  (deepest background)
//   GraphiteSurface     = dark walnut     #1A120D  (main surface / panels)
//   GraphiteSurfaceHigh = ember shadow    #241A13  (cards, chips, assistant bubbles)
//   Signal              = ember bronze    #B6803A  (actions, focus, user bubbles)
//   Amber               = ember orange    #C46A2A  (accent: cloud, warmth)
//   TextHigh            = muted ivory     #E7DCC9
//   TextMuted           = ash ivory       #9A8B78  (5.6:1 on walnut)
//   Hairline            = smoke brown     #3A2A1F
//
// CONTRAST, measured rather than assumed: white on ember bronze is 3.42:1 --
// below WCAG AA for body text. Charred black on bronze is 5.75:1. So onPrimary
// is charred black, NOT white. That is why the user bubble and the pill chips
// now read dark-on-bronze instead of the old white-on-sapphire.
val Graphite = Color(0xFF0B0B0D)
val GraphiteSurface = Color(0xFF1A120D)
val GraphiteSurfaceHigh = Color(0xFF241A13)
val CodeSurface = Color(0xFF08080A)
val Signal = Color(0xFFB6803A)
val SapphireDeep = Color(0xFF6E4A1F)  // name kept; now deep ember (pressed/border states)
val Amber = Color(0xFFC46A2A)
val TextHigh = Color(0xFFE7DCC9)
val TextMuted = Color(0xFF9A8B78)
val Success = Color(0xFF6E9E5E)  // moss, not the old clinical green
val Danger = Color(0xFFC4453A)   // ember red: still unmistakably an error
val Hairline = Color(0xFF3A2A1F)

/** Text/icon colour that belongs ON [Signal] or [Amber]. Never white: see above. */
val OnEmber = Graphite

private val KalivColors = darkColorScheme(
    primary = Signal,
    onPrimary = OnEmber,
    secondary = Amber,
    onSecondary = OnEmber,
    background = Graphite,
    onBackground = TextHigh,
    surface = GraphiteSurface,
    onSurface = TextHigh,
    surfaceVariant = GraphiteSurfaceHigh,
    onSurfaceVariant = TextMuted,
    error = Danger,
    outline = Hairline,
)

// The brand specifies Cinzel / Cormorant Garamond for display and Montserrat
// for UI. No font files shipped in the package, so rather than bundling
// something that isn't the brand, display text uses the platform serif -- which
// carries the same engraved, carved-in feel -- and body stays on the system
// sans. Drop the real faces into res/font and set them here to finish the job.
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

@Composable
fun ModelRigTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = KalivColors, typography = KalivTypography, content = content)
}
