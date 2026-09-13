package dk.ternedal.modelrig.desktop.net

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReviewedStartRecoverySentinelTest {
    @Test
    fun unreadableNonEmptyRecordRemainsUnresolved() {
        val raw = "{\"schema\":\"future-or-corrupt\"}"
        assertTrue(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(raw))
        assertNull(Agent3ReviewedStartRecoveryAuthority.decode(raw))
    }

    @Test
    fun onlyAbsentOrBlankRecordIsNotUnresolved() {
        assertFalse(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(null))
        assertFalse(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord(""))
        assertFalse(Agent3ReviewedStartRecoveryAuthority.hasUnresolvedRecord("   "))
    }
}
