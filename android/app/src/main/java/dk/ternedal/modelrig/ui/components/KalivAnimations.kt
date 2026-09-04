package dk.ternedal.modelrig.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.StartOffset
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens

/**
 * Animations-byggesten (DDR-001, fase 1). Specs fra mockuppen, skaleret efter
 * B2: cursor 8,5x18dp med 1s trinvis blink; equalizer-soejler scaleY
 * 0,32 -> 1,0 over 1,4s med 90ms forskydning pr. soejle.
 *
 * Screenshot-tests fanger foerste frame (animationer er frosne under
 * Roborazzi-capture), saa baseline viser hviletilstanden.
 */

/** Streaming-cursor: blinker trinvis (ikke fade) i accent-farven. */
@Composable
fun StreamingCursor(modifier: Modifier = Modifier) {
    val transition = rememberInfiniteTransition(label = "cursorBlink")
    val alpha by transition.animateFloat(
        initialValue = 1f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = keyframes {
                durationMillis = 1000
                1f at 0
                1f at 499
                0f at 500
                0f at 999
            },
        ),
        label = "cursorAlpha",
    )
    Box(
        modifier
            .size(
                width = KalivTokens.Layout.cursorWidth,
                height = KalivTokens.Layout.cursorHeight,
            )
            .graphicsLayer { this.alpha = alpha }
            .background(KalivTheme.colors.accent, RoundedCornerShape(2.dp)),
    )
}

/** Stemme-equalizer: [barCount] soejler i accent, staggeret puls. */
@Composable
fun EqualizerBars(
    modifier: Modifier = Modifier,
    barCount: Int = 12,
    color: androidx.compose.ui.graphics.Color? = null,
    barHeight: androidx.compose.ui.unit.Dp? = null,
    profile: List<Float>? = null,
) {
    val barColor = color ?: KalivTheme.colors.accent
    val h = barHeight ?: KalivTokens.Spacing.s6
    val transition = rememberInfiniteTransition(label = "equalizer")
    Row(
        modifier = modifier.height(h),
        horizontalArrangement = Arrangement.spacedBy(3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        repeat(barCount) { index ->
            val scale by transition.animateFloat(
                initialValue = 0.32f,
                targetValue = 1f,
                animationSpec = infiniteRepeatable(
                    animation = tween(durationMillis = 1400, easing = LinearEasing),
                    repeatMode = RepeatMode.Reverse,
                    initialStartOffset = StartOffset(index * 90),
                ),
                label = "bar$index",
            )
            Box(
                Modifier
                    .width(3.dp)
                    .height(if (profile != null) h * profile[index % profile.size] else h)
                    .graphicsLayer { scaleY = scale }
                    .background(
                        barColor,
                        RoundedCornerShape(KalivTokens.Radius.round),
                    ),
            )
        }
    }
}
