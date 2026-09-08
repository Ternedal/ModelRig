package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class KalivAgent3CockpitInteractionPolicyTest {
    @Test
    fun idleCockpitAllowsPreviewButNoPreviewActionsWithoutPreview() {
        assertTrue(canAgent3CockpitPreview("undersøg status", busy = false, hasRun = false))
        val p = presentAgent3CockpitInteraction(busy = false, runState = null)
        assertTrue(p.composerEnabled)
        assertFalse(p.previewStartEnabled)
        assertFalse(p.previewDiscardEnabled)
        assertFalse(p.stopPlanEnabled)
    }

    @Test
    fun idlePreviewAllowsStartAndLocalDiscard() {
        val p = presentAgent3CockpitInteraction(
            busy = false,
            runState = null,
            hasPreview = true,
        )
        assertTrue(p.previewStartEnabled)
        assertTrue(p.previewDiscardEnabled)
    }

    @Test
    fun busyPreviewBlocksStartAndDiscard() {
        assertFalse(canAgent3CockpitPreview("undersøg status", busy = true, hasRun = false))
        val p = presentAgent3CockpitInteraction(
            busy = true,
            runState = null,
            hasPreview = true,
        )
        assertFalse(p.composerEnabled)
        assertFalse(p.previewStartEnabled)
        assertFalse(p.previewDiscardEnabled)
        assertFalse(p.stopPlanEnabled)
    }

    @Test
    fun existingRunBlocksPreviewStartAndDiscardEvenIfStalePreviewFlagExists() {
        val p = presentAgent3CockpitInteraction(
            busy = false,
            runState = "running",
            planCanRequestStop = false,
            hasPreview = true,
        )
        assertFalse(p.composerEnabled)
        assertFalse(p.previewStartEnabled)
        assertFalse(p.previewDiscardEnabled)
        assertFalse(p.stopPlanEnabled)
        assertFalse(p.clearTerminalRunEnabled)
    }

    @Test
    fun activeRunBlocksAnotherPreviewAndNeedsServerStopAuthority() {
        assertFalse(canAgent3CockpitPreview("ny opgave", busy = false, hasRun = true))
        val blocked = presentAgent3CockpitInteraction(
            busy = false,
            runState = "running",
            planCanRequestStop = false,
        )
        assertFalse(blocked.stopPlanEnabled)

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
        assertFalse(p.previewStartEnabled)
        assertFalse(p.previewDiscardEnabled)
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
            hasPreview = true,
        )
        assertFalse(p.composerEnabled)
        assertFalse(p.previewStartEnabled)
        assertFalse(p.previewDiscardEnabled)
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
        assertFalse(p.previewStartEnabled)
        assertFalse(p.previewDiscardEnabled)
        assertFalse(p.stopPlanEnabled)
        assertFalse(p.clearTerminalRunEnabled)
    }
}
