package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
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

    @Test
    fun currentRefreshMayPublishRunEventsAndFailureState() {
        assertTrue(canPublishAgent3CockpitResponse(requestEpoch = 7L, currentEpoch = 7L))
    }

    @Test
    fun newerConfirmInvalidatesOlderRefreshPublication() {
        val refreshEpoch = 12L
        val confirmEpoch = nextAgent3CockpitPublicationEpoch(refreshEpoch)
        assertEquals(13L, confirmEpoch)
        assertFalse(canPublishAgent3CockpitResponse(refreshEpoch, confirmEpoch))
        assertTrue(canPublishAgent3CockpitResponse(confirmEpoch, confirmEpoch))
    }

    @Test
    fun newerStopInvalidatesOlderRefreshPublication() {
        val refreshEpoch = 31L
        val stopEpoch = nextAgent3CockpitPublicationEpoch(refreshEpoch)
        assertFalse(canPublishAgent3CockpitResponse(refreshEpoch, stopEpoch))
    }

    @Test
    fun staleSuccessAndFailureUseTheSameFailClosedPublicationRule() {
        val staleRequestEpoch = 4L
        val currentEpoch = 5L
        assertFalse(canPublishAgent3CockpitResponse(staleRequestEpoch, currentEpoch))
        assertFalse(canPublishAgent3CockpitResponse(staleRequestEpoch, currentEpoch))
    }

    @Test
    fun publicationEpochWrapsWithoutReusingTheCurrentMaxValue() {
        assertEquals(1L, nextAgent3CockpitPublicationEpoch(Long.MAX_VALUE))
    }

    @Test
    fun liveConfirmationIsActionableUntilServerExpiry() {
        val p = presentAgent3CockpitConfirmation(
            confirmationDigest = "a".repeat(64),
            confirmationExpiresAt = 120.0,
            stepState = "awaiting_confirmation",
            busy = false,
            nowEpochSeconds = 119.999,
        )
        assertEquals(Agent3CockpitConfirmationState.LIVE, p.state)
        assertTrue(p.actionEnabled)
        assertTrue(canAgent3CockpitDecide("a".repeat(64), 120.0, "awaiting_confirmation", false, 119.999))
    }

    @Test
    fun exactConfirmationExpiryBoundaryFailsClosed() {
        val p = presentAgent3CockpitConfirmation(
            confirmationDigest = "a".repeat(64),
            confirmationExpiresAt = 120.0,
            stepState = "awaiting_confirmation",
            busy = false,
            nowEpochSeconds = 120.0,
        )
        assertEquals(Agent3CockpitConfirmationState.EXPIRED, p.state)
        assertFalse(p.actionEnabled)
        assertFalse(canAgent3CockpitDecide("a".repeat(64), 120.0, "awaiting_confirmation", false, 120.0))
    }

    @Test
    fun expiredConfirmationRemainsVisibleButNotActionable() {
        val p = presentAgent3CockpitConfirmation(
            confirmationDigest = "a".repeat(64),
            confirmationExpiresAt = 120.0,
            stepState = "awaiting_confirmation",
            busy = false,
            nowEpochSeconds = 121.0,
        )
        assertEquals(Agent3CockpitConfirmationState.EXPIRED, p.state)
        assertFalse(p.actionEnabled)
    }

    @Test
    fun missingOrInvalidConfirmationExpiryFailsClosed() {
        val missing = presentAgent3CockpitConfirmation(
            confirmationDigest = "a".repeat(64),
            confirmationExpiresAt = null,
            stepState = "awaiting_confirmation",
            busy = false,
            nowEpochSeconds = 100.0,
        )
        val invalid = presentAgent3CockpitConfirmation(
            confirmationDigest = "a".repeat(64),
            confirmationExpiresAt = Double.NaN,
            stepState = "awaiting_confirmation",
            busy = false,
            nowEpochSeconds = 100.0,
        )
        assertEquals(Agent3CockpitConfirmationState.INVALID, missing.state)
        assertEquals(Agent3CockpitConfirmationState.INVALID, invalid.state)
        assertFalse(missing.actionEnabled)
        assertFalse(invalid.actionEnabled)
    }

    @Test
    fun busyLiveConfirmationRemainsVisibleButActionsAreBlocked() {
        val p = presentAgent3CockpitConfirmation(
            confirmationDigest = "a".repeat(64),
            confirmationExpiresAt = 120.0,
            stepState = "awaiting_confirmation",
            busy = true,
            nowEpochSeconds = 100.0,
        )
        assertEquals(Agent3CockpitConfirmationState.LIVE, p.state)
        assertFalse(p.actionEnabled)
    }

    @Test
    fun terminalStepHidesConfirmationEvenIfDigestAndFutureExpiryRemain() {
        val p = presentAgent3CockpitConfirmation(
            confirmationDigest = "a".repeat(64),
            confirmationExpiresAt = 120.0,
            stepState = "done",
            busy = false,
            nowEpochSeconds = 100.0,
        )
        assertEquals(Agent3CockpitConfirmationState.HIDDEN, p.state)
        assertFalse(p.actionEnabled)
    }
}
