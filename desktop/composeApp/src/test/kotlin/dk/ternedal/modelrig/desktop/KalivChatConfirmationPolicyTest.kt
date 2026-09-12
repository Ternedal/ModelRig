package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class KalivChatConfirmationPolicyTest {
    @Test
    fun idleWithoutConfirmationAllowsNewTurn() {
        val p = presentChatConfirmation(hasPendingConfirmation = false, busy = false)
        assertFalse(p.showCard)
        assertFalse(p.decisionEnabled)
        assertTrue(p.newTurnEnabled)
    }

    @Test
    fun pendingConfirmationStaysVisibleAndBlocksNewTurns() {
        val p = presentChatConfirmation(hasPendingConfirmation = true, busy = false)
        assertTrue(p.showCard)
        assertTrue(p.decisionEnabled)
        assertFalse(p.newTurnEnabled)
    }

    @Test
    fun decisionInFlightKeepsCardAndDisablesDuplicateActions() {
        val p = presentChatConfirmation(hasPendingConfirmation = true, busy = true)
        assertTrue(p.showCard)
        assertFalse(p.decisionEnabled)
        assertFalse(p.newTurnEnabled)
    }

    @Test
    fun ordinaryBusyChatTurnBlocksNewTurn() {
        val p = presentChatConfirmation(hasPendingConfirmation = false, busy = true)
        assertFalse(p.showCard)
        assertFalse(p.decisionEnabled)
        assertFalse(p.newTurnEnabled)
    }
}
