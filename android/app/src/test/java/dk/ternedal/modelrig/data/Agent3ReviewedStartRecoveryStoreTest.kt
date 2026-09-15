package dk.ternedal.modelrig.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test

class Agent3ReviewedStartRecoveryStoreTest {
    @Test
    fun `reviewed recovery key is normalized and rig scoped`() {
        assertEquals(
            agent3ReviewedStartRecoveryStorageKey(" https://rig.example/ "),
            agent3ReviewedStartRecoveryStorageKey("https://rig.example"),
        )
        assertNotEquals(
            agent3ReviewedStartRecoveryStorageKey("https://rig-a.example"),
            agent3ReviewedStartRecoveryStorageKey("https://rig-b.example"),
        )
        assertNull(agent3ReviewedStartRecoveryStorageKey("  "))
    }
}
