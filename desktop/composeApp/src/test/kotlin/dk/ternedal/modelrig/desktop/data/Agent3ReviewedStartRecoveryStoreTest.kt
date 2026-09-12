package dk.ternedal.modelrig.desktop.data

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNull

class Agent3ReviewedStartRecoveryStoreTest {
    @Test
    fun reviewedRecoveryKeyIsNormalizedAndRigScoped() {
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
