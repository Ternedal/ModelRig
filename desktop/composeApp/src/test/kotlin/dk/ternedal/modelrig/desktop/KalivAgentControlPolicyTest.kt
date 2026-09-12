package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class KalivAgentControlPolicyTest {
    @Test
    fun inFlightWorkerTurnExposesNoClearOrCancellationClaim() {
        val presentation = presentAgentClear(true, true, false, false)
        assertFalse(presentation.visible)
        assertNull(presentation.label)
        assertFalse(presentation.claimsRemoteCancellation)
    }

    @Test
    fun pendingWriteConfirmationCannotBeClearedLocally() {
        val presentation = presentAgentClear(true, false, true, false)
        assertFalse(presentation.visible)
        assertNull(presentation.label)
    }

    @Test
    fun failedOrUnknownTurnDoesNotExposeReset() {
        val presentation = presentAgentClear(true, false, false, true)
        assertFalse(presentation.visible)
        assertNull(presentation.label)
    }

    @Test
    fun completedLocalViewCanBeClearedWithoutRemoteCancellationLanguage() {
        val presentation = presentAgentClear(true, false, false, false)
        assertTrue(presentation.visible)
        assertEquals("Ryd visning", presentation.label)
        assertFalse(presentation.claimsRemoteCancellation)
        assertFalse("afbryd" in presentation.label.orEmpty().lowercase())
        assertFalse("stop" in presentation.label.orEmpty().lowercase())
    }

    @Test
    fun idleAgentShowsNoClearAffordance() {
        val presentation = presentAgentClear(false, false, false, false)
        assertFalse(presentation.visible)
        assertNull(presentation.label)
    }
}
