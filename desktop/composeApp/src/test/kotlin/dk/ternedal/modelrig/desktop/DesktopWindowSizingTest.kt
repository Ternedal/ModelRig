package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class DesktopWindowSizingTest {
    @Test
    fun normalProductKeepsDesignStartSizeAndUsableMinimum() {
        val sizing = desktopWindowSizing(
            showTasks = false,
            experimental = false,
            forceNormalChat = false,
        )

        assertEquals(1240, sizing.initialWidthDp)
        assertEquals(820, sizing.initialHeightDp)
        assertEquals(1100, sizing.minimumWidthDp)
        assertEquals(700, sizing.minimumHeightDp)
        assertTrue(sizing.initialWidthDp >= sizing.minimumWidthDp)
        assertTrue(sizing.initialHeightDp >= sizing.minimumHeightDp)
    }

    @Test
    fun awtMinimumUsesLogicalUnitsWithoutDensityMultiplication() {
        val normal = desktopWindowSizing(
            showTasks = false,
            experimental = false,
            forceNormalChat = false,
        ).awtMinimumSize()
        val experimental = desktopWindowSizing(
            showTasks = false,
            experimental = true,
            forceNormalChat = false,
        ).awtMinimumSize()

        assertEquals(1100, normal.width)
        assertEquals(700, normal.height)
        assertEquals(760, experimental.width)
        assertEquals(600, experimental.height)
    }

    @Test
    fun taskSurfaceMayBeNarrowerWithoutUsingExperimentalMinimum() {
        val sizing = desktopWindowSizing(
            showTasks = true,
            experimental = false,
            forceNormalChat = false,
        )

        assertEquals(1100, sizing.initialWidthDp)
        assertEquals(820, sizing.initialHeightDp)
        assertEquals(960, sizing.minimumWidthDp)
        assertEquals(660, sizing.minimumHeightDp)
    }

    @Test
    fun experimentalEvidenceSurfaceRetainsNarrowFootprint() {
        val sizing = desktopWindowSizing(
            showTasks = false,
            experimental = true,
            forceNormalChat = false,
        )

        assertEquals(900, sizing.initialWidthDp)
        assertEquals(820, sizing.initialHeightDp)
        assertEquals(760, sizing.minimumWidthDp)
        assertEquals(600, sizing.minimumHeightDp)
    }

    @Test
    fun normalChatFallbackOverridesExperimentalSizing() {
        val sizing = desktopWindowSizing(
            showTasks = false,
            experimental = true,
            forceNormalChat = true,
        )

        assertEquals(1240, sizing.initialWidthDp)
        assertEquals(1100, sizing.minimumWidthDp)
        assertEquals(700, sizing.minimumHeightDp)
    }

    @Test
    fun taskSurfaceWinsUntilItActuallyFallsBackToNormalChat() {
        val sizing = desktopWindowSizing(
            showTasks = true,
            experimental = true,
            forceNormalChat = true,
        )

        assertEquals(1100, sizing.initialWidthDp)
        assertEquals(960, sizing.minimumWidthDp)
    }
}
