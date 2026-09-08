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

    @Test
    fun capturedConversationLoadMayPublishWhileCurrent() {
        val epoch = KalivConversationPublicationEpoch()
        val captured = epoch.capture()
        assertTrue(epoch.mayPublish(captured))
    }

    @Test
    fun newerConversationActionInvalidatesOlderLoad() {
        val epoch = KalivConversationPublicationEpoch()
        val older = epoch.capture()
        val newer = epoch.advance()
        assertFalse(epoch.mayPublish(older))
        assertTrue(epoch.mayPublish(newer))
    }

    @Test
    fun secondOpenInvalidatesFirstOpen() {
        val epoch = KalivConversationPublicationEpoch()
        val firstOpen = epoch.advance()
        val secondOpen = epoch.advance()
        assertFalse(epoch.mayPublish(firstOpen))
        assertTrue(epoch.mayPublish(secondOpen))
    }

    @Test
    fun successfulDeleteInvalidatesPendingOpenLoad() {
        val epoch = KalivConversationPublicationEpoch()
        val pendingOpen = epoch.advance()
        val deleteEpoch = epoch.advance()
        assertFalse(epoch.mayPublish(pendingOpen))
        assertTrue(epoch.mayPublish(deleteEpoch))
    }

    @Test
    fun advanceWrapStillInvalidatesPreviousGeneration() {
        val epoch = KalivConversationPublicationEpoch(Long.MAX_VALUE)
        val beforeWrap = epoch.capture()
        val afterWrap = epoch.advance()
        assertEquals(Long.MIN_VALUE, afterWrap)
        assertFalse(epoch.mayPublish(beforeWrap))
        assertTrue(epoch.mayPublish(afterWrap))
    }
}
