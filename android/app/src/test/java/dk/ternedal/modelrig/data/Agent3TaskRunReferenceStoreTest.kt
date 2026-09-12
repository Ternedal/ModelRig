package dk.ternedal.modelrig.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test

class Agent3TaskRunReferenceStoreTest {
    @Test
    fun `run reference key is stable for the same normalized rig`() {
        assertEquals(
            agent3TaskRunReferenceStorageKey("http://rig.local:8080"),
            agent3TaskRunReferenceStorageKey("  http://rig.local:8080///  "),
        )
    }

    @Test
    fun `different rigs cannot share retained run reference key`() {
        assertNotEquals(
            agent3TaskRunReferenceStorageKey("http://rig-a.local:8080"),
            agent3TaskRunReferenceStorageKey("http://rig-b.local:8080"),
        )
    }

    @Test
    fun `missing rig has no recovery storage authority`() {
        assertNull(agent3TaskRunReferenceStorageKey(null))
        assertNull(agent3TaskRunReferenceStorageKey("   "))
    }
}
