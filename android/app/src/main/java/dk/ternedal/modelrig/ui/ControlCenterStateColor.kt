package dk.ternedal.modelrig.ui

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import dk.ternedal.modelrig.ui.theme.KalivTheme

/**
 * Existing Control Center state-color mapping, kept package-local so the
 * history UI integration can reuse the unchanged screen without another
 * whole-file rewrite through the contents API.
 */
@Composable
internal fun stateColor(state: String): Color = when (state) {
    "healthy" -> KalivTheme.colors.signal
    "unavailable" -> KalivTheme.colors.danger
    "attention", "fallback" -> KalivTheme.colors.textHigh
    else -> KalivTheme.colors.textMuted
}
