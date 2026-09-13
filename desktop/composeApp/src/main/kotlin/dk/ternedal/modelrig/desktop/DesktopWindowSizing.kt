package dk.ternedal.modelrig.desktop

import java.awt.Dimension

/**
 * Desktop window sizing policy.
 *
 * The product shell has intentionally fixed chrome (rails/context/action log)
 * and does not yet have a compact breakpoint. Until it does, allowing the
 * native window to shrink without a floor makes the flexible work area
 * structurally unusable (#779 item 8 / #916).
 *
 * Developer/evidence surfaces remain deliberately narrower than the normal
 * product. `forceNormalChat` always restores the normal-product policy.
 */
internal data class DesktopWindowSizing(
    val initialWidthDp: Int,
    val initialHeightDp: Int,
    val minimumWidthDp: Int,
    val minimumHeightDp: Int,
)

/**
 * AWT top-level window bounds/minimum sizes use logical screen coordinates.
 * Compose desktop Dp window sizes resolve to the same logical coordinate
 * space, so applying LocalDensity here would scale the minimum twice on HiDPI.
 */
internal fun DesktopWindowSizing.awtMinimumSize(): Dimension = Dimension(
    minimumWidthDp,
    minimumHeightDp,
)

internal fun desktopWindowSizing(
    showTasks: Boolean,
    experimental: Boolean,
    forceNormalChat: Boolean,
): DesktopWindowSizing = when {
    showTasks -> DesktopWindowSizing(
        initialWidthDp = 1100,
        initialHeightDp = 820,
        minimumWidthDp = 960,
        minimumHeightDp = 660,
    )

    experimental && !forceNormalChat -> DesktopWindowSizing(
        initialWidthDp = 900,
        initialHeightDp = 820,
        minimumWidthDp = 760,
        minimumHeightDp = 600,
    )

    else -> DesktopWindowSizing(
        initialWidthDp = 1240,
        initialHeightDp = 820,
        minimumWidthDp = 1100,
        minimumHeightDp = 700,
    )
}
