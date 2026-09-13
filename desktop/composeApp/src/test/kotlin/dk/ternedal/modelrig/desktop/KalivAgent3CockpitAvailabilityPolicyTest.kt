package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class KalivAgent3CockpitAvailabilityPolicyTest {
    @Test
    fun unavailableCurrentConnectionBlocksIdleCockpit() {
        assertTrue(
            shouldBlockAgent3CockpitForCurrentConnection(
                currentConnectionUnavailable = true,
                hasRun = false,
            ),
        )
    }

    @Test
    fun unavailableCurrentConnectionCannotHideExistingRunRecovery() {
        assertFalse(
            shouldBlockAgent3CockpitForCurrentConnection(
                currentConnectionUnavailable = true,
                hasRun = true,
            ),
        )
    }

    @Test
    fun availableCurrentConnectionNeverBlocksCockpit() {
        assertFalse(
            shouldBlockAgent3CockpitForCurrentConnection(
                currentConnectionUnavailable = false,
                hasRun = false,
            ),
        )
        assertFalse(
            shouldBlockAgent3CockpitForCurrentConnection(
                currentConnectionUnavailable = false,
                hasRun = true,
            ),
        )
    }
}
