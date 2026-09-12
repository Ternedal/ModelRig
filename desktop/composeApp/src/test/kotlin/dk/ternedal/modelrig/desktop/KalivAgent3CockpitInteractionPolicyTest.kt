package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class KalivAgent3CockpitInteractionPolicyTest {
    @Test
    fun idleCockpitAllowsPreview() {
        assertTrue(canAgent3CockpitPreview("undersøg status", busy = false, hasRun = false))
        assertTrue(presentAgent3CockpitInteraction(busy = false, runState = null).composerEnabled)
    }

    @Test
    fun busyCockpitBlocksPreview() {
        assertFalse(canAgent3CockpitPreview("undersøg status", busy = true, hasRun = false))
        assertFalse(presentAgent3CockpitInteraction(busy = true, runState = null).composerEnabled)
    }

    @Test
    fun activeRunBlocksAnotherPreview() {
        assertFalse(canAgent3CockpitPreview("ny opgave", busy = false, hasRun = true))
        val p = presentAgent3CockpitInteraction(busy = false, runState = "running")
        assertFalse(p.composerEnabled)
        assertFalse(p.clearTerminalRunEnabled)
    }

    @Test
    fun awaitingConfirmationRunCannotBeHiddenByNewPreviewOrLocalClear() {
        assertFalse(canAgent3CockpitPreview("ny opgave", busy = false, hasRun = true))
        val p = presentAgent3CockpitInteraction(busy = false, runState = "awaiting_confirmation")
        assertFalse(p.composerEnabled)
        assertFalse(p.clearTerminalRunEnabled)
    }

    @Test
    fun terminalRunRequiresExplicitLocalClearBeforeAnotherPreview() {
        val p = presentAgent3CockpitInteraction(busy = false, runState = "done")
        assertFalse(p.composerEnabled)
        assertTrue(p.clearTerminalRunEnabled)
        assertFalse(canAgent3CockpitPreview("ny opgave", busy = false, hasRun = true))
    }

    @Test
    fun busyTerminalRunCannotBeCleared() {
        val p = presentAgent3CockpitInteraction(busy = true, runState = "done")
        assertFalse(p.composerEnabled)
        assertFalse(p.clearTerminalRunEnabled)
    }
}
