package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class KalivConversationBrowserPolicyTest {
    @Test
    fun productionEntryUsesHumanConversationLabel() {
        assertEquals("Samtaler", CONVERSATION_BROWSER_LABEL)
    }

    @Test
    fun idleConversationContextMayChange() {
        val p = presentConversationBrowser(busy = false, hasPendingConfirmation = false)
        assertTrue(p.contextMutationEnabled)
        assertNull(p.lockMessage)
    }

    @Test
    fun inFlightTurnLocksConversationIdentity() {
        val p = presentConversationBrowser(busy = true, hasPendingConfirmation = false)
        assertFalse(p.contextMutationEnabled)
        assertTrue(p.lockMessage?.contains("igangværende tur") == true)
    }

    @Test
    fun pendingConfirmationLocksConversationIdentity() {
        val p = presentConversationBrowser(busy = false, hasPendingConfirmation = true)
        assertFalse(p.contextMutationEnabled)
        assertTrue(p.lockMessage?.contains("værktøjsbekræftelse") == true)
    }

    @Test
    fun pendingConfirmationRemainsTheVisibleReasonWhileDecisionIsInFlight() {
        val p = presentConversationBrowser(busy = true, hasPendingConfirmation = true)
        assertFalse(p.contextMutationEnabled)
        assertTrue(p.lockMessage?.contains("værktøjsbekræftelse") == true)
    }
}
