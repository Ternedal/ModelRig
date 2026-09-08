package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class KalivAgentConfirmationPolicyTest {
    @Test
    fun idleWithoutPendingConfirmationAllowsNewTurn() {
        val p = presentAgentConfirmation(hasPendingConfirmation = false, busy = false)
        assertFalse(p.showCard)
        assertFalse(p.decisionEnabled)
        assertTrue(p.newTurnEnabled)
    }

    @Test
    fun pendingConfirmationStaysVisibleAndBlocksNewTurns() {
        val p = presentAgentConfirmation(hasPendingConfirmation = true, busy = false)
        assertTrue(p.showCard)
        assertTrue(p.decisionEnabled)
        assertFalse(p.newTurnEnabled)
    }

    @Test
    fun decisionInFlightKeepsCardButDisablesDuplicateDecisionAndNewTurn() {
        val p = presentAgentConfirmation(hasPendingConfirmation = true, busy = true)
        assertTrue(p.showCard)
        assertFalse(p.decisionEnabled)
        assertFalse(p.newTurnEnabled)
    }

    @Test
    fun ordinaryWorkerTurnBlocksNewTurnWithoutInventingConfirmation() {
        val p = presentAgentConfirmation(hasPendingConfirmation = false, busy = true)
        assertFalse(p.showCard)
        assertFalse(p.decisionEnabled)
        assertFalse(p.newTurnEnabled)
    }
}
