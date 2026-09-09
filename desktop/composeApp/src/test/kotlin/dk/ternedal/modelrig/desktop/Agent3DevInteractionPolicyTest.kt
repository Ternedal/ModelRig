package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3DevInteractionPolicyTest {
    private val connection = binding("http://rig-a:8080", "token-a")

    private fun binding(base: String, token: String): Agent3DevConnectionBinding =
        requireNotNull(Agent3DevConnectionBinding.capture(base, token))

    @Test fun connectionBindingNormalizesWithoutExposingCredential() {
        val value = binding("  http://rig-a:8080///  ", "  secret-token  ")
        assertEquals("http://rig-a:8080", value.baseUrl)
        assertEquals("secret-token", value.token)
        assertFalse(value.toString().contains("secret-token"))
        assertTrue(value.toString().contains("<redacted>"))
    }

    @Test fun blankConnectionFailsClosed() {
        assertNull(Agent3DevConnectionBinding.capture("   ", "token"))
        assertNull(Agent3DevConnectionBinding.capture("http://rig", "   "))
    }

    @Test fun equivalentConnectionMatchesButUrlOrTokenDriftDoesNot() {
        assertEquals(connection, binding(" http://rig-a:8080/ ", " token-a "))
        assertFalse(connection == binding("http://rig-b:8080", "token-a"))
        assertFalse(connection == binding("http://rig-a:8080", "token-b"))
    }

    @Test fun idleSurfaceMayPreview() = assertTrue(
        Agent3DevInteractionPolicy.canPreview("status", false, null)
    )

    @Test fun blankOrBusyPreviewFailsClosed() {
        assertFalse(Agent3DevInteractionPolicy.canPreview("   ", false, null))
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", true, null))
    }

    @Test fun activeWaitingAndUnknownRunsRetainAuthority() {
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", false, "running"))
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", false, "waiting_confirmation"))
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", false, "future_state"))
    }

    @Test fun terminalRunWithExecutingToolCannotBeReplaced() = assertFalse(
        Agent3DevInteractionPolicy.canPreview(
            "status", false, "cancelled", "executing", "unavailable"
        )
    )

    @Test fun terminalRunWithPendingToolRequestCannotBeReplaced() = assertFalse(
        Agent3DevInteractionPolicy.canPreview(
            "status", false, "cancelled", "completed_after_cancel", "pending"
        )
    )

    @Test fun fullyTerminalRunMayBeReplaced() {
        assertTrue(Agent3DevInteractionPolicy.canPreview("ny opgave", false, "completed"))
        assertTrue(
            Agent3DevInteractionPolicy.canPreview(
                "ny opgave", false, "cancelled", "completed_after_cancel", "terminal"
            )
        )
    }

    @Test fun startRequiresUsablePreviewNoRunAndExactConnection() {
        assertTrue(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, null, false, false, connection, connection
            )
        )
        assertTrue(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, true, false, false, connection, connection
            )
        )
        assertFalse(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, false, false, false, connection, connection
            )
        )
        assertFalse(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, true, false, true, connection, connection
            )
        )
    }

    @Test fun startFailsClosedOnConnectionDriftOrMissingBinding() {
        val otherUrl = binding("http://rig-b:8080", "token-a")
        val otherToken = binding("http://rig-a:8080", "token-b")
        assertFalse(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, true, false, false, otherUrl, connection
            )
        )
        assertFalse(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, true, false, false, otherToken, connection
            )
        )
        assertFalse(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, true, false, false, connection, null
            )
        )
        assertFalse(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, true, false, false, null, connection
            )
        )
    }

    @Test fun startRejectsBusyMissingOrEmptyPreview() {
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 1, true, true, false, connection, connection))
        assertFalse(Agent3DevInteractionPolicy.canStart(null, 1, true, false, false, connection, connection))
        assertFalse(Agent3DevInteractionPolicy.canStart("", 1, true, false, false, connection, connection))
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 0, true, false, false, connection, connection))
    }
}
