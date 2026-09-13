package dk.ternedal.modelrig.desktop.data

import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReviewedStartRecoveryPersistenceTest {
    private object TestProtector : CredentialProtector {
        override fun protect(plaintext: String): String = "test:$plaintext"
        override fun unprotect(envelope: String): String = envelope.removePrefix("test:")
        override fun isProtected(value: String): Boolean = value.startsWith("test:")
    }

    @Test
    fun authorityReservationIsCrossConnectionCasAndRigScoped() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-", ".db").toString()
        val rigA = "https://rig-a.example:8443/"
        val rigB = "https://rig-b.example:8443"
        val first = "{\"schema\":\"authority-a\"}"
        val second = "{\"schema\":\"authority-b\"}"

        DesktopChatDb(dbPath, TestProtector).use { dbA ->
            DesktopChatDb(dbPath, TestProtector).use { dbB ->
                val storeA = Agent3ReviewedStartRecoveryStore(dbA)
                val storeB = Agent3ReviewedStartRecoveryStore(dbB)
                assertTrue(storeA.reserve(rigA, first))
                assertFalse(storeB.reserve(rigA, second))
                assertEquals(first, storeB.read("https://rig-a.example:8443"))
                assertFalse(storeB.clearIfMatches(rigA, second))
                assertEquals(first, storeA.read(rigA))
                assertNull(storeA.read(rigB))
                assertTrue(storeA.clearIfMatches(rigA, first))
                assertNull(storeB.read(rigA))
            }
        }
    }
}
