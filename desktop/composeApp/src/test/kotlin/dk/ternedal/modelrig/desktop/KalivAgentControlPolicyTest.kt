package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class KalivAgentControlPolicyTest {
    @Test
    fun inFlightWorkerTurnExposesNoClearOrCancellationClaim() {
        val presentation = presentAgentClear(
            taskStarted = true,
            busy = true,
            hasPendingConfirmation = false,
            hasError = false,
        )

        assertFalse(presentation.visible)
        assertNull(presentation.label)
        assertFalse(presentation.claimsRemoteCancellation)
    }

    @Test
    fun pendingWriteConfirmationCannotBeClearedLocally() {
        val presentation = presentAgentClear(
            taskStarted = true,
            busy = false,
            hasPendingConfirmation = true,
            hasError = false,
        )

        assertFalse(presentation.visible)
        assertNull(presentation.label)
    }

    @Test
    fun failedOrUnknownTurnDoesNotExposeAResetThatCouldImplyCancellation() {
        val presentation = presentAgentClear(
            taskStarted = true,
            busy = false,
            hasPendingConfirmation = false,
            hasError = true,
        )

        assertFalse(presentation.visible)
        assertNull(presentation.label)
    }

    @Test
    fun completedLocalViewCanBeClearedWithoutRemoteCancellationLanguage() {
        val presentation = presentAgentClear(
            taskStarted = true,
            busy = false,
            hasPendingConfirmation = false,
            hasError = false,
        )

        assertTrue(presentation.visible)
        assertEquals("Ryd visning", presentation.label)
        assertFalse(presentation.claimsRemoteCancellation)
        assertFalse("afbryd" in presentation.label.orEmpty().lowercase())
        assertFalse("stop" in presentation.label.orEmpty().lowercase())
    }

    @Test
    fun idleAgentShowsNoClearAffordance() {
        val presentation = presentAgentClear(
            taskStarted = false,
            busy = false,
            hasPendingConfirmation = false,
            hasError = false,
        )

        assertFalse(presentation.visible)
        assertNull(presentation.label)
    }
}
