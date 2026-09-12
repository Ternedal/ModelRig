package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class KalivComputerUsePolicyTest {
    @Test
    fun unavailableDesktopComputerUseClaimsNoExecutionAuthority() {
        val presentation = presentComputerUse()
        assertFalse(presentation.executionEnabled)
        assertFalse(presentation.showLiveViewport)
        assertFalse(presentation.showApproval)
        assertFalse(presentation.claimsLiveControl)
    }

    @Test
    fun unavailableCopyIsExplicitAndDoesNotPretendToBeLive() {
        val presentation = presentComputerUse()
        val copy = (presentation.title + " " + presentation.detail).lowercase()
        assertTrue("ikke tilgængelig" in copy)
        assertTrue("ikke koblet" in copy)
        assertFalse("kaliv styrer skærmen" in copy)
        assertFalse("arbejde live" in copy)
        assertFalse("fuldført" in copy)
    }
}
