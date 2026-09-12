package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class Agent3ConfirmationConsumedPresentationTest {
    @Test
    fun consumedLiveConfirmationRemainsVisibleButCannotBeReused() {
        val p = presentAgent3CockpitConfirmation(
            confirmationDigest = "a".repeat(64),
            confirmationExpiresAt = 200.0,
            runState = "waiting_confirmation",
            stepState = "awaiting_confirmation",
            busy = false,
            nowEpochSeconds = 100.0,
            confirmationConsumed = true,
        )
        assertEquals(Agent3CockpitConfirmationState.CONSUMED, p.state)
        assertFalse(p.actionEnabled)
        assertFalse(
            canAgent3CockpitDecide(
                "a".repeat(64),
                200.0,
                "waiting_confirmation",
                "awaiting_confirmation",
                false,
                100.0,
                confirmationConsumed = true,
            ),
        )
    }

    @Test
    fun freshServerAuthorityRemainsActionable() {
        val p = presentAgent3CockpitConfirmation(
            confirmationDigest = "b".repeat(64),
            confirmationExpiresAt = 200.0,
            runState = "waiting_confirmation",
            stepState = "awaiting_confirmation",
            busy = false,
            nowEpochSeconds = 100.0,
            confirmationConsumed = false,
        )
        assertEquals(Agent3CockpitConfirmationState.LIVE, p.state)
        assertTrue(p.actionEnabled)
    }

    @Test
    fun consumedAuthorityDoesNotOverrideTerminalServerTruth() {
        val p = presentAgent3CockpitConfirmation(
            confirmationDigest = "a".repeat(64),
            confirmationExpiresAt = 200.0,
            runState = "completed",
            stepState = "succeeded",
            busy = false,
            nowEpochSeconds = 100.0,
            confirmationConsumed = true,
        )
        assertEquals(Agent3CockpitConfirmationState.HIDDEN, p.state)
        assertFalse(p.actionEnabled)
    }
}
