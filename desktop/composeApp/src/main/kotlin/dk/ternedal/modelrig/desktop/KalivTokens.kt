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
    const val VERSION: String = "2.0"
    val BASE_GRID: Dp = 8.dp

    object Dark {
        val canvas: Color = Color(0xFF0B0A09)
        val surface: Color = Color(0xFF171411)
        val elevated: Color = Color(0xFF211B16)
        val border: Color = Color(0xFF2A2521)
        val text: Color = Color(0xFFF3EFE6)
        val muted: Color = Color(0xFFA89D90)
        val surfaceDim: Color = Color(0xFF14110E)
        val sheet: Color = Color(0xFF120E0A)
        val divider: Color = Color(0xFF1C1611)
        val userBubble: Color = Color(0xFF211D18)
        val userBubbleBorder: Color = Color(0xFF2F2A24)
        val faint: Color = Color(0xFF8A8073)
        val caps: Color = Color(0xFF857A6C)
        val accent: Color = Color(0xFFD4AB52)
        val ok: Color = Color(0xFF77836D)
        val warn: Color = Color(0xFFA08050)
        val danger: Color = Color(0xFFC96B5D)
        val scrim: Color = Color(0xA3050403)
        val textSoft: Color = Color(0xFFE9DFCA)
        val textBody: Color = Color(0xFFEEE6D8)
        val userBubbleText: Color = Color(0xFFECE3D5)
        val accentSoft: Color = Color(0xFFE2C06A)
        val selectedTint: Color = Color(0xFF191410)
    }

    object Light {
        val canvas: Color = Color(0xFFF7F3EC)
        val surface: Color = Color(0xFFFFFDF9)
        val elevated: Color = Color(0xFFEDE5D8)
        val border: Color = Color(0xFFD7C9B4)
        val text: Color = Color(0xFF231E19)
        val muted: Color = Color(0xFF6F665C)
        val surfaceDim: Color = Color(0xFFEFE8DB)
        val sheet: Color = Color(0xFFFFFDF9)
        val divider: Color = Color(0xFFE3DACB)
        val userBubble: Color = Color(0xFFEDE5D8)
        val userBubbleBorder: Color = Color(0xFFDCD2C2)
        val faint: Color = Color(0xFF776D62)
        val caps: Color = Color(0xFF776D62)
        val accent: Color = Color(0xFF7E621C)
        val ok: Color = Color(0xFF5F6B52)
        val warn: Color = Color(0xFF957620)
        val danger: Color = Color(0xFFA8503F)
        val scrim: Color = Color(0x52231E19)
        val textSoft: Color = Color(0xFF231E19)
        val textBody: Color = Color(0xFF231E19)
        val userBubbleText: Color = Color(0xFF231E19)
        val accentSoft: Color = Color(0xFF7E621C)
        val selectedTint: Color = Color(0xFFF5EFE4)
    }

    object Gold {
        val fill: Color = Color(0xFFB08A3E)
        val on: Color = Color(0xFF2B1C05)
        val tint: Color = Color(0x29D4AB52)
    }

    object Brand {
        val bronze: Color = Color(0xFF9A7136)
        val gold: Color = Color(0xFFC69A4B)
        val highlight: Color = Color(0xFFD8B66B)
    }

    object Semantic {
        val success: Color = Color(0xFF6F8A63)
        val warning: Color = Color(0xFFAA773A)
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
        val card: Dp = 15.dp
        val popover: Dp = 16.dp
        val bubbleUser: Dp = 17.dp
        val composer: Dp = 20.dp
        val sheet: Dp = 22.dp
    }

    object Layout {
        val desktopPadding: Dp = 24.dp
        val headerHeight: Dp = 96.dp
        val controlHeight: Dp = 40.dp
        val composerMinHeight: Dp = 88.dp
        val assistantMaxWidth: Dp = 780.dp
        val userMaxWidth: Dp = 620.dp
        val fabSend: Dp = 46.dp
        val micButton: Dp = 90.dp
        val ankhEmpty: Dp = 78.dp
        val ankhTopbar: Dp = 40.dp
        val switchTrackWidth: Dp = 51.dp
        val switchTrackHeight: Dp = 29.dp
        val switchKnob: Dp = 24.dp
        val dragHandleWidth: Dp = 46.dp
        val dragHandleHeight: Dp = 5.dp
        val cursorWidth: Dp = 8.5.dp
        val cursorHeight: Dp = 18.dp
        val hairline: Dp = 1.dp
        val minTouch: Dp = 48.dp
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
        object Title {
            const val family: String = "EB Garamond"
            const val weight: Int = 500
            val size: TextUnit = 26.sp
            const val trackingEm: Float = 0.01f
        }
        object Sheettitle {
            const val family: String = "EB Garamond"
            const val weight: Int = 500
            val size: TextUnit = 24.sp
            const val trackingEm: Float = 0.01f
        }
        object Rowtitle {
            const val family: String = "Inter"
            const val weight: Int = 600
            val size: TextUnit = 16.5.sp
        }
        object Secondary {
            const val family: String = "Inter"
            const val weight: Int = 400
            val size: TextUnit = 13.5.sp
        }
        object Sub {
            const val family: String = "Inter"
            const val weight: Int = 400
            val size: TextUnit = 13.sp
        }
        object Capslabel {
            const val family: String = "Inter"
            const val weight: Int = 700
            val size: TextUnit = 11.5.sp
            const val trackingEm: Float = 0.18f
        }
        object Brandline {
            const val family: String = "Inter"
            const val weight: Int = 700
            val size: TextUnit = 12.sp
            const val trackingEm: Float = 0.2f
        }
        object Emptytitle {
            const val family: String = "EB Garamond"
            const val weight: Int = 600
            val size: TextUnit = 30.5.sp
            const val lineHeightSp: Int = 38
        }
        object Wordmarkmobile {
            const val family: String = "EB Garamond"
            const val weight: Int = 600
            val size: TextUnit = 23.sp
            const val trackingEm: Float = 0.22f
        }
        object Chip {
            const val family: String = "Inter"
            const val weight: Int = 500
            val size: TextUnit = 15.sp
        }
    }
}
