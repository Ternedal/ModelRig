package dk.ternedal.modelrig.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test

class Agent3TaskStartRecoveryStoreTest {
    @Test
    fun `start recovery key is stable for the same normalized rig`() {
        assertEquals(
            agent3TaskStartRecoveryStorageKey("http://rig.local:8080"),
            agent3TaskStartRecoveryStorageKey("  http://rig.local:8080///  "),
        )
    }

    @Test
    fun `different rigs cannot share retained start recovery key`() {
        assertNotEquals(
            agent3TaskStartRecoveryStorageKey("http://rig-a.local:8080"),
            agent3TaskStartRecoveryStorageKey("http://rig-b.local:8080"),
        )
    }

    @Test
    fun `missing rig has no start recovery storage authority`() {
        assertNull(agent3TaskStartRecoveryStorageKey(null))
        assertNull(agent3TaskStartRecoveryStorageKey("   "))
    }
}
