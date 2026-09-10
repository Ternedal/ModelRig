package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class Agent3ReviewPreviewPolicyTest {
    private fun binding(base: String, token: String): Agent3DevConnectionBinding =
        requireNotNull(Agent3DevConnectionBinding.capture(base, token))

    @Test
    fun startAcceptsExactNormalizedOriginatingConnection() {
        val previewConnection = binding("http://rig-a:8080", "token-a")
        val currentConnection = binding("  http://rig-a:8080/// ", " token-a ")
        assertTrue(
            Agent3ReviewPreviewPolicy.canStart(
                planId = "plan-1",
                planSize = 1,
                busy = false,
                currentConnection = currentConnection,
                previewConnection = previewConnection,
            )
        )
    }

    @Test
    fun startRejectsUrlOrCredentialDrift() {
        val previewConnection = binding("http://rig-a:8080", "token-a")
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", 1, false,
                binding("http://rig-b:8080", "token-a"), previewConnection,
            )
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", 1, false,
                binding("http://rig-a:8080", "token-b"), previewConnection,
            )
        )
    }

    @Test
    fun startRejectsMissingConnectionAuthority() {
        val previewConnection = binding("http://rig-a:8080", "token-a")
        assertFalse(Agent3ReviewPreviewPolicy.canStart("plan-1", 1, false, null, previewConnection))
        assertFalse(Agent3ReviewPreviewPolicy.canStart("plan-1", 1, false, previewConnection, null))
        assertFalse(Agent3ReviewPreviewPolicy.canStart("plan-1", 1, false, null, null))
    }

    @Test
    fun startRetainsExistingPlanAndBusyGuards() {
        val connection = binding("http://rig-a:8080", "token-a")
        assertFalse(Agent3ReviewPreviewPolicy.canStart(null, 1, false, connection, connection))
        assertFalse(Agent3ReviewPreviewPolicy.canStart("", 1, false, connection, connection))
        assertFalse(Agent3ReviewPreviewPolicy.canStart("plan-1", 0, false, connection, connection))
        assertFalse(Agent3ReviewPreviewPolicy.canStart("plan-1", 1, true, connection, connection))
    }
}
