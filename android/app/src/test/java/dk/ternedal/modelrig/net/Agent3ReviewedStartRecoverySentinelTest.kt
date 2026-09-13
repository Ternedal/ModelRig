package dk.ternedal.modelrig.net

import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

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
