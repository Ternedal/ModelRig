package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewConnectionBindingTest {
    private val connection = binding("http://rig-a:8080", "token-a")

    private fun binding(base: String, token: String): Agent3ReviewConnectionBinding =
        requireNotNull(Agent3ReviewConnectionBinding.capture(base, token))

    @Test
    fun connectionBindingNormalizesWithoutExposingCredential() {
        val value = binding("  http://rig-a:8080///  ", "  secret-token  ")
        assertEquals("http://rig-a:8080", value.baseUrl)
        assertEquals("secret-token", value.token)
        assertFalse(value.toString().contains("secret-token"))
        assertTrue(value.toString().contains("<redacted>"))
    }

    @Test
    fun blankConnectionFailsClosed() {
        assertNull(Agent3ReviewConnectionBinding.capture(null, "token"))
        assertNull(Agent3ReviewConnectionBinding.capture("   ", "token"))
        assertNull(Agent3ReviewConnectionBinding.capture("http://rig", null))
        assertNull(Agent3ReviewConnectionBinding.capture("http://rig", "   "))
    }

    @Test
    fun equivalentConnectionMatchesButUrlOrTokenDriftDoesNot() {
        assertEquals(connection, binding(" http://rig-a:8080/ ", " token-a "))
        assertFalse(connection == binding("http://rig-b:8080", "token-a"))
        assertFalse(connection == binding("http://rig-a:8080", "token-b"))
    }

    @Test
    fun reviewedStartRequiresExactConnectionBinding() {
        assertTrue(
            Agent3ReviewConnectionPolicy.canStart(
                planId = "plan-1",
                hasSteps = true,
                busy = false,
                hasRun = false,
                currentConnection = connection,
                previewConnection = connection,
            ),
        )
        assertFalse(
            Agent3ReviewConnectionPolicy.canStart(
                planId = "plan-1",
                hasSteps = true,
                busy = false,
                hasRun = false,
                currentConnection = binding("http://rig-b:8080", "token-a"),
                previewConnection = connection,
            ),
        )
        assertFalse(
            Agent3ReviewConnectionPolicy.canStart(
                planId = "plan-1",
                hasSteps = true,
                busy = false,
                hasRun = false,
                currentConnection = binding("http://rig-a:8080", "token-b"),
                previewConnection = connection,
            ),
        )
        assertFalse(
            Agent3ReviewConnectionPolicy.canStart(
                planId = "plan-1",
                hasSteps = true,
                busy = false,
                hasRun = false,
                currentConnection = null,
                previewConnection = connection,
            ),
        )
        assertFalse(
            Agent3ReviewConnectionPolicy.canStart(
                planId = "plan-1",
                hasSteps = true,
                busy = false,
                hasRun = false,
                currentConnection = connection,
                previewConnection = null,
            ),
        )
    }

    @Test
    fun reviewedStartStillFailsClosedOnExistingPreviewGuards() {
        assertFalse(Agent3ReviewConnectionPolicy.canStart(null, true, false, false, connection, connection))
        assertFalse(Agent3ReviewConnectionPolicy.canStart("plan-1", false, false, false, connection, connection))
        assertFalse(Agent3ReviewConnectionPolicy.canStart("plan-1", true, true, false, connection, connection))
        assertFalse(Agent3ReviewConnectionPolicy.canStart("plan-1", true, false, true, connection, connection))
    }
}
