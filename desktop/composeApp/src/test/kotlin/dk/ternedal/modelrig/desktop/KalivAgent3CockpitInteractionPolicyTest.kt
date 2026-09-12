package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class KalivAgent3CockpitInteractionPolicyTest {
    @Test
    fun idleCockpitAllowsPreview() {
        assertTrue(canAgent3CockpitPreview("undersøg status", busy = false, hasRun = false))
        val p = presentAgent3CockpitInteraction(busy = false, runState = null)
        assertTrue(p.composerEnabled)
        assertFalse(p.stopPlanEnabled)
    }

    @Test
    fun busyCockpitBlocksPreview() {
        assertFalse(canAgent3CockpitPreview("undersøg status", busy = true, hasRun = false))
        val p = presentAgent3CockpitInteraction(busy = true, runState = null)
        assertFalse(p.composerEnabled)
        assertFalse(p.stopPlanEnabled)
    }

    @Test
    fun activeRunBlocksAnotherPreviewAndNeedsServerStopAuthority() {
        assertFalse(canAgent3CockpitPreview("ny opgave", busy = false, hasRun = true))
        val blocked = presentAgent3CockpitInteraction(
            busy = false,
            runState = "running",
            planCanRequestStop = false,
        )
        assertFalse(blocked.composerEnabled)
        assertFalse(blocked.stopPlanEnabled)
        assertFalse(blocked.clearTerminalRunEnabled)

        val allowed = presentAgent3CockpitInteraction(
            busy = false,
            runState = "running",
            planCanRequestStop = true,
        )
        assertTrue(allowed.stopPlanEnabled)
    }

    @Test
    fun missingTerminationAuthorityFailsClosed() {
        val p = presentAgent3CockpitInteraction(
            busy = false,
            runState = "running",
            planCanRequestStop = null,
        )
        assertFalse(p.stopPlanEnabled)
    }

    @Test
    fun awaitingConfirmationRunCannotBeHiddenByNewPreviewOrLocalClear() {
        assertFalse(canAgent3CockpitPreview("ny opgave", busy = false, hasRun = true))
        val p = presentAgent3CockpitInteraction(
            busy = false,
            runState = "awaiting_confirmation",
            planCanRequestStop = false,
        )
        assertFalse(p.composerEnabled)
        assertFalse(p.stopPlanEnabled)
        assertFalse(p.clearTerminalRunEnabled)
    }

    @Test
    fun busyStateBlocksOtherwiseAuthorizedStop() {
        val p = presentAgent3CockpitInteraction(
            busy = true,
            runState = "running",
            planCanRequestStop = true,
        )
        assertFalse(p.stopPlanEnabled)
    }

    @Test
    fun terminalRunRequiresExplicitLocalClearBeforeAnotherPreview() {
        val p = presentAgent3CockpitInteraction(
            busy = false,
            runState = "done",
            planCanRequestStop = true,
        )
        assertFalse(p.composerEnabled)
        assertFalse(p.stopPlanEnabled)
        assertTrue(p.clearTerminalRunEnabled)
        assertFalse(canAgent3CockpitPreview("ny opgave", busy = false, hasRun = true))
    }

    @Test
    fun busyTerminalRunCannotBeCleared() {
        val p = presentAgent3CockpitInteraction(
            busy = true,
            runState = "done",
            planCanRequestStop = false,
        )
        assertFalse(p.composerEnabled)
        assertFalse(p.stopPlanEnabled)
        assertFalse(p.clearTerminalRunEnabled)
    }
}
