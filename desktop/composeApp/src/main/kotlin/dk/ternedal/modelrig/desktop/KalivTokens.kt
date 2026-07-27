// GENERERET af scripts/design_tokens.py fra
// assets/design/kaliv-ui-guide/kaliv-ui-tokens.json -- rediger ikke i haanden.
// Aendr JSON'en og koer generatoren; CI fejler paa drift.

package dk.ternedal.modelrig.desktop

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Single source of truth for the Kaliv design tokens. */
object KalivTokens {
    const val VERSION: String = "1.0"
    val BASE_GRID: Dp = 8.dp

    object Dark {
        val canvas: Color = Color(0xFF0B0A09)
        val surface: Color = Color(0xFF171411)
        val elevated: Color = Color(0xFF211B16)
        val border: Color = Color(0xFF4B3925)
        val text: Color = Color(0xFFF3EFE6)
        val muted: Color = Color(0xFFA89D90)
    }

    object Light {
        val canvas: Color = Color(0xFFF7F3EC)
        val surface: Color = Color(0xFFEDE5D8)
        val elevated: Color = Color(0xFFFFFDF9)
        val border: Color = Color(0xFFD7C9B4)
        val text: Color = Color(0xFF231E19)
        val muted: Color = Color(0xFF6F665C)
    }

    object Brand {
        val bronze: Color = Color(0xFF9A7136)
        val gold: Color = Color(0xFFC69A4B)
        val highlight: Color = Color(0xFFD8B66B)
    }

    object Semantic {
        val success: Color = Color(0xFF6F8A63)
        val warning: Color = Color(0xFFB9823F)
        val danger: Color = Color(0xFF9C564C)
    }

    object Spacing {
        val s1: Dp = 4.dp
        val s2: Dp = 8.dp
        val s3: Dp = 12.dp
        val s4: Dp = 16.dp
        val s5: Dp = 20.dp
        val s6: Dp = 24.dp
        val s8: Dp = 32.dp
        val s10: Dp = 40.dp
        val s12: Dp = 48.dp
    }

    object Radius {
        val control: Dp = 14.dp
        val button: Dp = 16.dp
        val bubble: Dp = 16.dp
        val panel: Dp = 20.dp
        val round: Dp = 999.dp
    }

    object Layout {
        val desktopPadding: Dp = 24.dp
        val headerHeight: Dp = 96.dp
        val controlHeight: Dp = 40.dp
        val composerMinHeight: Dp = 88.dp
        val assistantMaxWidth: Dp = 780.dp
        val userMaxWidth: Dp = 620.dp
    }

    object Motion {
        const val fastMs: Int = 140
        const val normalMs: Int = 180
        const val panelMs: Int = 220
        const val thinkingLoopMs: Int = 1280
    }

    object Typography {
        object Body {
            const val family: String = "Inter"
            val size: TextUnit = 16.sp
            const val lineHeight: Float = 1.55f
        }
        object Control {
            const val family: String = "Inter"
            const val weight: Int = 500
            val size: TextUnit = 14.sp
        }
        object Meta {
            const val family: String = "Inter"
            const val weight: Int = 500
            val size: TextUnit = 12.sp
        }
        object Wordmark {
            const val family: String = "EB Garamond"
            val size: TextUnit = 30.sp
            const val trackingEm: Float = 0.22f
        }
    }
}
