package dk.ternedal.modelrig.ui

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent4ResponseEpochTest {
    private val first = Agent4ConnectionIdentity("http://rig-a:8080", "token-a")
    private val second = Agent4ConnectionIdentity("http://rig-a:8080", "token-b")

    @Test
    fun currentTicketIsAccepted() {
        val guard = Agent4ResponseEpoch()
        val ticket = guard.begin(first)

        assertTrue(guard.accepts(ticket, first))
    }

    @Test
    fun olderSuccessOrFailureIsRejectedAfterNewInitialLoad() {
        val guard = Agent4ResponseEpoch()
        val stale = guard.begin(first)
        val current = guard.begin(first)

        assertFalse(guard.accepts(stale, first))
        assertTrue(guard.accepts(current, first))
    }

    @Test
    fun credentialDriftRejectsCapturedPagingTicket() {
        val guard = Agent4ResponseEpoch()
        guard.begin(first)
        val paging = guard.capture(first)

        assertFalse(guard.accepts(paging, second))
        assertFalse(guard.accepts(paging, null))
        assertTrue(guard.accepts(paging, first))
    }

    @Test
    fun explicitInvalidationRejectsPendingSuccessFailureAndFinally() {
        val guard = Agent4ResponseEpoch()
        val pending = guard.begin(first)

        guard.invalidate()

        assertFalse(guard.accepts(pending, first))
    }
}
